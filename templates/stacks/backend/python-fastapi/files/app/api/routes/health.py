"""Health/liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Return a simple liveness payload.

    Returns:
        ``{"status": "ok"}`` when the service is running.
    """
    return {"status": "ok"}
