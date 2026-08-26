"""
cloud/main.py
=============
FastAPI application wiring: settings -> repository -> service, plus CORS,
API-key auth and the versioned REST surface consumed by the mobile companion.

Run locally:
    uvicorn cloud.main:app --reload --port 8000
Behind Docker/nginx in production: see docker-compose.yml + deploy/nginx.

Endpoints (all under /api/v1, JSON):
    GET  /health                       liveness + storage + reuse status (public)
    POST /sessions                     open a trip session
    GET  /sessions                     list sessions (?device_id&limit&skip)
    GET  /sessions/{id}                one session (summary + prediction + timeline)
    POST /sessions/{id}/states         sync per-frame state batch (server re-derives)
    POST /sessions/{id}/events         sync event batch (stats only)
    GET  /sessions/{id}/timeline       trip risk timeline (shared module output)
    GET  /sessions/{id}/prediction     drowsiness forecast (shared module output)
    POST /sessions/{id}/close          finalize a session
    GET  /stats                        aggregate safety stats (?device_id)
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cloud import service
from cloud.db import build_repository
from cloud.settings import get_settings
from cloud.security import APIKeyGuard
from cloud.shared import reuse_status
from cloud.models import SessionCreate, StateBatch, EventBatch, SessionClose

settings = get_settings()
repo = build_repository(settings.mongodb_uri, settings.mongodb_db)
guard = APIKeyGuard(settings)

app = FastAPI(
    title="Driver Safety Cloud",
    version="1.0.0",
    description="Cloud sync & analytics for the Driver Drowsiness Detection system. "
                "Reuses the edge analytics modules; stores scores only (no frames).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*", "X-API-Key"],
)

V1 = "/api/v1"


@app.get("/")
async def root():
    return {"service": "driver-safety-cloud", "version": app.version,
            "docs": "/docs", "health": f"{V1}/health"}


@app.get(V1 + "/health")
async def health():
    try:
        db_ok = await repo.ping()
    except Exception:                                       # pragma: no cover
        db_ok = False
    return {
        "ok": True,
        "storage_backend": getattr(repo, "backend", "unknown"),
        "storage_reachable": bool(db_ok),
        "reuse": reuse_status(),
        "settings": settings.public_dict(),
    }


# ------------------------------ sessions --------------------------------- #
@app.post(V1 + "/sessions")
async def create_session(body: SessionCreate, _=Depends(guard)):
    return await service.create_session(repo, body.device_id, body.started_at, body.meta)


@app.get(V1 + "/sessions")
async def list_sessions(device_id: str = None, limit: int = 50, skip: int = 0,
                        _=Depends(guard)):
    limit = max(1, min(int(limit), 200))
    return await service.list_sessions(repo, device_id, limit, max(0, int(skip)))


@app.get(V1 + "/sessions/{sid}")
async def get_session(sid: str, _=Depends(guard)):
    doc = await service.get_session(repo, sid)
    if not doc:
        raise HTTPException(404, "session not found")
    return doc


@app.post(V1 + "/sessions/{sid}/states")
async def post_states(sid: str, body: StateBatch, _=Depends(guard)):
    res = await service.ingest_states(repo, sid, body.states)
    if res is None:
        raise HTTPException(404, "session not found")
    return res


@app.post(V1 + "/sessions/{sid}/events")
async def post_events(sid: str, body: EventBatch, _=Depends(guard)):
    res = await service.ingest_events(repo, sid, body.events)
    if res is None:
        raise HTTPException(404, "session not found")
    return res


@app.get(V1 + "/sessions/{sid}/timeline")
async def session_timeline(sid: str, _=Depends(guard)):
    tl = await service.get_session_timeline(repo, sid)
    if tl is None:
        raise HTTPException(404, "session not found")
    return tl


@app.get(V1 + "/sessions/{sid}/prediction")
async def session_prediction(sid: str, _=Depends(guard)):
    pr = await service.get_session_prediction(repo, sid)
    if pr is None:
        raise HTTPException(404, "session not found")
    return pr


@app.post(V1 + "/sessions/{sid}/close")
async def close_session(sid: str, body: SessionClose, _=Depends(guard)):
    doc = await service.close_session(repo, sid, body.summary)
    if not doc:
        raise HTTPException(404, "session not found")
    return doc


# ------------------------------- stats ----------------------------------- #
@app.get(V1 + "/stats")
async def stats(device_id: str = None, _=Depends(guard)):
    return await service.get_stats(repo, device_id)


if __name__ == "__main__":                                  # pragma: no cover
    import uvicorn
    uvicorn.run("cloud.main:app", host=settings.host, port=settings.port, reload=False)
