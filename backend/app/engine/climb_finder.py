"""
Climb finder: detects and selects climbs from OSM graph for interval blocks.

Pipeline:
    1. Enrich graph nodes with elevation data
    2. Detect continuous climb segments (grade > threshold)
    3. Match climbs to interval blocks by estimated duration
    4. Score climbs by regularity, road type, and heatmap popularity
    5. Select best climb(s) based on mode (auto/repeat/loop)
"""

import logging
import math

import networkx as nx
import numpy as np

from app.config import settings
from app.engine.physics import power_to_speed
from app.models.athlete import AthleteProfile
from app.models.route import ClimbCandidate
from app.models.workout import WorkoutBlock

logger = logging.getLogger(__name__)

# Road type quality scores
ROAD_TYPE_SCORES = {
    "cycleway": 1.0,
    "secondary": 0.85,
    "tertiary": 0.80,
    "residential": 0.75,
    "unclassified": 0.70,
    "primary": 0.60,
    "service": 0.50,
    "trunk": 0.30,
    "motorway": 0.0,
}


def detect_climbs(
    graph: nx.MultiDiGraph,
    min_grade: float | None = None,
    min_length_m: float = 200.0,
) -> list[ClimbCandidate]:
    """Detect continuous climb segments from the OSM graph.

    Merges consecutive edges with grade > min_grade into climb segments.

    Args:
        graph: OSMnx graph with elevation-enriched nodes
        min_grade: minimum average grade (default from config)
        min_length_m: minimum climb length in meters

    Returns:
        List of ClimbCandidate objects
    """
    if min_grade is None:
        min_grade = settings.min_climb_grade_percent

    climbs = []

    # For each node, try to build uphill paths
    visited_edges = set()

    for node in graph.nodes:
        if not _node_has_elevation(graph, node):
            continue

        # Try extending a climb from this node
        climb_edges = _extend_climb_from(graph, node, min_grade, visited_edges)
        if not climb_edges:
            continue

        # Mark edges as visited
        for e in climb_edges:
            visited_edges.add(e)

        # Build ClimbCandidate from the chain of edges
        candidate = _build_climb_candidate(graph, climb_edges)
        if candidate and candidate.length_m >= min_length_m:
            climbs.append(candidate)

    logger.info("Detected %d climb candidates (grade >= %.1f%%)", len(climbs), min_grade)
    return climbs


def _node_has_elevation(graph: nx.MultiDiGraph, node: int) -> bool:
    return "elevation" in graph.nodes[node]


def _extend_climb_from(
    graph: nx.MultiDiGraph,
    start_node: int,
    min_grade: float,
    visited: set,
) -> list[tuple[int, int, int]]:
    """Extend a climb greedily from a start node following uphill edges."""
    chain = []
    current = start_node

    while True:
        best_edge = None
        best_grade = min_grade

        for _, neighbor, key, data in graph.out_edges(current, keys=True, data=True):
            edge_id = (current, neighbor, key)
            if edge_id in visited:
                continue
            if not _node_has_elevation(graph, neighbor):
                continue

            ele_start = graph.nodes[current]["elevation"]
            ele_end = graph.nodes[neighbor]["elevation"]
            length = data.get("length", 0)
            if length <= 0:
                continue

            grade = (ele_end - ele_start) / length * 100

            if grade >= min_grade and grade > best_grade * 0.5:
                best_edge = edge_id
                best_grade = grade

        if best_edge is None:
            break

        chain.append(best_edge)
        current = best_edge[1]  # move to neighbor

        # Safety: prevent infinite loops
        if len(chain) > 500:
            break

    return chain


def _build_climb_candidate(
    graph: nx.MultiDiGraph,
    edges: list[tuple[int, int, int]],
) -> ClimbCandidate | None:
    """Build a ClimbCandidate from a chain of edges."""
    if not edges:
        return None

    total_length = 0.0
    total_gain = 0.0
    grades = []
    max_grade = 0.0

    start_node = edges[0][0]
    end_node = edges[-1][1]

    for u, v, key in edges:
        data = graph.edges[u, v, key]
        length = data.get("length", 0)
        ele_u = graph.nodes[u].get("elevation", 0)
        ele_v = graph.nodes[v].get("elevation", 0)
        gain = ele_v - ele_u

        if length > 0:
            grade = gain / length * 100
            grades.append(grade)
            max_grade = max(max_grade, grade)

        total_length += length
        total_gain += max(gain, 0)

    if total_length <= 0:
        return None

    avg_grade = total_gain / total_length * 100
    grade_stddev = float(np.std(grades)) if grades else 0.0

    # Get road type from first edge
    first_data = graph.edges[edges[0][0], edges[0][1], edges[0][2]]
    road_type = first_data.get("highway", "unclassified")
    if isinstance(road_type, list):
        road_type = road_type[0]

    start_data = graph.nodes[start_node]
    end_data = graph.nodes[end_node]

    return ClimbCandidate(
        start_node=start_node,
        end_node=end_node,
        length_m=total_length,
        avg_grade_percent=avg_grade,
        max_grade_percent=max_grade,
        elevation_gain_m=total_gain,
        grade_stddev=grade_stddev,
        road_type=road_type,
        start_lat=start_data.get("y", 0),
        start_lon=start_data.get("x", 0),
        end_lat=end_data.get("y", 0),
        end_lon=end_data.get("x", 0),
    )


def match_climbs_to_intervals(
    climbs: list[ClimbCandidate],
    interval_blocks: list[WorkoutBlock],
    athlete: AthleteProfile,
    wind_speed_ms: float = 0.0,
    temp_c: float = 15.0,
) -> list[ClimbCandidate]:
    """Match and score climbs against interval blocks.

    Rules:
        - Climb is acceptable if estimated_duration >= block_duration × 0.80
        - Climb is preferred if estimated_duration >= block_duration × 1.00
        - NO upper limit: a climb 3× the duration is preferred over one slightly short
    """
    if not interval_blocks or not climbs:
        return []

    # Use the first interval block as reference for matching
    ref_block = interval_blocks[0]

    for climb in climbs:
        # Estimate speed on this climb
        speed = power_to_speed(
            power_w=ref_block.power_watts,
            grade_percent=climb.avg_grade_percent,
            wind_component_ms=0.0,  # ignore wind on climbs per rules
            cda=athlete.get_cda(),
            weight_kg=athlete.weight_kg,
            bike_weight_kg=athlete.bike_weight_kg,
            crr=athlete.crr,
            temp_c=temp_c,
        )

        climb.estimated_duration_s = climb.length_m / speed if speed > 0 else 0

        # Score the climb
        climb.quality_score = _score_climb(climb, ref_block)

    # Filter acceptable climbs
    min_duration = ref_block.duration_seconds * settings.climb_min_duration_ratio
    acceptable = [c for c in climbs if c.estimated_duration_s >= min_duration]

    if not acceptable:
        logger.warning(
            "No climb meets minimum duration (%.0fs). "
            "Best available: %.0fs (need >= %.0fs).",
            min_duration,
            max((c.estimated_duration_s for c in climbs), default=0),
            min_duration,
        )
        # Return the best available even if too short
        acceptable = sorted(climbs, key=lambda c: c.estimated_duration_s, reverse=True)

    # Sort by quality score (highest first)
    acceptable.sort(key=lambda c: c.quality_score, reverse=True)

    return acceptable


def _score_climb(climb: ClimbCandidate, block: WorkoutBlock) -> float:
    """Score a climb on regularity, road type, and duration match.

    Higher score = better climb.
    """
    # Weight factors
    w_regularity = 0.40
    w_road = 0.30
    w_duration = 0.20
    w_heatmap = 0.10

    # Regularity: lower stddev is better
    max_stddev = 5.0  # assume max reasonable stddev
    regularity = max(0, 1 - climb.grade_stddev / max_stddev) if max_stddev > 0 else 1.0

    # Road type score
    road_score = ROAD_TYPE_SCORES.get(climb.road_type, 0.60)

    # Duration match: prefer climbs >= target duration
    # Longer is always better than shorter (fundamental rule)
    target = block.duration_seconds
    if target > 0:
        ratio = climb.estimated_duration_s / target
        if ratio >= 1.0:
            duration_score = 1.0  # no penalty for being too long
        else:
            duration_score = max(0, ratio / 1.0)  # linear penalty if short
    else:
        duration_score = 0.5

    # Heatmap (set externally, default 0.5)
    heatmap = climb.heatmap_score

    return (
        w_regularity * regularity
        + w_road * road_score
        + w_duration * duration_score
        + w_heatmap * heatmap
    )


def select_climbs_for_workout(
    climbs: list[ClimbCandidate],
    interval_blocks: list[WorkoutBlock],
    athlete: AthleteProfile,
    climb_mode: str | None = None,
    wind_speed_ms: float = 0.0,
    temp_c: float = 15.0,
) -> tuple[list[ClimbCandidate], str]:
    """Select climb(s) for the workout based on mode.

    Args:
        climbs: ranked climb candidates
        interval_blocks: interval workout blocks
        athlete: athlete profile
        climb_mode: "auto", "repeat", or "loop" (default from config)

    Returns:
        Tuple of (selected_climbs, mode_used)
    """
    if climb_mode is None:
        climb_mode = settings.climb_mode

    n_intervals = len(interval_blocks)
    scored = match_climbs_to_intervals(
        climbs, interval_blocks, athlete, wind_speed_ms, temp_c
    )

    if not scored:
        return [], climb_mode

    best = scored[0]

    if climb_mode == "auto":
        # Auto: repeat if best climb >= 2km and N >= 3, else loop
        if (
            best.length_m >= settings.repeat_mode_min_climb_km * 1000
            and n_intervals >= settings.repeat_mode_min_intervals
        ):
            climb_mode = "repeat"
        else:
            climb_mode = "loop"

    if climb_mode == "repeat":
        # Single best climb, rider goes up/down N times
        return [best], "repeat"
    else:
        # Loop: find N distinct climbs
        selected = []
        used_nodes = set()
        for climb in scored:
            if climb.start_node not in used_nodes and climb.end_node not in used_nodes:
                selected.append(climb)
                used_nodes.add(climb.start_node)
                used_nodes.add(climb.end_node)
                if len(selected) >= n_intervals:
                    break

        if len(selected) < n_intervals:
            logger.warning(
                "Only found %d distinct climbs for %d intervals. "
                "Switching to repeat mode with best climb.",
                len(selected),
                n_intervals,
            )
            return [best], "repeat"

        return selected, "loop"
