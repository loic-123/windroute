"""
GeoJSON generator: produces map data for the frontend.

Only includes LineString segments (colored by block type) and
start/finish markers. No individual interval markers to avoid clutter.
"""

from app.models.route import Route

BLOCK_COLORS = {
    "warmup": "#22c55e",      # green
    "interval": "#ef4444",    # red
    "recovery": "#f97316",    # orange
    "cooldown": "#6b7280",    # gray
    "rest": "#a3a3a3",        # light gray
}


def route_to_geojson(route: Route) -> dict:
    """Convert a Route to a GeoJSON FeatureCollection.

    Includes:
        - LineString per segment (colored by block type)
        - Start marker (first coord)
        - Finish marker (last coord)
    """
    features = []

    for seg in route.segments:
        if not seg.coords or len(seg.coords) < 2:
            continue

        coordinates = [[lon, lat, ele] for lat, lon, ele in seg.coords]

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "block_index": seg.block_index,
                "block_type": seg.block_type,
                "color": BLOCK_COLORS.get(seg.block_type, "#6b7280"),
                "power_target": round(seg.power_target, 0),
                "distance_km": round(seg.distance_m / 1000, 2),
                "duration_min": round(seg.duration_s / 60, 1),
                "avg_speed_kmh": round(seg.avg_speed_ms * 3.6, 1),
                "avg_grade_percent": round(seg.avg_grade_percent, 1),
            },
        }

        if seg.climb:
            feature["properties"]["climb"] = {
                "length_m": round(seg.climb.length_m, 0),
                "avg_grade": round(seg.climb.avg_grade_percent, 1),
                "max_grade": round(seg.climb.max_grade_percent, 1),
                "elevation_gain_m": round(seg.climb.elevation_gain_m, 0),
            }

        features.append(feature)

    # Start marker
    if route.coords:
        start = route.coords[0]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [start[1], start[0], start[2]],
            },
            "properties": {
                "marker_type": "start",
                "label": "Depart",
            },
        })

        # Finish marker (same as start for a loop)
        end = route.coords[-1]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [end[1], end[0], end[2]],
            },
            "properties": {
                "marker_type": "finish",
                "label": "Arrivee",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "variant": route.variant,
            "total_distance_km": round(route.total_distance_km, 1),
            "total_elevation_m": round(route.total_elevation_m, 0),
            "overall_score": round(route.overall_score, 3),
        },
    }
