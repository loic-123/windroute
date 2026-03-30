from pydantic import BaseModel


class AthleteProfileResponse(BaseModel):
    id: str = ""
    intervals_athlete_id: str = ""
    name: str = ""
    weight_kg: float = 75.0
    ftp_watts: int = 250
    cda: float = 0.36
    bike_weight_kg: float = 8.0
    crr: float = 0.004
    home_lat: float | None = None
    home_lon: float | None = None
    default_position: str = "hoods"
    preferences: dict = {}


class AthleteProfileUpdate(BaseModel):
    name: str | None = None
    weight_kg: float | None = None
    ftp_watts: int | None = None
    cda: float | None = None
    bike_weight_kg: float | None = None
    crr: float | None = None
    home_lat: float | None = None
    home_lon: float | None = None
    default_position: str | None = None
    intervals_api_key: str | None = None
    intervals_athlete_id: str | None = None
    preferences: dict | None = None


class AthleteSyncRequest(BaseModel):
    api_key: str | None = None
    athlete_id: str | None = None
