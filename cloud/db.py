"""
cloud/db.py
===========
Persistence layer with two interchangeable async repositories:

    MongoRepository     - MongoDB Atlas via Motor (async driver).
    InMemoryRepository  - zero-dependency fallback used when no MONGODB_URI is
                          configured or Motor isn't installed, and by the tests.

``build_repository()`` picks the right one at boot. Both expose the identical
async interface, so the rest of the service is storage-agnostic.

PRIVACY: documents hold only scores / event statistics. Raw frames are never
accepted, so they can never be stored. State buffers are capped to bound size.
"""

import time
import uuid

# Motor is optional - guarded so the module imports fine without it (tests,
# in-memory mode). Only MongoRepository actually needs it.
try:                                                        # pragma: no cover
    from motor.motor_asyncio import AsyncIOMotorClient
    _MOTOR_AVAILABLE = True
except Exception:                                           # pragma: no cover
    AsyncIOMotorClient = None
    _MOTOR_AVAILABLE = False

STATES_CAP = 5000      # max per-frame states retained per session (rolling)
EVENTS_CAP = 2000      # max event records retained per session (rolling)


def _new_id():
    return uuid.uuid4().hex


def _now():
    return time.time()


class InMemoryRepository:
    """Dict-backed async repo. Not durable - for dev, tests, and Mongo-less runs."""

    backend = "memory"

    def __init__(self):
        self._sessions = {}     # sid -> doc
        self._states = {}       # sid -> [state, ...]

    async def ping(self):
        return True

    async def create_session(self, device_id, started_at=None, meta=None):
        sid = _new_id()
        doc = {
            "session_id": sid, "device_id": str(device_id or "unknown"),
            "started_at": float(started_at or _now()), "closed_at": None,
            "status": "open", "meta": dict(meta or {}),
            "summary": {}, "prediction": None, "timeline": None,
            "states_count": 0, "events_count": 0, "events": [],
            "created_at": _now(), "updated_at": _now(),
        }
        self._sessions[sid] = doc
        self._states[sid] = []
        return sid

    async def get_session(self, sid):
        doc = self._sessions.get(sid)
        return dict(doc) if doc else None

    async def list_sessions(self, device_id=None, limit=50, skip=0):
        docs = list(self._sessions.values())
        if device_id:
            docs = [d for d in docs if d["device_id"] == device_id]
        docs.sort(key=lambda d: d["started_at"], reverse=True)
        return [dict(d) for d in docs[skip:skip + limit]]

    async def all_sessions(self, device_id=None):
        docs = list(self._sessions.values())
        if device_id:
            docs = [d for d in docs if d["device_id"] == device_id]
        return [dict(d) for d in docs]

    async def get_states(self, sid):
        return list(self._states.get(sid, []))

    async def add_states(self, sid, states):
        if sid not in self._sessions:
            return 0
        buf = self._states.setdefault(sid, [])
        buf.extend(states or [])
        if len(buf) > STATES_CAP:
            del buf[:len(buf) - STATES_CAP]
        self._sessions[sid]["states_count"] += len(states or [])
        self._sessions[sid]["updated_at"] = _now()
        return len(states or [])

    async def add_events(self, sid, events):
        if sid not in self._sessions:
            return 0
        doc = self._sessions[sid]
        doc["events"].extend(events or [])
        if len(doc["events"]) > EVENTS_CAP:
            doc["events"] = doc["events"][-EVENTS_CAP:]
        doc["events_count"] += len(events or [])
        doc["updated_at"] = _now()
        return len(events or [])

    async def update_session(self, sid, patch):
        if sid not in self._sessions:
            return False
        self._sessions[sid].update(patch or {})
        self._sessions[sid]["updated_at"] = _now()
        return True


class MongoRepository:
    """MongoDB Atlas repository (async, via Motor)."""

    backend = "mongodb"

    def __init__(self, uri, db_name="driver_safety"):
        if not _MOTOR_AVAILABLE:                            # pragma: no cover
            raise RuntimeError("motor is not installed")
        self._client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        self._db = self._client[db_name]
        self._sessions = self._db["sessions"]
        self._states = self._db["states"]

    async def ping(self):                                   # pragma: no cover
        await self._client.admin.command("ping")
        return True

    async def create_session(self, device_id, started_at=None, meta=None):  # pragma: no cover
        sid = _new_id()
        doc = {
            "_id": sid, "session_id": sid, "device_id": str(device_id or "unknown"),
            "started_at": float(started_at or _now()), "closed_at": None,
            "status": "open", "meta": dict(meta or {}),
            "summary": {}, "prediction": None, "timeline": None,
            "states_count": 0, "events_count": 0, "events": [],
            "created_at": _now(), "updated_at": _now(),
        }
        await self._sessions.insert_one(doc)
        return sid

    async def get_session(self, sid):                       # pragma: no cover
        doc = await self._sessions.find_one({"_id": sid}, {"events": {"$slice": -200}})
        if doc:
            doc.pop("_id", None)
        return doc

    async def list_sessions(self, device_id=None, limit=50, skip=0):  # pragma: no cover
        q = {"device_id": device_id} if device_id else {}
        cur = (self._sessions.find(q, {"events": 0})
               .sort("started_at", -1).skip(int(skip)).limit(int(limit)))
        out = []
        async for d in cur:
            d.pop("_id", None)
            out.append(d)
        return out

    async def all_sessions(self, device_id=None):           # pragma: no cover
        q = {"device_id": device_id} if device_id else {}
        cur = self._sessions.find(q, {"events": 0})    # keep summary for stats
        out = []
        async for d in cur:
            d.pop("_id", None)
            out.append(d)
        return out

    async def get_states(self, sid):                        # pragma: no cover
        doc = await self._states.find_one({"_id": sid})
        return (doc or {}).get("buf", [])

    async def add_states(self, sid, states):                # pragma: no cover
        states = states or []
        await self._states.update_one(
            {"_id": sid},
            {"$push": {"buf": {"$each": states, "$slice": -STATES_CAP}}},
            upsert=True,
        )
        await self._sessions.update_one(
            {"_id": sid},
            {"$inc": {"states_count": len(states)}, "$set": {"updated_at": _now()}},
        )
        return len(states)

    async def add_events(self, sid, events):                # pragma: no cover
        events = events or []
        await self._sessions.update_one(
            {"_id": sid},
            {"$push": {"events": {"$each": events, "$slice": -EVENTS_CAP}},
             "$inc": {"events_count": len(events)},
             "$set": {"updated_at": _now()}},
        )
        return len(events)

    async def update_session(self, sid, patch):             # pragma: no cover
        patch = dict(patch or {})
        patch["updated_at"] = _now()
        res = await self._sessions.update_one({"_id": sid}, {"$set": patch})
        return res.matched_count > 0


def build_repository(mongodb_uri="", db_name="driver_safety"):
    """Pick a repository: Mongo when a URI is configured and Motor is present,
    otherwise the in-memory fallback (dev / tests / Mongo-less deployments)."""
    if mongodb_uri and _MOTOR_AVAILABLE:                    # pragma: no cover
        try:
            return MongoRepository(mongodb_uri, db_name)
        except Exception:
            pass
    return InMemoryRepository()
