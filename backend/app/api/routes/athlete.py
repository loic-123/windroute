from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas.athlete import (
    AthleteProfileResponse,
    AthleteProfileUpdate,
    AthleteSyncRequest,
)
from app.clients.intervals_client import IntervalsClient
from app.dependencies import get_supabase

router = APIRouter(prefix="/athlete", tags=["athlete"])


@router.get("/profile", response_model=AthleteProfileResponse)
async def get_profile(db=Depends(get_supabase)):
    result = db.table("athletes").select("*").limit(1).execute()
    if not result.data:
        # Create default athlete
        new = db.table("athletes").insert({}).execute()
        return AthleteProfileResponse(**new.data[0])
    return AthleteProfileResponse(**result.data[0])


@router.put("/profile", response_model=AthleteProfileResponse)
async def update_profile(
    update: AthleteProfileUpdate,
    db=Depends(get_supabase),
):
    result = db.table("athletes").select("id").limit(1).execute()
    if not result.data:
        data = update.model_dump(exclude_none=True)
        new = db.table("athletes").insert(data).execute()
        return AthleteProfileResponse(**new.data[0])

    athlete_id = result.data[0]["id"]
    data = update.model_dump(exclude_none=True)
    updated = (
        db.table("athletes").update(data).eq("id", athlete_id).execute()
    )
    return AthleteProfileResponse(**updated.data[0])


@router.post("/sync", response_model=AthleteProfileResponse)
async def sync_from_intervals(
    request: AthleteSyncRequest,
    db=Depends(get_supabase),
):
    client = IntervalsClient(
        api_key=request.api_key,
        athlete_id=request.athlete_id,
    )
    try:
        profile = await client.get_athlete_profile()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"intervals.icu error: {e}")
    finally:
        await client.close()

    # Upsert athlete
    result = db.table("athletes").select("id").limit(1).execute()
    data = {
        "name": profile.name,
        "weight_kg": profile.weight_kg,
        "ftp_watts": profile.ftp_watts,
        "intervals_athlete_id": profile.intervals_athlete_id,
    }
    if request.api_key:
        data["intervals_api_key"] = request.api_key

    if result.data:
        updated = (
            db.table("athletes").update(data).eq("id", result.data[0]["id"]).execute()
        )
        return AthleteProfileResponse(**updated.data[0])
    else:
        new = db.table("athletes").insert(data).execute()
        return AthleteProfileResponse(**new.data[0])
