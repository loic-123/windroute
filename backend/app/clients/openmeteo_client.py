"""
Client for the Open-Meteo weather API (free, no API key required).

Retrieves hourly weather data including wind, temperature, cloud cover,
precipitation, and surface pressure.
"""

import logging
from datetime import datetime

import httpx

from app.models.weather import WeatherForecast, WeatherSnapshot

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoClient:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        await self._client.aclose()

    async def get_forecast(
        self,
        lat: float,
        lon: float,
        hours: int = 6,
        target_date: datetime | None = None,
    ) -> WeatherForecast:
        """Get hourly weather forecast for the next N hours.

        Args:
            lat: latitude
            lon: longitude
            hours: number of hours to forecast (default: 6)
            target_date: target date/time (default: now)

        Returns:
            WeatherForecast with hourly snapshots
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join([
                "windspeed_10m",
                "winddirection_10m",
                "temperature_2m",
                "cloudcover",
                "precipitation",
                "surface_pressure",
            ]),
            "forecast_days": 2,
            "timezone": "auto",
        }

        resp = await self._client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        hourly = data["hourly"]
        times = hourly["time"]

        # Find the start index closest to target time
        if target_date is None:
            target_date = datetime.now()

        target_str = target_date.strftime("%Y-%m-%dT%H:00")
        start_idx = 0
        for i, t in enumerate(times):
            if t >= target_str:
                start_idx = i
                break

        end_idx = min(start_idx + hours, len(times))

        snapshots = []
        for i in range(start_idx, end_idx):
            snapshots.append(
                WeatherSnapshot(
                    timestamp=times[i],
                    lat=lat,
                    lon=lon,
                    wind_speed_kmh=hourly["windspeed_10m"][i] or 0.0,
                    wind_direction_deg=hourly["winddirection_10m"][i] or 0.0,
                    temperature_c=hourly["temperature_2m"][i] or 15.0,
                    cloudcover_percent=hourly["cloudcover"][i] or 0.0,
                    precipitation_mm=hourly["precipitation"][i] or 0.0,
                    surface_pressure_hpa=hourly["surface_pressure"][i] or 1013.25,
                )
            )

        if not snapshots:
            logger.warning("No weather data available, using defaults")
            snapshots = [
                WeatherSnapshot(
                    timestamp=target_date.isoformat(),
                    lat=lat,
                    lon=lon,
                    wind_speed_kmh=10.0,
                    wind_direction_deg=0.0,
                    temperature_c=15.0,
                    cloudcover_percent=50.0,
                    precipitation_mm=0.0,
                    surface_pressure_hpa=1013.25,
                )
            ]

        # Check for wind direction shift > 45°
        wind_shift_warning = None
        if len(snapshots) >= 2:
            dir_start = snapshots[0].wind_direction_deg
            for snap in snapshots[1:]:
                diff = abs(snap.wind_direction_deg - dir_start) % 360
                if diff > 180:
                    diff = 360 - diff
                if diff > 45:
                    wind_shift_warning = (
                        f"Vent tourne de {diff:.0f}° entre "
                        f"{snapshots[0].timestamp} et {snap.timestamp}"
                    )
                    break

        return WeatherForecast(
            snapshots=snapshots,
            wind_shift_warning=wind_shift_warning,
        )
