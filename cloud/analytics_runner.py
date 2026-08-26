"""
cloud/analytics_runner.py
=========================
The reuse core - pure, synchronous, no I/O, no FastAPI, no database. Given a
stream of per-frame ``state`` dicts (exactly what the edge already produces and
syncs up), it replays them through the SAME shared analytics classes to derive
the cloud-side forecast and trip risk timeline.

Because it imports nothing heavy and takes an injectable clock via each state's
own timestamp, it is trivially unit-testable offline - which is how we prove
the cloud reproduces the edge's numbers with zero duplicated logic.
"""

from cloud.shared import (
    ANALYTICS_AVAILABLE, DrowsinessPredictor, TripRiskTimeline, shared_config,
)


def _ts(state, fallback):
    for k in ("ts", "t", "timestamp"):
        if state.get(k) is not None:
            try:
                return float(state[k])
            except (TypeError, ValueError):
                pass
    return fallback


def replay_states(states, cfg=None):
    """Replay an ordered list of per-frame states through the shared modules.

    Returns ``{"prediction": {...}, "timeline": {...}, "frames": N}`` using the
    identical ``DrowsinessPredictor`` / ``TripRiskTimeline`` the Flask edge uses.
    Degrades to an honest empty result if the analytics package isn't importable.
    """
    if not ANALYTICS_AVAILABLE:
        return {"prediction": None, "timeline": None, "frames": 0,
                "analytics_available": False}

    cfg = cfg or shared_config
    predictor = DrowsinessPredictor(cfg)
    timeline = TripRiskTimeline(cfg)

    last_t = None
    for i, state in enumerate(states or []):
        if not isinstance(state, dict):
            continue
        t = _ts(state, float(i))          # synthetic 1 Hz clock if unstamped
        last_t = t
        predictor.update(state, now=t)
        timeline.update(state, now=t)

    return {
        "prediction": predictor.current(),
        "timeline": timeline.series(now=last_t),
        "frames": len(states or []),
        "analytics_available": True,
    }


def aggregate_stats(sessions):
    """Aggregate safety stats across finalized sessions (pure function).

    Reads the fields the edge already computes (``final_safety_score``,
    ``final_risk_level``, ``avg_attention_score``, ``duration_seconds``) so
    nothing is recomputed by hand. Those fields may sit at the top level of the
    session doc or nested under its ``summary`` (that's where ``close_session``
    stores the edge summary), so we look in both.
    """
    n = len(sessions or [])
    if n == 0:
        return {"sessions": 0, "avg_safety_score": None, "avg_attention_score": None,
                "total_drive_seconds": 0.0, "risk_distribution": {},
                "high_risk_sessions": 0}

    def _field(s, key):
        v = s.get(key)
        if v is None:
            v = (s.get("summary") or {}).get(key)
        return v

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    safeties = [x for x in (_num(_field(s, "final_safety_score")) for s in sessions) if x is not None]
    attns = [x for x in (_num(_field(s, "avg_attention_score")) for s in sessions) if x is not None]
    total = sum((_num(_field(s, "duration_seconds")) or 0.0) for s in sessions)

    dist = {}
    high = 0
    for s in sessions:
        band = str(_field(s, "final_risk_level") or "UNKNOWN")
        dist[band] = dist.get(band, 0) + 1
        if band == "HIGH":
            high += 1

    return {
        "sessions": n,
        "avg_safety_score": round(sum(safeties) / len(safeties), 1) if safeties else None,
        "avg_attention_score": round(sum(attns) / len(attns), 1) if attns else None,
        "total_drive_seconds": round(total, 1),
        "risk_distribution": dist,
        "high_risk_sessions": high,
    }
