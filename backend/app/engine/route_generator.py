"""
Route generator: builds complete cycling routes from workout + terrain + weather.

Generates 3 route variants:
    A: maximize wind optimization
    B: maximize climb quality
    C: balanced compromise (weighted by config)

Pipeline:
    1. Calculate search radius from estimated total distance
    2. Load OSMnx graph (with cache) and enrich elevations
    3. Detect climbs and match to interval blocks
    4. Build outbound path (warmup → climb start) with wind bearing
    5. Add climb segments (repeat or loop mode)
    6. Build return path (climb end → home) with tailwind bearing
    7. Score and rank variants
"""

import logging
import math
from dataclasses import dataclass

import networkx as nx
import osmnx as ox

from app.cache.osm_cache import enrich_elevations, load_or_fetch_graph
from app.config import settings
from app.engine.climb_finder import detect_climbs, select_climbs_for_workout
from app.engine.heatmap_scorer import HeatmapScorer
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
    """Generate 3 route variants for a workout.

    Returns:
        List of up to 3 Route objects (A, B, C), sorted by overall_score.
    """
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
    cooldown_reach_km = compute_cooldown_reach_km(blocks, speeds)

    # ── Step 2: Calculate search radius ──────────────────────────
    radius_m = min(
        total_distance_m / (2 * math.pi) * 1.2,
        params.max_radius_km * 1000,
    )
    radius_m = max(radius_m, 3000)  # minimum 3km radius

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
    climbs = []
    selected_climbs = []
    climb_mode_used = params.climb_mode

    if workout.has_intervals:
        climbs = detect_climbs(graph)
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
                cooldown_reach_km=cooldown_reach_km,
            )
            variants.append(route)
        except Exception as e:
            logger.error("Failed to generate variant %s: %s", variant_name, e)
            continue

    # Sort by overall score
    variants.sort(key=lambda r: r.overall_score, reverse=True)

    return variants


def _estimate_block_speeds(
    blocks: list[WorkoutBlock],
    athlete: AthleteProfile,
    weather,
) -> list[float]:
    """Estimate speed for each block on flat terrain with average wind."""
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
    """Get weight sets for the 3 variants."""
    return {
        "A": {  # Max wind optimization
            "wind": 0.60,
            "climb": 0.25,
            "sunshine": 0.10,
            "heatmap": 0.05,
        },
        "B": {  # Max climb quality
            "wind": 0.15,
            "climb": 0.60,
            "sunshine": 0.15,
            "heatmap": 0.10,
        },
        "C": custom_weights or {  # Balanced (config defaults)
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
    cooldown_reach_km: float,
) -> Route:
    """Build a single route variant."""
    weather = forecast.current
    route = Route(variant=variant)
    warnings = []

    all_nodes = []
    all_coords = []
    segments = []

    # ── Phase 1: Outbound (warmup) ───────────────────────────────
    warmup_blocks = [b for b in blocks if b.block_type == BlockType.WARMUP]
    warmup_duration = sum(b.duration_seconds for b in warmup_blocks) if warmup_blocks else settings.warmup_min_duration_s
    warmup_max_duration = compute_elastic_max(warmup_duration)

    if selected_climbs:
        target_node = selected_climbs[0].start_node

        # Try to route to climb start with wind bearing preference
        outbound_path = _route_with_bearing_preference(
            graph, start_node, target_node, outbound_bearing, weights["wind"]
        )
        if outbound_path is None:
            outbound_path = _shortest_path_safe(graph, start_node, target_node)

        if outbound_path:
            path_nodes, path_dist = outbound_path
            warmup_speed = speeds[0] if speeds else 7.0
            actual_duration = path_dist / warmup_speed

            if actual_duration > warmup_max_duration:
                warnings.append(
                    f"Montée optimale à {path_dist/1000:.1f} km, "
                    f"budget échauffement max = {warmup_reach_km:.1f} km — "
                    f"montée alternative peut être nécessaire"
                )

            route.warmup_duration_initial_s = warmup_duration
            route.warmup_duration_actual_s = int(actual_duration)
            route.warmup_distance_km = path_dist / 1000

            all_nodes.extend(path_nodes)
            seg_coords = _nodes_to_coords(graph, path_nodes)
            all_coords.extend(seg_coords)
            segments.append(RouteSegment(
                block_index=0,
                block_type="warmup",
                nodes=path_nodes,
                coords=seg_coords,
                distance_m=path_dist,
                duration_s=actual_duration,
                power_target=warmup_blocks[0].power_watts if warmup_blocks else 0,
                avg_speed_ms=warmup_speed,
            ))
    else:
        # No climbs: generate a simple loop
        outbound_path = _generate_outbound_loop(
            graph, start_node, outbound_bearing,
            warmup_reach_km * 1000, weights["wind"]
        )
        if outbound_path:
            path_nodes, path_dist = outbound_path
            all_nodes.extend(path_nodes)
            seg_coords = _nodes_to_coords(graph, path_nodes)
            all_coords.extend(seg_coords)

    # ── Phase 2: Climb segments (intervals) ──────────────────────
    if selected_climbs:
        interval_blocks = [b for b in blocks if b.is_effort]

        if climb_mode == "repeat" and selected_climbs:
            climb = selected_climbs[0]
            for i, block in enumerate(interval_blocks):
                # Ascent
                climb_path = _shortest_path_safe(graph, climb.start_node, climb.end_node)
                if climb_path:
                    c_nodes, c_dist = climb_path
                    c_speed = power_to_speed(
                        block.power_watts, climb.avg_grade_percent,
                        0.0, athlete.get_cda(), athlete.weight_kg,
                        athlete.bike_weight_kg, athlete.crr,
                        weather.temperature_c,
                    )
                    all_nodes.extend(c_nodes[1:])  # skip first (already added)
                    seg_coords = _nodes_to_coords(graph, c_nodes)
                    all_coords.extend(seg_coords[1:])
                    segments.append(RouteSegment(
                        block_index=block.index,
                        block_type="interval",
                        nodes=c_nodes,
                        coords=seg_coords,
                        distance_m=c_dist,
                        duration_s=c_dist / c_speed if c_speed > 0 else block.duration_seconds,
                        power_target=block.power_watts,
                        avg_speed_ms=c_speed,
                        avg_grade_percent=climb.avg_grade_percent,
                        climb=climb,
                    ))

                # Descent (recovery between repeats, except after last)
                if i < len(interval_blocks) - 1:
                    desc_path = _shortest_path_safe(graph, climb.end_node, climb.start_node)
                    if desc_path:
                        d_nodes, d_dist = desc_path
                        d_speed = power_to_speed(
                            athlete.ftp_watts * 0.5, -climb.avg_grade_percent,
                            0.0, athlete.get_cda("drops"), athlete.weight_kg,
                            athlete.bike_weight_kg, athlete.crr,
                            weather.temperature_c,
                        )
                        all_nodes.extend(d_nodes[1:])
                        seg_coords = _nodes_to_coords(graph, d_nodes)
                        all_coords.extend(seg_coords[1:])
                        segments.append(RouteSegment(
                            block_index=block.index,
                            block_type="recovery",
                            nodes=d_nodes,
                            coords=seg_coords,
                            distance_m=d_dist,
                            duration_s=d_dist / d_speed if d_speed > 0 else 180,
                            power_target=athlete.ftp_watts * 0.5,
                            avg_speed_ms=d_speed,
                            avg_grade_percent=-climb.avg_grade_percent,
                        ))

        elif climb_mode == "loop" and selected_climbs:
            current_node = selected_climbs[0].start_node
            for i, (block, climb) in enumerate(zip(interval_blocks, selected_climbs)):
                # Route to climb start if needed
                if i > 0:
                    transfer = _shortest_path_safe(graph, current_node, climb.start_node)
                    if transfer:
                        t_nodes, t_dist = transfer
                        all_nodes.extend(t_nodes[1:])
                        seg_coords = _nodes_to_coords(graph, t_nodes)
                        all_coords.extend(seg_coords[1:])

                # Climb
                climb_path = _shortest_path_safe(graph, climb.start_node, climb.end_node)
                if climb_path:
                    c_nodes, c_dist = climb_path
                    c_speed = power_to_speed(
                        block.power_watts, climb.avg_grade_percent,
                        0.0, athlete.get_cda(), athlete.weight_kg,
                        athlete.bike_weight_kg, athlete.crr,
                        weather.temperature_c,
                    )
                    all_nodes.extend(c_nodes[1:] if i > 0 or all_nodes else c_nodes)
                    seg_coords = _nodes_to_coords(graph, c_nodes)
                    all_coords.extend(seg_coords[1:] if all_coords else seg_coords)
                    segments.append(RouteSegment(
                        block_index=block.index,
                        block_type="interval",
                        nodes=c_nodes,
                        coords=seg_coords,
                        distance_m=c_dist,
                        duration_s=c_dist / c_speed if c_speed > 0 else block.duration_seconds,
                        power_target=block.power_watts,
                        avg_speed_ms=c_speed,
                        avg_grade_percent=climb.avg_grade_percent,
                        climb=climb,
                    ))
                    current_node = climb.end_node

    # ── Phase 3: Return (cooldown) ───────────────────────────────
    last_node = all_nodes[-1] if all_nodes else start_node
    if last_node != start_node:
        return_path = _route_with_bearing_preference(
            graph, last_node, start_node, return_bearing, weights["wind"]
        )
        if return_path is None:
            return_path = _shortest_path_safe(graph, last_node, start_node)

        if return_path:
            r_nodes, r_dist = return_path
            cooldown_blocks = [b for b in blocks if b.block_type == BlockType.COOLDOWN]
            cooldown_duration = sum(b.duration_seconds for b in cooldown_blocks) if cooldown_blocks else settings.cooldown_min_duration_s
            cooldown_speed = speeds[-1] if speeds else 7.0
            actual_cooldown = r_dist / cooldown_speed

            route.cooldown_duration_initial_s = cooldown_duration
            route.cooldown_duration_actual_s = int(actual_cooldown)
            route.cooldown_distance_km = r_dist / 1000

            all_nodes.extend(r_nodes[1:])
            seg_coords = _nodes_to_coords(graph, r_nodes)
            all_coords.extend(seg_coords[1:])
            segments.append(RouteSegment(
                block_index=len(blocks) - 1,
                block_type="cooldown",
                nodes=r_nodes,
                coords=seg_coords,
                distance_m=r_dist,
                duration_s=actual_cooldown,
                power_target=cooldown_blocks[0].power_watts if cooldown_blocks else 0,
                avg_speed_ms=cooldown_speed,
            ))

    # ── Phase 4: Compute scores ──────────────────────────────────
    route.nodes = all_nodes
    route.coords = all_coords
    route.segments = segments
    route.climbs = selected_climbs
    route.warnings = warnings

    # Distance and elevation
    route.total_distance_km = sum(s.distance_m for s in segments) / 1000
    route.total_elevation_m = _compute_total_elevation(all_coords)
    route.estimated_duration_s = int(sum(s.duration_s for s in segments))

    # Wind score: % of non-interval time with favorable wind
    route.wind_score = _compute_wind_score(
        graph, segments, forecast.current.wind_direction_deg
    )

    # Climb score: quality of matched climbs
    route.climb_score = _compute_climb_score(selected_climbs, blocks)

    # Sunshine score
    seg_hours = [sum(s.duration_s for s in segments[:i]) / 3600 for i in range(len(segments))]
    seg_durations = [s.duration_s for s in segments]
    route.sunshine_score = score_sunshine(forecast, seg_hours, seg_durations)

    # Overall score
    route.overall_score = (
        weights["wind"] * route.wind_score
        + weights["climb"] * route.climb_score
        + weights["sunshine"] * route.sunshine_score
        + weights["heatmap"] * route.heatmap_score
    )

    # Add wind shift warning if applicable
    if forecast.wind_shift_warning:
        route.warnings.append(forecast.wind_shift_warning)

    return route


# ── Helper functions ─────────────────────────────────────────────


def _nodes_to_coords(
    graph: nx.MultiDiGraph, nodes: list[int]
) -> list[tuple[float, float, float]]:
    """Convert node IDs to (lat, lon, elevation) tuples."""
    coords = []
    for node in nodes:
        data = graph.nodes[node]
        lat = data.get("y", 0.0)
        lon = data.get("x", 0.0)
        ele = data.get("elevation", 0.0)
        coords.append((lat, lon, ele))
    return coords


def _shortest_path_safe(
    graph: nx.MultiDiGraph,
    source: int,
    target: int,
) -> tuple[list[int], float] | None:
    """Find shortest path, returning None on failure."""
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
    """Route with custom edge weights favoring the preferred bearing.

    Weight = length × (1 + wind_weight × bearing_penalty)
    """
    # Add temporary weight attribute
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
        # Clean up temporary attribute
        for u, v, key, data in graph.edges(keys=True, data=True):
            data.pop("_wind_weight", None)


def _generate_outbound_loop(
    graph: nx.MultiDiGraph,
    start_node: int,
    bearing: float,
    target_distance_m: float,
    wind_weight: float,
) -> tuple[list[int], float] | None:
    """Generate a simple outbound path in the preferred direction.

    Walks the graph in the preferred bearing direction for half
    the target distance, then returns to start.
    """
    # Find a node roughly in the right direction and distance
    half_dist = target_distance_m / 2
    start_data = graph.nodes[start_node]
    start_lat = start_data.get("y", 0)
    start_lon = start_data.get("x", 0)

    # Target point in the preferred direction
    target_lat = start_lat + (half_dist / 111000) * math.cos(math.radians(bearing))
    target_lon = start_lon + (half_dist / (111000 * math.cos(math.radians(start_lat)))) * math.sin(math.radians(bearing))

    try:
        far_node = ox.nearest_nodes(graph, target_lon, target_lat)
    except Exception:
        return None

    # Route out and back
    outbound = _route_with_bearing_preference(
        graph, start_node, far_node, bearing, wind_weight
    )
    if outbound is None:
        outbound = _shortest_path_safe(graph, start_node, far_node)
    if outbound is None:
        return None

    inbound = _shortest_path_safe(graph, far_node, start_node)
    if inbound is None:
        return None

    combined_nodes = outbound[0] + inbound[0][1:]
    combined_dist = outbound[1] + inbound[1]
    return combined_nodes, combined_dist


def _compute_total_elevation(coords: list[tuple[float, float, float]]) -> float:
    """Compute total positive elevation gain."""
    gain = 0.0
    for i in range(1, len(coords)):
        diff = coords[i][2] - coords[i - 1][2]
        if diff > 0:
            gain += diff
    return gain


def _compute_wind_score(
    graph: nx.MultiDiGraph,
    segments: list[RouteSegment],
    wind_direction: float,
) -> float:
    """Compute wind score: % of non-interval distance with favorable wind."""
    favorable_dist = 0.0
    total_dist = 0.0

    for seg in segments:
        if seg.block_type == "interval":
            continue  # wind ignored during intervals

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
    """Compute climb score based on quality of matched climbs."""
    if not climbs:
        interval_blocks = [b for b in blocks if b.is_effort]
        return 1.0 if not interval_blocks else 0.0

    return sum(c.quality_score for c in climbs) / len(climbs)
