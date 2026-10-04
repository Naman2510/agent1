"""Top-level v1 router."""

from fastapi import APIRouter

from app.api.routes import admin, auth, chat, health, sessions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
