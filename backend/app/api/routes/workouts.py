from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas.workout import (
    WorkoutBlockResponse,
    WorkoutResponse,
    WorkoutSyncRequest,
)
from app.clients.intervals_client import IntervalsClient
from app.dependencies import get_supabase

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("", response_model=list[WorkoutResponse])
async def list_workouts(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db=Depends(get_supabase),
):
    query = db.table("workouts").select("*").order("planned_date", desc=True)
    if date_from:
        query = query.gte("planned_date", date_from)
    if date_to:
        query = query.lte("planned_date", date_to)

    result = query.limit(50).execute()

    workouts = []
    for row in result.data:
        blocks = [
            WorkoutBlockResponse(**b) for b in (row.get("parsed_blocks") or [])
        ]
        workouts.append(
            WorkoutResponse(
                id=row["id"],
                name=row["name"],
                description=row.get("description", ""),
                planned_date=str(row["planned_date"]),
                sport_type=row.get("sport_type", "cycling"),
                duration_seconds=row.get("duration_seconds"),
                tss_planned=row.get("tss_planned"),
                block_count=row.get("block_count", len(blocks)),
                blocks=blocks,
            )
        )
    return workouts


@router.get("/{workout_id}", response_model=WorkoutResponse)
async def get_workout(workout_id: str, db=Depends(get_supabase)):
    result = db.table("workouts").select("*").eq("id", workout_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Workout not found")

    row = result.data[0]
    blocks = [
        WorkoutBlockResponse(**b) for b in (row.get("parsed_blocks") or [])
    ]
    return WorkoutResponse(
        id=row["id"],
        name=row["name"],
        description=row.get("description", ""),
        planned_date=str(row["planned_date"]),
        sport_type=row.get("sport_type", "cycling"),
        duration_seconds=row.get("duration_seconds"),
        tss_planned=row.get("tss_planned"),
        block_count=row.get("block_count", len(blocks)),
        blocks=blocks,
    )


@router.post("/sync", response_model=list[WorkoutResponse])
async def sync_workouts(
    request: WorkoutSyncRequest,
    db=Depends(get_supabase),
):
    # Get athlete info
    athlete_result = db.table("athletes").select("*").limit(1).execute()
    if not athlete_result.data:
        raise HTTPException(status_code=400, detail="No athlete profile found. Set up profile first.")

    athlete = athlete_result.data[0]
    api_key = athlete.get("intervals_api_key")
    athlete_icu_id = athlete.get("intervals_athlete_id")

    if not api_key or not athlete_icu_id:
        raise HTTPException(
            status_code=400,
            detail="intervals.icu credentials not configured in profile",
        )

    ftp = athlete.get("ftp_watts", 250)

    date_from = date.fromisoformat(request.date_from) if request.date_from else date.today()
    date_to = date.fromisoformat(request.date_to) if request.date_to else date_from + timedelta(days=7)

    client = IntervalsClient(api_key=api_key, athlete_id=athlete_icu_id)
    try:
        events = await client.get_cycling_workouts(date_from, date_to)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"intervals.icu error: {e}")
    finally:
        await client.close()

    synced = []
    for event in events:
        parsed = client.parse_workout(event, ftp)
        blocks_data = [
            {
                "index": b.index,
                "block_type": b.block_type.value,
                "duration_seconds": b.duration_seconds,
                "power_watts": b.power_watts,
                "power_percent_ftp": b.power_percent_ftp,
                "cadence_target": b.cadence_target,
                "repeat_index": b.repeat_index,
            }
            for b in parsed.blocks
        ]

        workout_data = {
            "athlete_id": athlete["id"],
            "intervals_event_id": str(event.get("id", "")),
            "name": parsed.name,
            "description": parsed.description,
            "planned_date": event.get("start_date", date_from.isoformat())[:10],
            "sport_type": event.get("type", "cycling"),
            "duration_seconds": parsed.total_duration_seconds,
            "workout_definition": event.get("workout_doc", {}),
            "parsed_blocks": blocks_data,
        }

        # Upsert by intervals_event_id
        event_id = str(event.get("id", ""))
        existing = (
            db.table("workouts")
            .select("id")
            .eq("intervals_event_id", event_id)
            .execute()
        )

        if existing.data:
            result = (
                db.table("workouts")
                .update(workout_data)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
        else:
            result = db.table("workouts").insert(workout_data).execute()

        if result.data:
            row = result.data[0]
            blocks_resp = [WorkoutBlockResponse(**b) for b in blocks_data]
            synced.append(
                WorkoutResponse(
                    id=row["id"],
                    name=row["name"],
                    description=row.get("description", ""),
                    planned_date=str(row["planned_date"]),
                    sport_type=row.get("sport_type", "cycling"),
                    duration_seconds=row.get("duration_seconds"),
                    block_count=len(blocks_data),
                    blocks=blocks_resp,
                )
            )

    return synced
