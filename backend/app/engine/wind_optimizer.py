"""
Wind optimizer: calculates preferred bearings for outbound/return segments.

Rules:
    - Outbound (warmup → start of intervals): prefer HEADWIND
      Target bearing = wind_direction + 180° ± tolerance
    - Return (end of intervals → home): prefer TAILWIND
      Target bearing = wind_direction ± tolerance
    - Interval segments: NO wind constraint (wind_bearing=None)
"""

import logging
import math

from app.config import settings

logger = logging.getLogger(__name__)


def preferred_outbound_bearing(wind_direction_deg: float) -> float:
    """Calculate preferred outbound bearing (ride INTO the wind).

    The rider leaves home facing the wind, so the route bearing
    should be in the direction the wind comes FROM.

    Args:
        wind_direction_deg: meteorological wind direction (where wind blows FROM)

    Returns:
        Preferred bearing in degrees (0-360)
    """
    # Wind comes FROM this direction → ride toward it
    bearing = wind_direction_deg % 360
    return bearing


def preferred_return_bearing(wind_direction_deg: float) -> float:
    """Calculate preferred return bearing (ride WITH the wind).

    The rider returns home with the wind at their back, so the route
    bearing should be opposite to where the wind comes FROM.

    Args:
        wind_direction_deg: meteorological wind direction (where wind blows FROM)

    Returns:
        Preferred bearing in degrees (0-360)
    """
    # Wind comes FROM wind_direction → tailwind means riding in the
    # opposite direction (wind pushes from behind)
    bearing = (wind_direction_deg + 180) % 360
    return bearing


def bearing_penalty(
    actual_bearing: float,
    preferred_bearing: float,
    tolerance_deg: float | None = None,
) -> float:
    """Calculate a penalty score for deviation from preferred bearing.

    Args:
        actual_bearing: actual route bearing in degrees
        preferred_bearing: preferred bearing in degrees
        tolerance_deg: initial tolerance (default from config)

    Returns:
        Penalty in [0, 1]. 0 = perfect alignment, 1 = worst case (opposite).
    """
    if tolerance_deg is None:
        tolerance_deg = settings.wind_bearing_tolerance_deg

    diff = abs(actual_bearing - preferred_bearing) % 360
    if diff > 180:
        diff = 360 - diff

    if diff <= tolerance_deg:
        return 0.0

    max_tol = settings.wind_bearing_max_tolerance_deg
    if diff >= 180:
        return 1.0

    # Linear ramp from 0 at tolerance to 1 at 180°
    return min((diff - tolerance_deg) / (180 - tolerance_deg), 1.0)


def expand_bearing_range(
    preferred_bearing: float,
    initial_tolerance: float | None = None,
) -> list[tuple[float, float]]:
    """Generate expanding bearing ranges for route search.

    Starts with ±initial_tolerance and widens by 15° steps up to ±max_tolerance.

    Returns:
        List of (min_bearing, max_bearing) ranges, expanding outward.
    """
    if initial_tolerance is None:
        initial_tolerance = settings.wind_bearing_tolerance_deg

    max_tolerance = settings.wind_bearing_max_tolerance_deg
    step = 15.0

    ranges = []
    tol = initial_tolerance
    while tol <= max_tolerance:
        min_b = (preferred_bearing - tol) % 360
        max_b = (preferred_bearing + tol) % 360
        ranges.append((min_b, max_b))
        tol += step

    return ranges


def is_bearing_in_range(
    bearing: float,
    preferred: float,
    tolerance: float,
) -> bool:
    """Check if a bearing falls within ±tolerance of the preferred bearing."""
    diff = abs(bearing - preferred) % 360
    if diff > 180:
        diff = 360 - diff
    return diff <= tolerance


def compute_edge_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute compass bearing between two lat/lon points.

    Returns bearing in degrees (0-360), where 0 = North, 90 = East.
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
        lat2_r
    ) * math.cos(dlon)

    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360
