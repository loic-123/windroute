from pydantic import BaseModel


class WeatherSnapshotResponse(BaseModel):
    timestamp: str
    wind_speed_kmh: float
    wind_direction_deg: float
    wind_direction_label: str
    temperature_c: float
    cloudcover_percent: float
    precipitation_mm: float
    surface_pressure_hpa: float


class WeatherForecastResponse(BaseModel):
    snapshots: list[WeatherSnapshotResponse]
    wind_shift_warning: str | None = None
