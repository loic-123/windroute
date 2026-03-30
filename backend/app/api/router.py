from fastapi import APIRouter

from app.api.routes import athlete, health, routes, weather, workouts

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(athlete.router)
api_router.include_router(workouts.router)
api_router.include_router(weather.router)
api_router.include_router(routes.router)
