"""
Timing engine: places workout blocks sequentially onto a route graph.

Calculates cumulative distance and lat/lon positions for each block
transition point, respecting elastic duration rules for warmup/cooldown.
"""

import logging

from app.config import settings
from app.models.workout import BlockType, WorkoutBlock

logger = logging.getLogger(__name__)


def compute_elastic_max(initial_duration_s: int) -> int:
    """Compute maximum allowed duration after elastic stretching.

    Rules:
        - If initial < 3600s: max = initial × 1.40 (+40%)
        - If initial >= 3600s: max = initial × 1.20 (+20%)
    """
    if initial_duration_s < 3600:
        ratio = settings.warmup_elastic_ratio_short
    else:
        ratio = settings.warmup_elastic_ratio_long
    return int(initial_duration_s * (1 + ratio))


def compute_block_distances(
    blocks: list[WorkoutBlock],
    speeds_ms: list[float],
) -> list[dict]:
    """Compute cumulative distances and positions for each block.

    Args:
        blocks: flat list of workout blocks
        speeds_ms: estimated speed for each block in m/s

    Returns:
        List of dicts with keys:
            - block_index: int
            - block_type: str
            - start_distance_m: float
            - end_distance_m: float
            - duration_s: int
            - speed_ms: float
            - distance_m: float
    """
    if len(blocks) != len(speeds_ms):
        raise ValueError(
            f"blocks ({len(blocks)}) and speeds ({len(speeds_ms)}) must have same length"
        )

    result = []
    cumulative_m = 0.0

    for block, speed in zip(blocks, speeds_ms):
        distance = speed * block.duration_seconds
        result.append({
            "block_index": block.index,
            "block_type": block.block_type.value,
            "start_distance_m": cumulative_m,
            "end_distance_m": cumulative_m + distance,
            "duration_s": block.duration_seconds,
            "speed_ms": speed,
            "distance_m": distance,
        })
        cumulative_m += distance

    return result


def compute_warmup_reach_km(blocks: list[WorkoutBlock], speeds_ms: list[float]) -> float:
    """Compute the maximum distance reachable during warmup (with elasticity).

    This is used by climb_finder to know how far from home the first
    interval climb can be placed.
    """
    warmup_distance = 0.0
    warmup_duration = 0

    for block, speed in zip(blocks, speeds_ms):
        if block.block_type != BlockType.WARMUP:
            break
        warmup_duration += block.duration_seconds
        warmup_distance += speed * block.duration_seconds

    if warmup_duration == 0:
        # No explicit warmup block: use minimum warmup
        warmup_duration = settings.warmup_min_duration_s
        # Estimate warmup speed at 60% of first interval speed
        warmup_speed = speeds_ms[0] * 0.6 if speeds_ms else 7.0
        warmup_distance = warmup_speed * warmup_duration

    max_duration = compute_elastic_max(warmup_duration)
    elastic_extra = max_duration - warmup_duration

    # Average warmup speed for the elastic extension
    avg_speed = warmup_distance / warmup_duration if warmup_duration > 0 else 7.0
    max_distance = warmup_distance + avg_speed * elastic_extra

    return max_distance / 1000.0  # convert to km


def compute_cooldown_reach_km(
    blocks: list[WorkoutBlock], speeds_ms: list[float]
) -> float:
    """Compute the maximum distance available for cooldown/return."""
    cooldown_distance = 0.0
    cooldown_duration = 0

    for block, speed in zip(reversed(blocks), reversed(speeds_ms)):
        if block.block_type != BlockType.COOLDOWN:
            break
        cooldown_duration += block.duration_seconds
        cooldown_distance += speed * block.duration_seconds

    if cooldown_duration == 0:
        cooldown_duration = settings.cooldown_min_duration_s
        cooldown_speed = speeds_ms[-1] * 0.7 if speeds_ms else 7.0
        cooldown_distance = cooldown_speed * cooldown_duration

    max_duration = compute_elastic_max(cooldown_duration)
    elastic_extra = max_duration - cooldown_duration
    avg_speed = cooldown_distance / cooldown_duration if cooldown_duration > 0 else 7.0
    max_distance = cooldown_distance + avg_speed * elastic_extra

    return max_distance / 1000.0
