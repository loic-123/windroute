from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Intervals.icu
    intervals_icu_api_key: str = ""
    intervals_icu_athlete_id: str = ""

    # Supabase
    supabase_url: str = "http://localhost:54321"
    supabase_service_key: str = ""

    # Strava (optional)
    strava_access_token: str = ""

    # App
    cache_dir: str = ".cache"
    log_level: str = "INFO"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:3000"

    # Bike defaults
    default_cda: float = 0.36
    default_bike_weight_kg: float = 8.0
    default_crr: float = 0.004

    # Optimization toggles
    use_wind_optimization: bool = True
    use_sunshine_optimization: bool = True
    use_strava_heatmap: bool = False

    # Route parameters
    climb_mode: str = "auto"  # auto | repeat | loop
    road_type_filter: str = "road"  # road | gravel | mixed
    max_route_radius_km: float = 50.0
    min_climb_grade_percent: float = 3.0
    climb_min_duration_ratio: float = 0.80
    repeat_mode_min_climb_km: float = 2.0
    repeat_mode_min_intervals: int = 3

    # Wind
    wind_bearing_tolerance_deg: float = 45.0
    wind_bearing_max_tolerance_deg: float = 90.0

    # Elastic durations
    warmup_min_duration_s: int = 600
    cooldown_min_duration_s: int = 300
    warmup_elastic_ratio_short: float = 0.40
    warmup_elastic_ratio_long: float = 0.20

    # Scoring weights (sum = 1.0)
    wind_weight: float = 0.35
    climb_weight: float = 0.40
    sunshine_weight: float = 0.15
    heatmap_weight: float = 0.10

    @property
    def cache_path(self) -> Path:
        p = Path(self.cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
