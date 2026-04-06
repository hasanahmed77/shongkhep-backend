from fastapi import APIRouter

from app.api.v1.endpoints import health, news, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
