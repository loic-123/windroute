"""
GPX exporter: generates Garmin/Wahoo-compatible GPX files.

Includes:
    - Track points with elevation
    - Waypoints for interval start/end markers
    - Garmin power target extensions
"""

from datetime import datetime

import gpxpy
import gpxpy.gpx

from app.models.route import Route


def export_gpx(route: Route, workout_name: str = "") -> str:
    """Export a Route to GPX XML string.

    Args:
        route: the Route to export
        workout_name: optional workout name for metadata

    Returns:
        GPX XML string
    """
    gpx = gpxpy.gpx.GPX()

    # Metadata
    gpx.name = workout_name or f"WindRoute {route.variant}"
    gpx.description = (
        f"Distance: {route.total_distance_km:.1f} km | "
        f"D+: {route.total_elevation_m:.0f} m | "
        f"Score: {route.overall_score:.2f}"
    )
    gpx.author_name = "WindRoute"
    gpx.time = datetime.now()

    # Track
    track = gpxpy.gpx.GPXTrack()
    track.name = gpx.name
    gpx.tracks.append(track)

    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    for lat, lon, ele in route.coords:
        point = gpxpy.gpx.GPXTrackPoint(
            latitude=lat,
            longitude=lon,
            elevation=ele,
        )
        segment.points.append(point)

    # Waypoints for interval markers
    for seg in route.segments:
        if seg.block_type == "interval" and seg.coords:
            # Start marker
            start = seg.coords[0]
            wp_start = gpxpy.gpx.GPXWaypoint(
                latitude=start[0],
                longitude=start[1],
                elevation=start[2],
                name=f"INT_{seg.block_index}_START",
                description=(
                    f"Interval {seg.block_index} start | "
                    f"Power: {seg.power_target:.0f}W | "
                    f"Duration: {seg.duration_s:.0f}s"
                ),
            )
            gpx.waypoints.append(wp_start)

            # End marker
            end = seg.coords[-1]
            wp_end = gpxpy.gpx.GPXWaypoint(
                latitude=end[0],
                longitude=end[1],
                elevation=end[2],
                name=f"INT_{seg.block_index}_END",
            )
            gpx.waypoints.append(wp_end)

        # Climb markers
        if seg.climb and seg.coords:
            start = seg.coords[0]
            wp_climb = gpxpy.gpx.GPXWaypoint(
                latitude=start[0],
                longitude=start[1],
                elevation=start[2],
                name=f"CLIMB_{seg.block_index}",
                description=(
                    f"Climb: {seg.climb.length_m:.0f}m | "
                    f"Grade: {seg.climb.avg_grade_percent:.1f}% | "
                    f"D+: {seg.climb.elevation_gain_m:.0f}m"
                ),
            )
            gpx.waypoints.append(wp_climb)

    return gpx.to_xml()


def export_summary_json(route: Route, workout_name: str = "") -> dict:
    """Generate the JSON summary for a route."""
    weather = None
    if hasattr(route, "_weather_snapshot"):
        weather = route._weather_snapshot

    climbs_data = []
    for i, climb in enumerate(route.climbs):
        climbs_data.append({
            "id": f"climb_{i + 1}",
            "length_km": round(climb.length_m / 1000, 2),
            "avg_grade_percent": round(climb.avg_grade_percent, 1),
            "elevation_gain_m": round(climb.elevation_gain_m, 0),
            "estimated_duration_s": round(climb.estimated_duration_s, 0),
            "quality_score": round(climb.quality_score, 3),
            "road_type": climb.road_type,
        })

    return {
        "workout_name": workout_name,
        "variant": route.variant,
        "generated_at": datetime.now().isoformat(),
        "total_distance_km": round(route.total_distance_km, 1),
        "total_elevation_m": round(route.total_elevation_m, 0),
        "estimated_duration_s": route.estimated_duration_s,
        "warmup_distance_km": round(route.warmup_distance_km, 1),
        "warmup_duration_initial_s": route.warmup_duration_initial_s,
        "warmup_duration_actual_s": route.warmup_duration_actual_s,
        "cooldown_distance_km": round(route.cooldown_distance_km, 1),
        "cooldown_duration_initial_s": route.cooldown_duration_initial_s,
        "cooldown_duration_actual_s": route.cooldown_duration_actual_s,
        "wind_score": round(route.wind_score, 3),
        "climb_score": round(route.climb_score, 3),
        "sunshine_score": round(route.sunshine_score, 3),
        "heatmap_score": round(route.heatmap_score, 3),
        "overall_score": round(route.overall_score, 3),
        "climbs": climbs_data,
        "warnings": route.warnings,
    }
