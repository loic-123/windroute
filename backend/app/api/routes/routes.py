"""
Route generation endpoints with async job tracking.
"""

import asyncio
import logging
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from app.api.schemas.route import (
    ClimbResponse,
    GenerateRequest,
    GenerationJobResponse,
    RouteResponse,
)
from app.clients.intervals_client import IntervalsClient
from app.clients.openmeteo_client import OpenMeteoClient
from app.dependencies import get_supabase
from app.engine.route_generator import GenerationParams, generate_routes
from app.models.athlete import AthleteProfile
from app.models.workout import ParsedWorkout, WorkoutBlock, BlockType
from app.output.gpx_exporter import export_gpx, export_summary_json
from app.output.map_data import route_to_geojson

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["routes"])

# Thread pool for CPU-heavy generation (doesn't block the event loop)
_executor = ThreadPoolExecutor(max_workers=2)


@router.post("/generate", response_model=GenerationJobResponse)
async def start_generation(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_supabase),
):
    """Start async route generation. Returns job_id for polling."""
    # Get or create athlete
    athlete_result = db.table("athletes").select("*").limit(1).execute()
    if not athlete_result.data:
        raise HTTPException(400, "No athlete profile. Set up profile first.")

    athlete_data = athlete_result.data[0]

    # Create job
    job_id = str(uuid.uuid4())
    db.table("generation_jobs").insert({
        "id": job_id,
        "athlete_id": athlete_data["id"],
        "workout_id": request.workout_id,
        "status": "queued",
        "params": request.model_dump(),
    }).execute()

    # Run in a separate thread so OSMnx loading doesn't block the server
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _executor,
        lambda: asyncio.run(_run_generation(job_id, request, athlete_data, db)),
    )

    return GenerationJobResponse(job_id=job_id, status="queued")


@router.get("/jobs/{job_id}", response_model=GenerationJobResponse)
async def get_job_status(job_id: str, db=Depends(get_supabase)):
    result = db.table("generation_jobs").select("*").eq("id", job_id).execute()
    if not result.data:
        raise HTTPException(404, "Job not found")

    job = result.data[0]
    return GenerationJobResponse(
        job_id=job["id"],
        status=job["status"],
        progress_percent=job.get("progress_percent", 0),
        progress_message=job.get("progress_message"),
        route_ids=[str(r) for r in (job.get("route_ids") or [])],
        error_message=job.get("error_message"),
    )


@router.get("", response_model=list[RouteResponse])
async def list_routes(
    limit: int = 20,
    db=Depends(get_supabase),
):
    result = (
        db.table("generated_routes")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_row_to_route_response(r) for r in result.data]


@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(route_id: str, db=Depends(get_supabase)):
    result = db.table("generated_routes").select("*").eq("id", route_id).execute()
    if not result.data:
        raise HTTPException(404, "Route not found")

    route_data = result.data[0]

    # Get climbs
    climbs_result = (
        db.table("route_climbs")
        .select("*")
        .eq("route_id", route_id)
        .order("climb_index")
        .execute()
    )

    return _row_to_route_response(route_data, climbs_result.data)


@router.get("/{route_id}/gpx")
async def download_gpx(route_id: str, db=Depends(get_supabase)):
    result = (
        db.table("generated_routes")
        .select("gpx_data, name")
        .eq("id", route_id)
        .execute()
    )
    if not result.data or not result.data[0].get("gpx_data"):
        raise HTTPException(404, "GPX not found")

    gpx_data = result.data[0]["gpx_data"]
    name = result.data[0].get("name", "windroute")
    filename = f"{name.replace(' ', '_')}.gpx"

    return Response(
        content=gpx_data,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{route_id}/summary")
async def get_summary(route_id: str, db=Depends(get_supabase)):
    result = (
        db.table("generated_routes")
        .select("summary_json")
        .eq("id", route_id)
        .execute()
    )
    if not result.data or not result.data[0].get("summary_json"):
        raise HTTPException(404, "Summary not found")
    return result.data[0]["summary_json"]


@router.put("/{route_id}/select")
async def select_route(route_id: str, db=Depends(get_supabase)):
    # Deselect all routes for this workout
    route_result = (
        db.table("generated_routes").select("workout_id").eq("id", route_id).execute()
    )
    if not route_result.data:
        raise HTTPException(404, "Route not found")

    workout_id = route_result.data[0].get("workout_id")
    if workout_id:
        db.table("generated_routes").update({"selected": False}).eq(
            "workout_id", workout_id
        ).execute()

    db.table("generated_routes").update({"selected": True}).eq(
        "id", route_id
    ).execute()
    return {"status": "ok"}


@router.delete("/{route_id}")
async def delete_route(route_id: str, db=Depends(get_supabase)):
    db.table("generated_routes").delete().eq("id", route_id).execute()
    return {"status": "ok"}


# ── Background generation task ───────────────────────────────────


async def _run_generation(
    job_id: str,
    request: GenerateRequest,
    athlete_data: dict,
    db,
):
    """Background task that runs the full generation pipeline."""
    try:
        _update_job(db, job_id, "running", 5, "Initialisation...")

        # Build athlete profile
        athlete = AthleteProfile(
            id=athlete_data["id"],
            intervals_athlete_id=athlete_data.get("intervals_athlete_id", ""),
            name=athlete_data.get("name", ""),
            weight_kg=float(athlete_data.get("weight_kg", 75)),
            ftp_watts=int(athlete_data.get("ftp_watts", 250)),
            cda=float(athlete_data.get("cda", 0.36)),
            bike_weight_kg=float(athlete_data.get("bike_weight_kg", 8.0)),
            crr=float(athlete_data.get("crr", 0.004)),
            home_lat=request.start_lat,
            home_lon=request.start_lon,
        )

        # Get workout
        _update_job(db, job_id, "running", 10, "Récupération de la séance...")

        if request.workout_id:
            workout_result = (
                db.table("workouts").select("*").eq("id", request.workout_id).execute()
            )
            if not workout_result.data:
                raise ValueError("Workout not found")

            row = workout_result.data[0]
            blocks = [
                WorkoutBlock(
                    index=b["index"],
                    block_type=BlockType(b["block_type"]),
                    duration_seconds=b["duration_seconds"],
                    power_watts=b["power_watts"],
                    power_percent_ftp=b.get("power_percent_ftp"),
                    cadence_target=b.get("cadence_target"),
                    repeat_index=b.get("repeat_index"),
                )
                for b in row["parsed_blocks"]
            ]
            workout = ParsedWorkout(
                name=row["name"],
                description=row.get("description", ""),
                blocks=blocks,
            )
        elif request.manual_workout:
            workout = _parse_manual_workout(request.manual_workout, athlete.ftp_watts)
        else:
            # No workout selected: generate a default endurance ride
            duration_s = request.options.get("duration_seconds", 5400)  # default 1h30
            workout = _build_default_endurance(athlete.ftp_watts, int(duration_s))

        # Get weather
        _update_job(db, job_id, "running", 20, "Récupération météo...")

        target_dt = (
            datetime.fromisoformat(request.departure_time)
            if request.departure_time
            else None
        )
        meteo = OpenMeteoClient()
        try:
            forecast = await meteo.get_forecast(
                request.start_lat, request.start_lon, 6, target_dt
            )
        finally:
            await meteo.close()

        # Generate routes
        _update_job(db, job_id, "running", 30, "Chargement du graphe OSM...")

        options = request.options or {}
        params = GenerationParams(
            lat=request.start_lat,
            lon=request.start_lon,
            athlete=athlete,
            workout=workout,
            forecast=forecast,
            climb_mode=options.get("climb_mode", "auto"),
            road_type=options.get("road_type", "road"),
            max_radius_km=options.get("max_radius_km", 50),
            weights=options.get("weights"),
        )

        _update_job(db, job_id, "running", 50, "Génération des routes...")
        routes = await generate_routes(params)

        if not routes:
            raise ValueError("Aucune route n'a pu être générée")

        # Save routes to DB
        _update_job(db, job_id, "running", 85, "Sauvegarde des routes...")
        route_ids = []

        weather_snap = {
            "wind_speed_kmh": forecast.current.wind_speed_kmh,
            "wind_direction_deg": forecast.current.wind_direction_deg,
            "wind_direction_label": forecast.current.wind_direction_label,
            "temperature_c": forecast.current.temperature_c,
            "cloudcover_percent": forecast.current.cloudcover_percent,
        }

        for route in routes:
            gpx = export_gpx(route, workout.name)
            geojson = route_to_geojson(route)
            summary = export_summary_json(route, workout.name)

            route_data = {
                "athlete_id": athlete_data["id"],
                "workout_id": request.workout_id,
                "variant": route.variant,
                "name": f"{workout.name} — Variante {route.variant}",
                "status": "completed",
                "gpx_data": gpx,
                "geojson": geojson,
                "coords": [list(c) for c in route.coords],
                "start_lat": request.start_lat,
                "start_lon": request.start_lon,
                "total_distance_km": route.total_distance_km,
                "total_elevation_m": route.total_elevation_m,
                "warmup_distance_km": route.warmup_distance_km,
                "warmup_duration_actual_s": route.warmup_duration_actual_s,
                "warmup_duration_initial_s": route.warmup_duration_initial_s,
                "cooldown_distance_km": route.cooldown_distance_km,
                "cooldown_duration_actual_s": route.cooldown_duration_actual_s,
                "cooldown_duration_initial_s": route.cooldown_duration_initial_s,
                "estimated_duration_s": route.estimated_duration_s,
                "wind_score": route.wind_score,
                "climb_score": route.climb_score,
                "sunshine_score": route.sunshine_score,
                "heatmap_score": route.heatmap_score,
                "overall_score": route.overall_score,
                "weather_snapshot": weather_snap,
                "generation_params": request.model_dump(),
                "warnings": route.warnings,
                "summary_json": summary,
            }

            result = db.table("generated_routes").insert(route_data).execute()
            route_id = result.data[0]["id"]
            route_ids.append(route_id)

            # Save climbs
            for i, climb in enumerate(route.climbs):
                db.table("route_climbs").insert({
                    "route_id": route_id,
                    "climb_index": i,
                    "length_m": climb.length_m,
                    "avg_grade_percent": climb.avg_grade_percent,
                    "max_grade_percent": climb.max_grade_percent,
                    "elevation_gain_m": climb.elevation_gain_m,
                    "grade_stddev": climb.grade_stddev,
                    "road_type": climb.road_type,
                    "start_lat": climb.start_lat,
                    "start_lon": climb.start_lon,
                    "end_lat": climb.end_lat,
                    "end_lon": climb.end_lon,
                    "estimated_duration_s": int(climb.estimated_duration_s),
                    "quality_score": climb.quality_score,
                }).execute()

        _update_job(
            db, job_id, "completed", 100, "Terminé",
            route_ids=route_ids,
        )

    except Exception as e:
        logger.error("Generation failed: %s\n%s", e, traceback.format_exc())
        _update_job(db, job_id, "failed", 0, error_message=str(e))


def _update_job(
    db,
    job_id: str,
    status: str,
    progress: int,
    message: str | None = None,
    route_ids: list[str] | None = None,
    error_message: str | None = None,
):
    data = {
        "status": status,
        "progress_percent": progress,
        "progress_message": message,
    }
    if route_ids is not None:
        data["route_ids"] = route_ids
    if error_message is not None:
        data["error_message"] = error_message
    if status == "running" and progress == 5:
        data["started_at"] = datetime.now().isoformat()
    if status in ("completed", "failed"):
        data["completed_at"] = datetime.now().isoformat()

    db.table("generation_jobs").update(data).eq("id", job_id).execute()


def _parse_manual_workout(manual: dict, ftp: int) -> ParsedWorkout:
    """Parse a manual workout definition (--manual mode)."""
    intervals_str = manual.get("intervals", "")
    warmup_s = manual.get("warmup_seconds", 900)
    cooldown_s = manual.get("cooldown_seconds", 600)

    blocks = [
        WorkoutBlock(
            index=0,
            block_type=BlockType.WARMUP,
            duration_seconds=warmup_s,
            power_watts=ftp * 0.55,
            power_percent_ftp=55.0,
        )
    ]

    # Parse format: "5x300w:300s/150w:180s"
    if "x" in intervals_str:
        parts = intervals_str.split("x", 1)
        repeat_count = int(parts[0])
        interval_def = parts[1]

        segments = interval_def.split("/")
        idx = 1
        for rep in range(repeat_count):
            for i, seg in enumerate(segments):
                power_str, dur_str = seg.split(":")
                power = float(power_str.replace("w", "").replace("W", ""))
                duration = int(dur_str.replace("s", "").replace("S", ""))

                is_work = i % 2 == 0
                blocks.append(
                    WorkoutBlock(
                        index=idx,
                        block_type=BlockType.INTERVAL if is_work else BlockType.RECOVERY,
                        duration_seconds=duration,
                        power_watts=power,
                        repeat_index=rep,
                    )
                )
                idx += 1

    blocks.append(
        WorkoutBlock(
            index=len(blocks),
            block_type=BlockType.COOLDOWN,
            duration_seconds=cooldown_s,
            power_watts=ftp * 0.50,
            power_percent_ftp=50.0,
        )
    )

    return ParsedWorkout(name="Manual Workout", blocks=blocks)


def _build_default_endurance(ftp: int, total_duration_s: int = 5400) -> ParsedWorkout:
    """Build a simple endurance ride: warmup + endurance + cooldown."""
    warmup_s = min(900, total_duration_s // 6)
    cooldown_s = min(600, total_duration_s // 6)
    main_s = total_duration_s - warmup_s - cooldown_s

    blocks = [
        WorkoutBlock(
            index=0,
            block_type=BlockType.WARMUP,
            duration_seconds=warmup_s,
            power_watts=ftp * 0.55,
            power_percent_ftp=55.0,
        ),
        WorkoutBlock(
            index=1,
            block_type=BlockType.INTERVAL,
            duration_seconds=main_s,
            power_watts=ftp * 0.65,
            power_percent_ftp=65.0,
        ),
        WorkoutBlock(
            index=2,
            block_type=BlockType.COOLDOWN,
            duration_seconds=cooldown_s,
            power_watts=ftp * 0.50,
            power_percent_ftp=50.0,
        ),
    ]

    hours = total_duration_s / 3600
    return ParsedWorkout(name=f"Endurance {hours:.1f}h", blocks=blocks)


def _row_to_route_response(
    row: dict, climbs_data: list[dict] | None = None
) -> RouteResponse:
    climbs = []
    if climbs_data:
        for c in climbs_data:
            climbs.append(ClimbResponse(
                id=c["id"],
                length_km=round(float(c.get("length_m", 0)) / 1000, 2),
                avg_grade_percent=float(c.get("avg_grade_percent", 0)),
                max_grade_percent=float(c.get("max_grade_percent", 0)),
                elevation_gain_m=float(c.get("elevation_gain_m", 0)),
                estimated_duration_s=float(c.get("estimated_duration_s", 0)),
                quality_score=float(c.get("quality_score", 0)),
                road_type=c.get("road_type", "unknown"),
            ))

    return RouteResponse(
        id=row["id"],
        variant=row.get("variant", ""),
        name=row.get("name", ""),
        status=row.get("status", ""),
        total_distance_km=row.get("total_distance_km"),
        total_elevation_m=row.get("total_elevation_m"),
        estimated_duration_s=row.get("estimated_duration_s"),
        warmup_distance_km=row.get("warmup_distance_km"),
        cooldown_distance_km=row.get("cooldown_distance_km"),
        wind_score=row.get("wind_score"),
        climb_score=row.get("climb_score"),
        sunshine_score=row.get("sunshine_score"),
        heatmap_score=row.get("heatmap_score"),
        overall_score=row.get("overall_score"),
        geojson=row.get("geojson"),
        climbs=climbs,
        warnings=row.get("warnings", []),
        weather_snapshot=row.get("weather_snapshot"),
    )
