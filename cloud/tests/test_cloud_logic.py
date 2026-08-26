"""
cloud/tests/test_cloud_logic.py
===============================
Offline verification of the cloud service's LOGIC without needing FastAPI,
Uvicorn, Motor or a real MongoDB. It covers the two things that actually carry
risk:

    1. REUSE  - the cloud replays synced state through the very same
                analytics classes the edge uses, and reproduces the edge's
                numbers exactly (parity check).
    2. FLOW   - create -> ingest states -> ingest events -> close -> stats,
                against the in-memory repository, driving the async service
                layer with asyncio.

Run from the project root:  python cloud/tests/test_cloud_logic.py
"""

import asyncio
import os
import sys

# project root = parent of cloud/
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cloud.shared import reuse_status, ANALYTICS_AVAILABLE, DrowsinessPredictor
from cloud.analytics_runner import replay_states, aggregate_stats
from cloud.db import InMemoryRepository, build_repository
from cloud.settings import get_settings
from cloud import service

_fail = []
def ck(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        _fail.append(name)


def _frame(i):
    score = min(100.0, i * 4.0)
    band = "LOW" if score < 50 else ("MEDIUM" if score < 80 else "HIGH")
    return {
        "ts": 1000.0 + i,
        "score": score,
        "perclos": min(0.5, 0.05 + 0.02 * i),
        "yawning": (i % 5 == 0),
        "risk_level": band,
        "safety_score": max(10.0, 100.0 - score),
        "attention_score": max(20.0, 100.0 - score * 0.8),
    }


STATES = [_frame(i) for i in range(30)]


# ------------------------------ reuse ------------------------------------ #
def test_reuse_wired():
    st = reuse_status()
    ck("reuse: analytics package importable", ANALYTICS_AVAILABLE is True)
    ck("reuse: predictor is the shared class", st["predictor"] == "DrowsinessPredictor")
    ck("reuse: timeline is the shared class", st["timeline"] == "TripRiskTimeline")


def test_replay_and_parity():
    res = replay_states(STATES)
    ck("replay: consumed all frames", res["frames"] == len(STATES))
    ck("replay: rising trip -> elevated forecast",
       res["prediction"]["level"] in ("HIGH", "IMMINENT"))
    ck("replay: timeline has points", res["timeline"]["point_count"] > 0)
    ck("replay: timeline peak risk is HIGH", res["timeline"]["peak_risk"] == "HIGH")

    # PARITY: feeding the shared predictor directly must match the replay output
    from config import config as shared_cfg
    ref = DrowsinessPredictor(shared_cfg)
    for s in STATES:
        ref.update(s, now=s["ts"])
    ck("replay: matches a direct run of the shared predictor (no divergence)",
       ref.current() == res["prediction"])


def test_aggregate_stats():
    sessions = [
        {"status": "closed", "final_safety_score": 80, "final_risk_level": "LOW",
         "avg_attention_score": 90, "duration_seconds": 600},
        {"status": "closed", "final_safety_score": 40, "final_risk_level": "HIGH",
         "avg_attention_score": 55, "duration_seconds": 300},
    ]
    agg = aggregate_stats(sessions)
    ck("stats: counts sessions", agg["sessions"] == 2)
    ck("stats: averages safety", agg["avg_safety_score"] == 60.0)
    ck("stats: sums drive time", agg["total_drive_seconds"] == 900.0)
    ck("stats: counts high-risk", agg["high_risk_sessions"] == 1)
    ck("stats: risk distribution", agg["risk_distribution"] == {"LOW": 1, "HIGH": 1})
    ck("stats: empty is safe", aggregate_stats([])["sessions"] == 0)


# --------------------------- full async flow ----------------------------- #
async def _flow():
    repo = InMemoryRepository()
    ck("db: default build is in-memory", build_repository("").backend == "memory")
    ck("db: no-motor mongo URI falls back to memory",
       build_repository("mongodb://nope").backend == "memory")

    s = await service.create_session(repo, "dev-1", started_at=1000.0, meta={"app": "test"})
    sid = s["session_id"]
    ck("flow: session opens", s["status"] == "open" and bool(sid))

    r = await service.ingest_states(repo, sid, STATES)
    ck("flow: states ingested", r["ingested"] == len(STATES))
    ck("flow: server derived a forecast on ingest",
       r["prediction"]["level"] in ("HIGH", "IMMINENT"))

    tl = await service.get_session_timeline(repo, sid)
    ck("flow: timeline retrievable", tl and tl["point_count"] > 0)
    pr = await service.get_session_prediction(repo, sid)
    ck("flow: prediction retrievable", pr and pr["samples"] > 0)

    e = await service.ingest_events(repo, sid, [{"type": "DROWSINESS", "severity": "high"}])
    ck("flow: events ingested", e["ingested"] == 1)

    closed = await service.close_session(repo, sid, summary={
        "final_safety_score": 45, "final_risk_level": "HIGH",
        "avg_attention_score": 60, "duration_seconds": 120})
    ck("flow: session closes with summary",
       closed["status"] == "closed" and closed["summary"]["final_risk_level"] == "HIGH")

    stats = await service.get_stats(repo, "dev-1")
    ck("flow: stats see the closed session", stats["sessions"] == 1)
    ck("flow: stats count the high-risk trip", stats["high_risk_sessions"] == 1)

    missing = await service.ingest_states(repo, "does-not-exist", STATES)
    ck("flow: unknown session -> None (404 upstream)", missing is None)


def test_full_flow():
    asyncio.run(_flow())


# ------------------------------ settings --------------------------------- #
def test_settings_auth_policy():
    saved = {k: os.environ.get(k) for k in ("ENV", "API_KEYS", "REQUIRE_AUTH")}
    try:
        os.environ["ENV"] = "development"
        os.environ.pop("API_KEYS", None)
        os.environ.pop("REQUIRE_AUTH", None)
        ck("settings: dev + no keys -> auth OFF", get_settings().require_auth is False)

        os.environ["API_KEYS"] = "k1,k2"
        s = get_settings()
        ck("settings: keys configured -> auth ON", s.require_auth is True)
        ck("settings: parses key list", len(s.api_keys) == 2)

        os.environ["ENV"] = "production"
        os.environ.pop("API_KEYS", None)
        ck("settings: prod + no keys -> auth ON (fail closed)",
           get_settings().require_auth is True)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    print("=" * 62)
    print(" Cloud service logic: reuse / analytics / flow / settings")
    print("=" * 62)
    test_reuse_wired()
    test_replay_and_parity()
    test_aggregate_stats()
    test_full_flow()
    test_settings_auth_policy()
    print("\n" + ("ALL CLOUD LOGIC CHECKS PASSED"
                  if not _fail else f"{len(_fail)} CHECK(S) FAILED: {_fail}"))
    sys.exit(1 if _fail else 0)
