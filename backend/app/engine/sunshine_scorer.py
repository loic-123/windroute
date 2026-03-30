"""
Sunshine scorer: evaluates how much sun exposure a route gets.

Score = proportion of ride time where cloudcover < 40%.
"""

from app.models.weather import WeatherForecast


def score_sunshine(
    forecast: WeatherForecast,
    segment_start_hours: list[float],
    segment_durations_s: list[float],
    cloud_threshold: float = 40.0,
) -> float:
    """Calculate sunshine score for a route.

    Args:
        forecast: weather forecast with hourly snapshots
        segment_start_hours: hour offset from ride start for each segment
        segment_durations_s: duration in seconds for each segment
        cloud_threshold: cloudcover % below which counts as sunny

    Returns:
        Score in [0, 1]. 1 = fully sunny, 0 = fully cloudy.
    """
    if not segment_start_hours or not forecast.snapshots:
        return 0.5

    total_time = 0.0
    sunny_time = 0.0

    for start_h, dur_s in zip(segment_start_hours, segment_durations_s):
        hour_idx = int(start_h)
        snap = forecast.at_hour(hour_idx)
        total_time += dur_s
        if snap.cloudcover_percent < cloud_threshold:
            sunny_time += dur_s

    if total_time <= 0:
        return 0.5

    return sunny_time / total_time
