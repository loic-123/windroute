"""
Route generator: builds clean out-and-back cycling routes.

Strategy:
    1. Calculate total ride distance from workout blocks + speeds
    2. Find a turnaround point at half-distance in the headwind direction
    3. Route: home → turnaround (headwind) → home (tailwind)
    4. Map workout blocks sequentially onto the route by distance
    5. Generate 3 variants with slightly different turnaround targets

The route is always a clean out-and-back. No spaghetti.
"""

import logging
import math
from dataclasses import dataclass

import networkx as nx
import osmnx as ox

from app.cache.osm_cache import enrich_elevations, load_or_fetch_graph
from app.config import settings
from app.engine.physics import estimate_speed_flat, power_to_speed
from app.engine.sunshine_scorer import score_sunshine
from app.engine.timing import compute_block_distances
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
    """Generate up to 3 clean out-and-back route variants."""
    workout = params.workout
    athlete = params.athlete
    forecast = params.forecast
    weather = forecast.current

    # ── Step 1: Estimate speeds and total distance ───────────────
    blocks = workout.blocks
    speeds = _estimate_block_speeds(blocks, athlete, weather)
    block_dists = compute_block_distances(blocks, speeds)
    total_distance_m = sum(bd["distance_m"] for bd in block_dists)
    half_distance_m = total_distance_m / 2

    logger.info(
        "Total estimated distance: %.1f km (half: %.1f km)",
        total_distance_m / 1000,
        half_distance_m / 1000,
    )

    # ── Step 2: Load graph ───────────────────────────────────────
    radius_m = min(half_distance_m * 1.1, params.max_radius_km * 1000)
    radius_m = max(radius_m, 3000)

    logger.info("Loading OSM graph with radius %.1f km", radius_m / 1000)

    graph = load_or_fetch_graph(
        params.lat, params.lon, radius_m, network_type="bike"
    )

    logger.info("Graph loaded: %d nodes, %d edges", len(graph.nodes), len(graph.edges))

    # Enrich with SRTM elevation data (local files, instant)
    graph = enrich_elevations(graph)

    start_node = ox.nearest_nodes(graph, params.lon, params.lat)

    # ── Step 3: Wind bearings ────────────────────────────────────
    wind_dir = weather.wind_direction_deg
    outbound_bearing = preferred_outbound_bearing(wind_dir)
    return_bearing = preferred_return_bearing(wind_dir)

    # ── Step 4: Generate 3 variants with different targets ───────
    # A: strict headwind bearing
    # B: 30° clockwise from headwind
    # C: 30° counter-clockwise from headwind
    variant_bearings = {
        "A": outbound_bearing,
        "B": (outbound_bearing + 30) % 360,
        "C": (outbound_bearing - 30) % 360,
    }

    variants = []
    for variant_name, bearing in variant_bearings.items():
        try:
            route = _build_out_and_back(
                graph=graph,
                start_node=start_node,
                half_distance_m=half_distance_m,
                outbound_bearing=bearing,
                return_bearing=(bearing + 180) % 360,
                blocks=blocks,
                speeds=speeds,
                block_dists=block_dists,
                athlete=athlete,
                forecast=forecast,
                variant=variant_name,
                wind_dir=wind_dir,
            )
            variants.append(route)
        except Exception as e:
            logger.error("Failed to generate variant %s: %s", variant_name, e)

    variants.sort(key=lambda r: r.overall_score, reverse=True)
    return variants


def _build_out_and_back(
    graph: nx.MultiDiGraph,
    start_node: int,
    half_distance_m: float,
    outbound_bearing: float,
    return_bearing: float,
    blocks: list[WorkoutBlock],
    speeds: list[float],
    block_dists: list[dict],
    athlete: AthleteProfile,
    forecast: WeatherForecast,
    variant: str,
    wind_dir: float,
) -> Route:
    """Build a clean out-and-back route.

    1. Find turnaround node at ~half_distance in outbound_bearing direction
    2. Route home → turnaround with bearing-weighted shortest path
    3. Route turnaround → home (different path if possible)
    4. Map blocks onto the combined path by cumulative distance
    """

    # ── Find turnaround point ────────────────────────────────────
    turnaround_node = _find_turnaround(
        graph, start_node, outbound_bearing, half_distance_m
    )

    if turnaround_node is None or turnaround_node == start_node:
        raise ValueError("Cannot find turnaround point")

    # ── Build outbound path (headwind) ───────────────────────────
    _set_bearing_weights(graph, outbound_bearing, wind_weight=0.5)
    outbound_path = _shortest_path(graph, start_node, turnaround_node, "_bw")
    _clear_weights(graph)

    if outbound_path is None:
        raise ValueError("No outbound path found")

    out_nodes, out_dist = outbound_path

    # ── Build return path (tailwind) ─────────────────────────────
    # Try to find a DIFFERENT return path by penalizing outbound edges
    _set_bearing_weights(graph, return_bearing, wind_weight=0.5)
    _penalize_used_edges(graph, out_nodes, penalty_factor=3.0)
    return_path = _shortest_path(graph, turnaround_node, start_node, "_bw")
    _clear_weights(graph)

    if return_path is None:
        # Fallback: same path reversed
        return_path = (list(reversed(out_nodes)), out_dist)

    ret_nodes, ret_dist = return_path

    # ── Combine into one continuous path ─────────────────────────
    all_nodes = list(out_nodes) + list(ret_nodes[1:])  # skip duplicate turnaround
    all_coords = _nodes_to_coords(graph, all_nodes)

    # Compute cumulative distances along the path
    edge_dists = _compute_edge_distances(graph, all_nodes)
    total_route_dist = sum(edge_dists)

    # ── Map blocks onto the path by distance ─────────────────────
    segments = _map_blocks_to_path(
        blocks, speeds, block_dists, all_nodes, all_coords,
        edge_dists, total_route_dist, graph
    )

    # ── Build Route object ───────────────────────────────────────
    route = Route(variant=variant)
    route.nodes = all_nodes
    route.coords = all_coords
    route.segments = segments
    route.total_distance_km = total_route_dist / 1000
    route.total_elevation_m = _compute_total_elevation(all_coords)
    route.estimated_duration_s = int(sum(s.duration_s for s in segments))
    route.warmup_distance_km = out_dist / 1000
    route.cooldown_distance_km = ret_dist / 1000

    # Scores
    route.wind_score = _compute_wind_score(
        all_coords, out_dist, total_route_dist, wind_dir, outbound_bearing
    )
    route.climb_score = 0.5  # neutral for out-and-back
    seg_hours = [sum(s.duration_s for s in segments[:i]) / 3600 for i in range(len(segments))]
    seg_durations = [s.duration_s for s in segments]
    route.sunshine_score = score_sunshine(forecast, seg_hours, seg_durations)
    route.heatmap_score = 0.5

    route.overall_score = (
        0.35 * route.wind_score
        + 0.25 * route.climb_score
        + 0.25 * route.sunshine_score
        + 0.15 * route.heatmap_score
    )

    if forecast.wind_shift_warning:
        route.warnings.append(forecast.wind_shift_warning)

    return route


# ── Path finding helpers ─────────────────────────────────────────


def _find_turnaround(
    graph: nx.MultiDiGraph,
    start_node: int,
    bearing: float,
    target_distance_m: float,
) -> int | None:
    """Find a turnaround node at ~target_distance in the given bearing.

    Strategy: compute a target lat/lon, find nearest graph node,
    then verify a path exists. If too far or no path, try closer.
    """
    start_data = graph.nodes[start_node]
    start_lat = start_data["y"]
    start_lon = start_data["x"]

    # Try distances from 100% down to 40% of target
    for fraction in [1.0, 0.85, 0.7, 0.55, 0.4]:
        dist = target_distance_m * fraction
        target_lat = start_lat + (dist / 111000) * math.cos(math.radians(bearing))
        target_lon = start_lon + (dist / (111000 * math.cos(math.radians(start_lat)))) * math.sin(math.radians(bearing))

        try:
            node = ox.nearest_nodes(graph, target_lon, target_lat)
        except Exception:
            continue

        if node == start_node:
            continue

        # Verify path exists
        path = _shortest_path(graph, start_node, node, "length")
        if path is not None:
            actual_dist = path[1]
            logger.info(
                "Turnaround found at %.1f km (target was %.1f km, fraction=%.0f%%)",
                actual_dist / 1000,
                target_distance_m / 1000,
                fraction * 100,
            )
            return node

    return None


def _set_bearing_weights(
    graph: nx.MultiDiGraph,
    preferred_bearing: float,
    wind_weight: float,
) -> None:
    """Set custom edge weights that penalize deviation from preferred bearing."""
    for u, v, key, data in graph.edges(keys=True, data=True):
        length = data.get("length", 1.0)
        edge_bearing = compute_edge_bearing(
            graph.nodes[u].get("y", 0), graph.nodes[u].get("x", 0),
            graph.nodes[v].get("y", 0), graph.nodes[v].get("x", 0),
        )
        penalty = bearing_penalty(edge_bearing, preferred_bearing)
        data["_bw"] = length * (1.0 + wind_weight * penalty)


def _penalize_used_edges(
    graph: nx.MultiDiGraph,
    used_nodes: list[int],
    penalty_factor: float = 3.0,
) -> None:
    """Make edges already used more expensive to encourage a different return."""
    used_set = set(zip(used_nodes[:-1], used_nodes[1:]))
    for u, v, key, data in graph.edges(keys=True, data=True):
        if (u, v) in used_set or (v, u) in used_set:
            data["_bw"] = data.get("_bw", data.get("length", 1.0)) * penalty_factor


def _clear_weights(graph: nx.MultiDiGraph) -> None:
    for u, v, key, data in graph.edges(keys=True, data=True):
        data.pop("_bw", None)


def _shortest_path(
    graph: nx.MultiDiGraph,
    source: int,
    target: int,
    weight: str = "length",
) -> tuple[list[int], float] | None:
    """Find shortest path, return (nodes, distance_m) or None."""
    try:
        path = ox.shortest_path(graph, source, target, weight=weight)
        if path is None:
            return None
        dist = sum(
            graph.edges[path[i], path[i + 1], 0].get("length", 0)
            for i in range(len(path) - 1)
        )
        return path, dist
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


# ── Block mapping ────────────────────────────────────────────────


def _map_blocks_to_path(
    blocks: list[WorkoutBlock],
    speeds: list[float],
    block_dists: list[dict],
    all_nodes: list[int],
    all_coords: list[tuple[float, float, float]],
    edge_dists: list[float],
    total_route_dist: float,
    graph: nx.MultiDiGraph,
) -> list[RouteSegment]:
    """Map workout blocks sequentially onto the route path.

    Each block occupies a stretch of the route proportional to its
    estimated distance. The coords/nodes are sliced accordingly.
    """
    # Build cumulative distance array for each node
    cum_dist = [0.0]
    for d in edge_dists:
        cum_dist.append(cum_dist[-1] + d)

    total_block_dist = sum(bd["distance_m"] for bd in block_dists)
    if total_block_dist <= 0:
        total_block_dist = total_route_dist

    # Scale factor: route distance / planned distance
    scale = total_route_dist / total_block_dist if total_block_dist > 0 else 1.0

    segments = []
    route_cursor = 0.0  # where we are along the route (meters)

    for block, speed, bd in zip(blocks, speeds, block_dists):
        block_dist_on_route = bd["distance_m"] * scale
        seg_start = route_cursor
        seg_end = min(route_cursor + block_dist_on_route, total_route_dist)

        # Find node indices for this segment
        start_idx = _dist_to_node_index(cum_dist, seg_start)
        end_idx = _dist_to_node_index(cum_dist, seg_end)
        end_idx = max(end_idx, start_idx + 1)  # at least 2 nodes

        seg_nodes = all_nodes[start_idx : end_idx + 1]
        seg_coords = all_coords[start_idx : end_idx + 1]
        seg_distance = seg_end - seg_start

        segments.append(RouteSegment(
            block_index=block.index,
            block_type=block.block_type.value,
            nodes=seg_nodes,
            coords=seg_coords,
            distance_m=seg_distance,
            duration_s=seg_distance / speed if speed > 0 else block.duration_seconds,
            power_target=block.power_watts,
            avg_speed_ms=speed,
        ))

        route_cursor = seg_end

    return segments


def _dist_to_node_index(cum_dist: list[float], target: float) -> int:
    """Find the node index closest to a cumulative distance."""
    for i, d in enumerate(cum_dist):
        if d >= target:
            return i
    return len(cum_dist) - 1


# ── Geometry helpers ─────────────────────────────────────────────


def _nodes_to_coords(
    graph: nx.MultiDiGraph, nodes: list[int]
) -> list[tuple[float, float, float]]:
    return [
        (
            graph.nodes[n].get("y", 0.0),
            graph.nodes[n].get("x", 0.0),
            graph.nodes[n].get("elevation", 0.0),
        )
        for n in nodes
    ]


def _compute_edge_distances(
    graph: nx.MultiDiGraph, nodes: list[int]
) -> list[float]:
    """Compute actual edge lengths along a path."""
    dists = []
    for i in range(len(nodes) - 1):
        try:
            length = graph.edges[nodes[i], nodes[i + 1], 0].get("length", 0)
        except KeyError:
            # Edge not found, estimate from coords
            c1 = graph.nodes[nodes[i]]
            c2 = graph.nodes[nodes[i + 1]]
            dlat = (c2["y"] - c1["y"]) * 111000
            dlon = (c2["x"] - c1["x"]) * 111000 * math.cos(math.radians(c1["y"]))
            length = math.sqrt(dlat ** 2 + dlon ** 2)
        dists.append(length)
    return dists


def _compute_total_elevation(coords: list[tuple[float, float, float]]) -> float:
    gain = 0.0
    for i in range(1, len(coords)):
        diff = coords[i][2] - coords[i - 1][2]
        if diff > 0:
            gain += diff
    return gain


def _compute_wind_score(
    coords: list[tuple[float, float, float]],
    outbound_dist: float,
    total_dist: float,
    wind_dir: float,
    outbound_bearing: float,
) -> float:
    """Simple wind score: how well aligned is the route with wind?"""
    if len(coords) < 2 or total_dist <= 0:
        return 0.5

    # Outbound bearing vs headwind
    out_penalty = bearing_penalty(outbound_bearing, wind_dir)
    # Return bearing vs tailwind direction
    ret_bearing = (outbound_bearing + 180) % 360
    ret_penalty = bearing_penalty(ret_bearing, (wind_dir + 180) % 360)

    # Weight by distance proportion
    out_frac = outbound_dist / total_dist
    ret_frac = 1.0 - out_frac

    return 1.0 - (out_penalty * out_frac + ret_penalty * ret_frac)


def _estimate_block_speeds(
    blocks: list[WorkoutBlock],
    athlete: AthleteProfile,
    weather,
) -> list[float]:
    return [
        estimate_speed_flat(
            power_w=b.power_watts,
            cda=athlete.get_cda(),
            weight_kg=athlete.weight_kg,
            bike_weight_kg=athlete.bike_weight_kg,
            crr=athlete.crr,
            temp_c=weather.temperature_c,
        )
        for b in blocks
    ]
