from dataclasses import dataclass


@dataclass
class WeatherSnapshot:
    """Weather data at a specific time and location."""

    timestamp: str
    lat: float
    lon: float
    wind_speed_kmh: float
    wind_direction_deg: float  # meteorological: direction wind comes FROM
    temperature_c: float
    cloudcover_percent: float
    precipitation_mm: float
    surface_pressure_hpa: float

    @property
    def wind_speed_ms(self) -> float:
        return self.wind_speed_kmh / 3.6

    @property
    def wind_direction_label(self) -> str:
        directions = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
        ]
        idx = round(self.wind_direction_deg / 22.5) % 16
        return directions[idx]


@dataclass
class WeatherForecast:
    """Hourly weather forecast over a time window."""

    snapshots: list[WeatherSnapshot]
    wind_shift_warning: str | None = None  # set if wind turns >45° during window

    @property
    def current(self) -> WeatherSnapshot:
        return self.snapshots[0]

    def at_hour(self, hour_offset: int) -> WeatherSnapshot:
        if hour_offset < len(self.snapshots):
            return self.snapshots[hour_offset]
        return self.snapshots[-1]
