"""Health check API router."""
from sqlalchemy import text
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", summary="Health check")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Returns the service health status.

    - Pings the PostgreSQL database with a lightweight `SELECT 1`.
    - Returns ``{"status": "ok", "db": "connected"}`` on success.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}
