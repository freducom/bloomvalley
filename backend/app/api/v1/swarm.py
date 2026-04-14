"""Analyst swarm status — read/write via Redis."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()

REDIS_KEY = "swarm:status"


class SwarmStatusUpdate(BaseModel):
    status: str  # idle, running, complete
    agent: str | None = None  # currently running agent
    completed: int = 0
    total: int = 0
    message: str | None = None


@router.get("/status")
async def get_swarm_status(request: Request):
    """Get current analyst swarm status from Redis."""
    redis = request.app.state.redis
    data = await redis.hgetall(REDIS_KEY)
    if not data:
        return {"data": {"status": "idle"}, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}
    return {
        "data": {
            "status": data.get("status", "idle"),
            "agent": data.get("agent"),
            "completed": int(data.get("completed", 0)),
            "total": int(data.get("total", 0)),
            "message": data.get("message"),
            "updatedAt": data.get("updated_at"),
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/status")
async def update_swarm_status(request: Request, update: SwarmStatusUpdate):
    """Update analyst swarm status (called by swarm container)."""
    redis = request.app.state.redis
    await redis.hset(REDIS_KEY, mapping={
        "status": update.status,
        "agent": update.agent or "",
        "completed": str(update.completed),
        "total": str(update.total),
        "message": update.message or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    # Auto-expire: running status gets 4 hours (per-security runs are long),
    # idle status gets 10 minutes (stale crash detection)
    ttl = 14400 if update.status == "running" else 600
    await redis.expire(REDIS_KEY, ttl)
    return {"ok": True}
