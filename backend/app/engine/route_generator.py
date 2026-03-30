"""
Route generator: builds complete cycling routes from workout + terrain + weather.

Generates 3 route variants:
    A: maximize wind optimization
    B: maximize climb quality
    C: balanced compromise (weighted by config)

CRITICAL INVARIANT: The route is always continuous. Each segment starts
exactly where the previous one ended. No teleportation.
"""

import logging
import math
from dataclasses import dataclass

import networkx as nx
import osmnx as ox

from app.cache.osm_cache import enrich_elevations, load_or_fetch_graph
from app.config import settings
from app.engine.climb_finder import detect_climbs, select_climbs_for_workout
from app.engine.physics import estimate_speed_flat, power_to_speed
from app.engine.sunshine_scorer import score_sunshine
from app.engine.timing import (
    compute_block_distances,
    compute_cooldown_reach_km,
    compute_elastic_max,
    compute_warmup_reach_km,
)
from app.engine.wind_optimizer import (
    bearing_penalty,
    compute_edge_bearing,
    preferred_outbound_bearing,
    preferred_return_bearing,
)
from app.models.athlete import AthleteProfile
from app.models.route import ClimbCandidate, Route, RouteSegment
from app.models.weather import WeatherForecast
from app.models.workout import BlockType, ParsedWorkout, WorkoutBlock

logger = logging.getLogger(__name__)


@dataclass
class GenerationParams:
    lat: float
    lon: float
    athlete: AthleteProfile
    workout: ParsedWorkout
    forecast: WeatherForecast
    climb_mode: str = "auto"
    road_type: str = "road"
    max_radius_km: float = 50.0
    weights: dict | None = None


async def generate_routes(params: GenerationParams) -> list[Route]:
    """Generate 3 route variants for a workout."""
    workout = params.workout
    athlete = params.athlete
    forecast = params.forecast
    weather = forecast.current

    # ── Step 1: Estimate speeds and distances ────────────────────
    blocks = workout.blocks
    speeds = _estimate_block_speeds(blocks, athlete, weather)
    block_distances = compute_block_distances(blocks, speeds)

    total_distance_m = sum(bd["distance_m"] for bd in block_distances)
    warmup_reach_km = compute_warmup_reach_km(blocks, speeds)

    # ── Step 2: Calculate search radius ──────────────────────────
    radius_m = min(
        total_distance_m / (2 * math.pi) * 1.2,
        params.max_radius_km * 1000,
    )
    radius_m = max(radius_m, 3000)

    logger.info(
        "Estimated total distance: %.1f km, search radius: %.1f km",
        total_distance_m / 1000,
        radius_m / 1000,
    )

    # ── Step 3: Load graph and enrich elevations ─────────────────
    graph = load_or_fetch_graph(
        params.lat, params.lon, radius_m, network_type="bike"
    )
    graph = enrich_elevations(graph)

    # ── Step 4: Find start node ──────────────────────────────────
    start_node = ox.nearest_nodes(graph, params.lon, params.lat)

    # ── Step 5: Detect and select climbs ─────────────────────────
    selected_climbs = []
    climb_mode_used = params.climb_mode

    if workout.has_intervals:
        climbs = detect_climbs(graph)
        if climbs:
            selected_climbs, climb_mode_used = select_climbs_for_workout(
                climbs=climbs,
                interval_blocks=workout.interval_blocks,
                athlete=athlete,
                climb_mode=params.climb_mode,
                wind_speed_ms=weather.wind_speed_ms,
                temp_c=weather.temperature_c,
            )

    # ── Step 6: Wind bearings ────────────────────────────────────
    wind_dir = weather.wind_direction_deg
    outbound_bearing = preferred_outbound_bearing(wind_dir)
    return_bearing = preferred_return_bearing(wind_dir)

    # ── Step 7: Generate 3 variants ──────────────────────────────
    weight_sets = _get_weight_sets(params.weights)
    variants = []

    for variant_name, weights in weight_sets.items():
        try:
            route = _build_single_route(
                graph=graph,
                start_node=start_node,
                blocks=blocks,
                speeds=speeds,
                athlete=athlete,
                forecast=forecast,
                selected_climbs=selected_climbs,
                climb_mode=climb_mode_used,
                outbound_bearing=outbound_bearing,
                return_bearing=return_bearing,
                variant=variant_name,
                weights=weights,
                warmup_reach_km=warmup_reach_km,
            )
            variants.append(route)
        except Exception as e:
            logger.error("Failed to generate variant %s: %s", variant_name, e)
            continue

    variants.sort(key=lambda r: r.overall_score, reverse=True)
    return variants


def _estimate_block_speeds(
    blocks: list[WorkoutBlock],
    athlete: AthleteProfile,
    weather,
) -> list[float]:
    speeds = []
    for block in blocks:
        speed = estimate_speed_flat(
            power_w=block.power_watts,
            cda=athlete.get_cda(),
            weight_kg=athlete.weight_kg,
            bike_weight_kg=athlete.bike_weight_kg,
            crr=athlete.crr,
            temp_c=weather.temperature_c,
        )
        speeds.append(speed)
    return speeds


def _get_weight_sets(custom_weights: dict | None = None) -> dict[str, dict]:
    return {
        "A": {"wind": 0.60, "climb": 0.25, "sunshine": 0.10, "heatmap": 0.05},
        "B": {"wind": 0.15, "climb": 0.60, "sunshine": 0.15, "heatmap": 0.10},
        "C": custom_weights or {
            "wind": settings.wind_weight,
            "climb": settings.climb_weight,
            "sunshine": settings.sunshine_weight,
            "heatmap": settings.heatmap_weight,
        },
    }


def _build_single_route(
    graph: nx.MultiDiGraph,
    start_node: int,
    blocks: list[WorkoutBlock],
    speeds: list[float],
    athlete: AthleteProfile,
    forecast: WeatherForecast,
    selected_climbs: list[ClimbCandidate],
    climb_mode: str,
    outbound_bearing: float,
    return_bearing: float,
    variant: str,
    weights: dict,
    warmup_reach_km: float,
) -> Route:
    """Build a single route variant.

    INVARIANT: `current_node` tracks where the cyclist is at all times.
    Every path starts from `current_node` and updates it to the path's end.
    """
    weather = forecast.current
    route = Route(variant=variant)
    warnings = []

    all_nodes = [start_node]
    all_coords = [_node_to_coord(graph, start_node)]
    segments = []
    current_node = start_node

    warmup_blocks = [b for b in blocks if b.block_type == BlockType.WARMUP]
    warmup_duration = sum(b.duration_seconds for b in warmup_blocks) if warmup_blocks else settings.warmup_min_duration_s

    # ── Phase 1: Outbound (warmup) ───────────────────────────────

    if selected_climbs:
        target_node = selected_climbs[0].start_node

        path = _find_path(graph, current_node, target_node, outbound_bearing, weights["wind"])
        if path:
            path_nodes, path_dist = path
            warmup_speed = speeds[0] if speeds else 7.0
            actual_duration = path_dist / warmup_speed

            warmup_max = compute_elastic_max(warmup_duration)
            if actual_duration > warmup_max:
                warnings.append(
                    f"Montée à {path_dist/1000:.1f} km, "
                    f"budget échauffement max = {warmup_reach_km:.1f} km"
                )

            route.warmup_duration_initial_s = warmup_duration
            route.warmup_duration_actual_s = int(actual_duration)
            route.warmup_distance_km = path_dist / 1000

            current_node = _append_path(graph, path_nodes, all_nodes, all_coords)
            segments.append(RouteSegment(
                block_index=0,
                block_type="warmup",
                nodes=path_nodes,
                coords=_nodes_to_coords(graph, path_nodes),
                distance_m=path_dist,
                duration_s=actual_duration,
                power_target=warmup_blocks[0].power_watts if warmup_blocks else 0,
                avg_speed_ms=warmup_speed,
            ))
    else:
        # No climbs: outbound loop
        far_node = _find_far_node(graph, start_node, outbound_bearing, warmup_reach_km * 500)
        if far_node and far_node != start_node:
            path = _find_path(graph, current_node, far_node, outbound_bearing, weights["wind"])
            if path:
                path_nodes, path_dist = path
                current_node = _append_path(graph, path_nodes, all_nodes, all_coords)
                segments.append(RouteSegment(
                    block_index=0,
                    block_type="warmup",
                    nodes=path_nodes,
                    coords=_nodes_to_coords(graph, path_nodes),
                    distance_m=path_dist,
                    duration_s=path_dist / (speeds[0] if speeds else 7.0),
                    power_target=warmup_blocks[0].power_watts if warmup_blocks else 0,
                ))

    # ── Phase 2: Climb segments (intervals) ──────────────────────

    if selected_climbs and workout_has_intervals(blocks):
        interval_blocks = [b for b in blocks if b.is_effort]

        if climb_mode == "repeat":
            climb = selected_climbs[0]
            for i, block in enumerate(interval_blocks):
                # Route to climb start if not already there
                if current_node != climb.start_node:
                    transfer = _find_path(graph, current_node, climb.start_node)
                    if transfer:
                        t_nodes, t_dist = transfer
                        current_node = _append_path(graph, t_nodes, all_nodes, all_coords)

                # Ascent
                climb_path = _find_path(graph, current_node, climb.end_node)
                if climb_path:
                    c_nodes, c_dist = climb_path
                    c_speed = power_to_speed(
                        block.power_watts, climb.avg_grade_percent,
                        0.0, athlete.get_cda(), athlete.weight_kg,
                        athlete.bike_weight_kg, athlete.crr,
                        weather.temperature_c,
                    )
                    current_node = _append_path(graph, c_nodes, all_nodes, all_coords)
                    segments.append(RouteSegment(
                        block_index=block.index,
                        block_type="interval",
                        nodes=c_nodes,
                        coords=_nodes_to_coords(graph, c_nodes),
                        distance_m=c_dist,
                        duration_s=c_dist / c_speed if c_speed > 0 else block.duration_seconds,
                        power_target=block.power_watts,
                        avg_speed_ms=c_speed,
                        avg_grade_percent=climb.avg_grade_percent,
                        climb=climb,
                    ))

                # Descent (recovery between repeats, except after last)
                if i < len(interval_blocks) - 1:
                    desc_path = _find_path(graph, current_node, climb.start_node)
                    if desc_path:
                        d_nodes, d_dist = desc_path
                        d_speed = power_to_speed(
                            athlete.ftp_watts * 0.5, -climb.avg_grade_percent,
                            0.0, athlete.get_cda("drops"), athlete.weight_kg,
                            athlete.bike_weight_kg, athlete.crr,
                            weather.temperature_c,
                        )
                        current_node = _append_path(graph, d_nodes, all_nodes, all_coords)
                        segments.append(RouteSegment(
                            block_index=block.index,
                            block_type="recovery",
                            nodes=d_nodes,
                            coords=_nodes_to_coords(graph, d_nodes),
                            distance_m=d_dist,
                            duration_s=d_dist / d_speed if d_speed > 0 else 180,
                            power_target=athlete.ftp_watts * 0.5,
                            avg_speed_ms=d_speed,
                            avg_grade_percent=-climb.avg_grade_percent,
                        ))

        elif climb_mode == "loop":
            for i, (block, climb) in enumerate(zip(interval_blocks, selected_climbs)):
                # Route to this climb's start
                if current_node != climb.start_node:
                    transfer = _find_path(graph, current_node, climb.start_node)
                    if transfer:
                        t_nodes, t_dist = transfer
                        current_node = _append_path(graph, t_nodes, all_nodes, all_coords)
                        segments.append(RouteSegment(
                            block_index=block.index,
                            block_type="recovery",
                            nodes=t_nodes,
                            coords=_nodes_to_coords(graph, t_nodes),
                            distance_m=t_dist,
                            duration_s=t_dist / (speeds[block.index] if block.index < len(speeds) else 7.0),
                        ))

                # Climb
                climb_path = _find_path(graph, current_node, climb.end_node)
                if climb_path:
                    c_nodes, c_dist = climb_path
                    c_speed = power_to_speed(
                        block.power_watts, climb.avg_grade_percent,
                        0.0, athlete.get_cda(), athlete.weight_kg,
                        athlete.bike_weight_kg, athlete.crr,
                        weather.temperature_c,
                    )
                    current_node = _append_path(graph, c_nodes, all_nodes, all_coords)
                    segments.append(RouteSegment(
                        block_index=block.index,
                        block_type="interval",
                        nodes=c_nodes,
                        coords=_nodes_to_coords(graph, c_nodes),
                        distance_m=c_dist,
                        duration_s=c_dist / c_speed if c_speed > 0 else block.duration_seconds,
                        power_target=block.power_watts,
                        avg_speed_ms=c_speed,
                        avg_grade_percent=climb.avg_grade_percent,
                        climb=climb,
                    ))

    # ── Phase 3: Return (cooldown) ───────────────────────────────

    if current_node != start_node:
        return_path = _find_path(graph, current_node, start_node, return_bearing, weights["wind"])
        if return_path:
            r_nodes, r_dist = return_path
            cooldown_blocks = [b for b in blocks if b.block_type == BlockType.COOLDOWN]
            cooldown_duration = sum(b.duration_seconds for b in cooldown_blocks) if cooldown_blocks else settings.cooldown_min_duration_s
            cooldown_speed = speeds[-1] if speeds else 7.0

            route.cooldown_duration_initial_s = cooldown_duration
            route.cooldown_duration_actual_s = int(r_dist / cooldown_speed)
            route.cooldown_distance_km = r_dist / 1000

            current_node = _append_path(graph, r_nodes, all_nodes, all_coords)
            segments.append(RouteSegment(
                block_index=len(blocks) - 1,
                block_type="cooldown",
                nodes=r_nodes,
                coords=_nodes_to_coords(graph, r_nodes),
                distance_m=r_dist,
                duration_s=r_dist / cooldown_speed,
                power_target=cooldown_blocks[0].power_watts if cooldown_blocks else 0,
                avg_speed_ms=cooldown_speed,
            ))

    # ── Phase 4: Compute scores ──────────────────────────────────

    route.nodes = all_nodes
    route.coords = all_coords
    route.segments = segments
    route.climbs = selected_climbs
    route.warnings = warnings

    route.total_distance_km = sum(s.distance_m for s in segments) / 1000
    route.total_elevation_m = _compute_total_elevation(all_coords)
    route.estimated_duration_s = int(sum(s.duration_s for s in segments))

    route.wind_score = _compute_wind_score(segments, weather.wind_direction_deg)
    route.climb_score = _compute_climb_score(selected_climbs, blocks)

    seg_hours = [sum(s.duration_s for s in segments[:i]) / 3600 for i in range(len(segments))]
    seg_durations = [s.duration_s for s in segments]
    route.sunshine_score = score_sunshine(forecast, seg_hours, seg_durations)

    route.overall_score = (
        weights["wind"] * route.wind_score
        + weights["climb"] * route.climb_score
        + weights["sunshine"] * route.sunshine_score
        + weights["heatmap"] * route.heatmap_score
    )

    if forecast.wind_shift_warning:
        route.warnings.append(forecast.wind_shift_warning)

    return route


# ── Helper functions ─────────────────────────────────────────────


def workout_has_intervals(blocks: list[WorkoutBlock]) -> bool:
    return any(b.is_effort for b in blocks)


def _node_to_coord(graph: nx.MultiDiGraph, node: int) -> tuple[float, float, float]:
    d = graph.nodes[node]
    return (d.get("y", 0.0), d.get("x", 0.0), d.get("elevation", 0.0))


def _nodes_to_coords(
    graph: nx.MultiDiGraph, nodes: list[int]
) -> list[tuple[float, float, float]]:
    return [_node_to_coord(graph, n) for n in nodes]


def _append_path(
    graph: nx.MultiDiGraph,
    path_nodes: list[int],
    all_nodes: list[int],
    all_coords: list[tuple[float, float, float]],
) -> int:
    """Append path to the running node/coord lists, skipping the first node
    (which is the same as the last node already in the list).

    Returns the new current_node (last node of path).
    """
    if not path_nodes:
        return all_nodes[-1] if all_nodes else 0

    # Skip the first node — it's where we already are
    new_nodes = path_nodes[1:] if len(path_nodes) > 1 else []
    all_nodes.extend(new_nodes)
    all_coords.extend(_nodes_to_coords(graph, new_nodes))

    return path_nodes[-1]


def _find_path(
    graph: nx.MultiDiGraph,
    source: int,
    target: int,
    preferred_bearing: float | None = None,
    wind_weight: float = 0.0,
) -> tuple[list[int], float] | None:
    """Find a path from source to target.

    If preferred_bearing is given, uses custom edge weights that penalize
    deviation from the preferred direction. Falls back to shortest path.
    """
    if source == target:
        return [source], 0.0

    # Try bearing-weighted path first
    if preferred_bearing is not None and wind_weight > 0:
        result = _route_with_bearing_preference(
            graph, source, target, preferred_bearing, wind_weight
        )
        if result:
            return result

    # Fallback: shortest path by distance
    return _shortest_path_safe(graph, source, target)


def _shortest_path_safe(
    graph: nx.MultiDiGraph,
    source: int,
    target: int,
) -> tuple[list[int], float] | None:
    try:
        path = ox.shortest_path(graph, source, target, weight="length")
        if path is None:
            return None
        dist = sum(
            graph.edges[path[i], path[i + 1], 0].get("length", 0)
            for i in range(len(path) - 1)
        )
        return path, dist
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def _route_with_bearing_preference(
    graph: nx.MultiDiGraph,
    source: int,
    target: int,
    preferred_bearing: float,
    wind_weight: float,
) -> tuple[list[int], float] | None:
    for u, v, key, data in graph.edges(keys=True, data=True):
        length = data.get("length", 1.0)
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        edge_bearing = compute_edge_bearing(
            u_data.get("y", 0), u_data.get("x", 0),
            v_data.get("y", 0), v_data.get("x", 0),
        )
        penalty = bearing_penalty(edge_bearing, preferred_bearing)
        data["_wind_weight"] = length * (1.0 + wind_weight * penalty)

    try:
        path = ox.shortest_path(graph, source, target, weight="_wind_weight")
        if path is None:
            return None
        dist = sum(
            graph.edges[path[i], path[i + 1], 0].get("length", 0)
            for i in range(len(path) - 1)
        )
        return path, dist
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    finally:
        for u, v, key, data in graph.edges(keys=True, data=True):
            data.pop("_wind_weight", None)


def _find_far_node(
    graph: nx.MultiDiGraph,
    start_node: int,
    bearing: float,
    target_distance_m: float,
) -> int | None:
    """Find a node roughly in the given direction at the given distance."""
    start_data = graph.nodes[start_node]
    start_lat = start_data.get("y", 0)
    start_lon = start_data.get("x", 0)

    target_lat = start_lat + (target_distance_m / 111000) * math.cos(math.radians(bearing))
    target_lon = start_lon + (target_distance_m / (111000 * math.cos(math.radians(start_lat)))) * math.sin(math.radians(bearing))

    try:
        return ox.nearest_nodes(graph, target_lon, target_lat)
    except Exception:
        return None


def _compute_total_elevation(coords: list[tuple[float, float, float]]) -> float:
    gain = 0.0
    for i in range(1, len(coords)):
        diff = coords[i][2] - coords[i - 1][2]
        if diff > 0:
            gain += diff
    return gain


def _compute_wind_score(
    segments: list[RouteSegment],
    wind_direction: float,
) -> float:
    favorable_dist = 0.0
    total_dist = 0.0

    for seg in segments:
        if seg.block_type == "interval":
            continue

        total_dist += seg.distance_m
        if len(seg.coords) >= 2:
            seg_bearing = compute_edge_bearing(
                seg.coords[0][0], seg.coords[0][1],
                seg.coords[-1][0], seg.coords[-1][1],
            )
            penalty = bearing_penalty(seg_bearing, wind_direction)
            favorable_dist += seg.distance_m * (1 - penalty)

    return favorable_dist / total_dist if total_dist > 0 else 0.5


def _compute_climb_score(
    climbs: list[ClimbCandidate],
    blocks: list[WorkoutBlock],
) -> float:
    if not climbs:
        return 1.0 if not any(b.is_effort for b in blocks) else 0.0
    return sum(c.quality_score for c in climbs) / len(climbs)
