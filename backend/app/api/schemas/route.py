from pydantic import BaseModel


class GenerateRequest(BaseModel):
    athlete_id: str | None = None
    workout_id: str | None = None
    manual_workout: dict | None = None
    start_lat: float
    start_lon: float
    departure_time: str | None = None
    options: dict = {}


class ClimbResponse(BaseModel):
    id: str
    length_km: float
    avg_grade_percent: float
    max_grade_percent: float
    elevation_gain_m: float
    estimated_duration_s: float
    quality_score: float
    road_type: str


class RouteResponse(BaseModel):
    id: str
    variant: str
    name: str
    status: str
    total_distance_km: float | None = None
    total_elevation_m: float | None = None
    estimated_duration_s: int | None = None
    warmup_distance_km: float | None = None
    cooldown_distance_km: float | None = None
    wind_score: float | None = None
    climb_score: float | None = None
    sunshine_score: float | None = None
    heatmap_score: float | None = None
    overall_score: float | None = None
    geojson: dict | None = None
    climbs: list[ClimbResponse] = []
    warnings: list[str] = []
    weather_snapshot: dict | None = None


class GenerationJobResponse(BaseModel):
    job_id: str
    status: str
    progress_percent: int = 0
    progress_message: str | None = None
    route_ids: list[str] = []
    error_message: str | None = None
