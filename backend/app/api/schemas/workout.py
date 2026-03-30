from pydantic import BaseModel


class WorkoutBlockResponse(BaseModel):
    index: int
    block_type: str
    duration_seconds: int
    power_watts: float
    power_percent_ftp: float | None = None
    cadence_target: int | None = None
    repeat_index: int | None = None


class WorkoutResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    planned_date: str
    sport_type: str = "cycling"
    duration_seconds: int | None = None
    tss_planned: float | None = None
    block_count: int = 0
    blocks: list[WorkoutBlockResponse] = []


class WorkoutSyncRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
