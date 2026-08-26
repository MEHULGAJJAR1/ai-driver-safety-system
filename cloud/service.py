"""
cloud/service.py
================
Async business logic. Ties the storage repository (cloud/db.py) to the reused
analytics core (cloud/analytics_runner.py). Deliberately free of FastAPI and
Pydantic so it can be unit-tested directly with ``asyncio.run(...)``.

The key move: whenever new per-frame state is ingested (or a session closes),
we replay the session's buffered states through the SHARED
``DrowsinessPredictor`` / ``TripRiskTimeline`` and persist the derived forecast
and trip timeline. The cloud therefore reports the same numbers as the edge,
computed by the same code.
"""

from cloud.analytics_runner import replay_states, aggregate_stats


async def create_session(repo, device_id, started_at=None, meta=None):
    sid = await repo.create_session(device_id, started_at, meta)
    return await repo.get_session(sid)


async def _refresh_derived(repo, sid):
    """Replay buffered states through the shared modules and store the result."""
    states = await repo.get_states(sid)
    derived = replay_states(states)
    await repo.update_session(sid, {
        "prediction": derived.get("prediction"),
        "timeline": derived.get("timeline"),
    })
    return derived


async def ingest_states(repo, sid, states):
    session = await repo.get_session(sid)
    if not session:
        return None
    n = await repo.add_states(sid, states)
    derived = await _refresh_derived(repo, sid)
    return {
        "ok": True, "session_id": sid, "ingested": n,
        "states_count": (session.get("states_count", 0) + n),
        "prediction": derived.get("prediction"),
        "timeline": derived.get("timeline"),
    }


async def ingest_events(repo, sid, events):
    session = await repo.get_session(sid)
    if not session:
        return None
    n = await repo.add_events(sid, events)
    return {"ok": True, "session_id": sid, "ingested": n}


async def close_session(repo, sid, summary=None):
    session = await repo.get_session(sid)
    if not session:
        return None
    import time as _t
    await _refresh_derived(repo, sid)
    await repo.update_session(sid, {
        "status": "closed", "closed_at": _t.time(),
        "summary": dict(summary or {}),
    })
    return await repo.get_session(sid)


async def get_session(repo, sid):
    return await repo.get_session(sid)


async def get_session_timeline(repo, sid):
    session = await repo.get_session(sid)
    if not session:
        return None
    return session.get("timeline") or replay_states(await repo.get_states(sid)).get("timeline")


async def get_session_prediction(repo, sid):
    session = await repo.get_session(sid)
    if not session:
        return None
    return session.get("prediction") or replay_states(await repo.get_states(sid)).get("prediction")


async def list_sessions(repo, device_id=None, limit=50, skip=0):
    items = await repo.list_sessions(device_id, limit, skip)
    return {"count": len(items), "sessions": items}


async def get_stats(repo, device_id=None):
    sessions = await repo.all_sessions(device_id)
    closed = [s for s in sessions if s.get("status") == "closed"]
    stats = aggregate_stats(closed)
    stats["open_sessions"] = len([s for s in sessions if s.get("status") == "open"])
    stats["device_id"] = device_id
    return stats
