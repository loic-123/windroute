from datetime import datetime

from fastapi import APIRouter, Query

from app.api.schemas.weather import WeatherForecastResponse, WeatherSnapshotResponse
from app.clients.openmeteo_client import OpenMeteoClient

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("", response_model=WeatherForecastResponse)
async def get_weather(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    hours: int = Query(6, ge=1, le=24),
    target_date: str | None = Query(None, description="ISO datetime"),
):
    target = datetime.fromisoformat(target_date) if target_date else None

    client = OpenMeteoClient()
    try:
        forecast = await client.get_forecast(lat, lon, hours, target)
    finally:
        await client.close()

    snapshots = [
        WeatherSnapshotResponse(
            timestamp=s.timestamp,
            wind_speed_kmh=s.wind_speed_kmh,
            wind_direction_deg=s.wind_direction_deg,
            wind_direction_label=s.wind_direction_label,
            temperature_c=s.temperature_c,
            cloudcover_percent=s.cloudcover_percent,
            precipitation_mm=s.precipitation_mm,
            surface_pressure_hpa=s.surface_pressure_hpa,
        )
        for s in forecast.snapshots
    ]

    return WeatherForecastResponse(
        snapshots=snapshots,
        wind_shift_warning=forecast.wind_shift_warning,
    )
