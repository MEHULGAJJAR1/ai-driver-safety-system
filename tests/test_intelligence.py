"""
tests/test_intelligence.py
==========================
Offline, dependency-light verification of the companion-app "intelligence v2"
layer added on top of the safety brain:

    Predictive Drowsiness   analytics/prediction.py  (DrowsinessPredictor)
    Trip Risk Timeline      analytics/timeline.py    (TripRiskTimeline)
    Emergency Contact       notifications/emergency.py (EmergencyContactNotifier)

Runs without a webcam, mediapipe, tensorflow, firebase or any network. Time is
injected (`now=`) so everything is deterministic, and the emergency notifier is
always used WITHOUT a webhook so it logs instead of making a real HTTP call.

    python3 tests/test_intelligence.py      # from the project root
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config as c
from analytics.prediction import DrowsinessPredictor
from analytics.timeline import TripRiskTimeline
from notifications.emergency import EmergencyContactNotifier

_fail = []
def ck(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        _fail.append(name)


def clone_cfg(**over):
    class Cfg(object):
        pass
    cfg = Cfg()
    for k in dir(c):
        if k.isupper():
            setattr(cfg, k, getattr(c, k))
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# ============================ Predictive Drowsiness ======================= #
def pst(score=0.0, perclos=0.0, yawning=False, nodding=False,
        micro_sleep=False, fatigue_trend="STABLE"):
    return {"found": True, "score": score, "perclos": perclos,
            "yawning": yawning, "nodding": nodding, "micro_sleep": micro_sleep,
            "fatigue_trend": fatigue_trend}


def test_predict_rising():
    p = DrowsinessPredictor(c); t = 1000.0; r = None; peak = 0.0
    for i in range(31):                      # 0 -> 90 over 30 s (dt = 1 s)
        r = p.update(pst(score=min(100.0, i * 3.0),
                         perclos=min(0.5, 0.1 + 0.01 * i)), now=t + i)
        peak = max(peak, r["prob"])
    ck("predict: rising drowsiness -> positive slope", r["trend_slope"] > 0)
    ck("predict: rising -> HIGH/IMMINENT level", r["level"] in ("HIGH", "IMMINENT"))
    ck("predict: rising -> prob crosses HIGH band", peak >= c.PREDICT_PROB_HIGH)
    ck("predict: rising -> confident (enough samples/span)", r["confidence"] == "high")
    ck("predict: rising -> ETA is available", r["eta_seconds"] is not None)
    ck("predict: rising -> explains itself (factors)", len(r["factors"]) > 0)


def test_predict_flat_low():
    p = DrowsinessPredictor(c); t = 2000.0; r = None
    for i in range(20):
        r = p.update(pst(score=0.0, perclos=0.0), now=t + i)
    ck("predict: alert driver -> LOW level", r["level"] == "LOW")
    ck("predict: alert driver -> low probability", r["prob"] < c.PREDICT_PROB_MODERATE)
    ck("predict: no upward trend -> no ETA", r["eta_seconds"] is None)


def test_predict_imminent_band():
    # smoothing=1.0 removes EMA lag so we can prove the top band is reachable
    cfg = clone_cfg(PREDICT_SMOOTHING=1.0)
    p = DrowsinessPredictor(cfg); t = 4000.0; r = None
    for i in range(15):
        r = p.update(pst(score=min(100.0, 90.0 + i), perclos=0.6,
                         yawning=(i % 2 == 0)), now=t + i)
    ck("predict: extreme sustained danger -> IMMINENT", r["level"] == "IMMINENT")
    ck("predict: already past threshold -> ETA now (0s)", r["eta_seconds"] == 0)


def test_predict_disabled_and_reset():
    cfg = clone_cfg(PREDICT_ENABLED=False)
    p = DrowsinessPredictor(cfg)
    r = p.update(pst(score=95.0, perclos=0.9), now=5000.0)
    ck("predict: disabled -> reports disabled", r["enabled"] is False)
    ck("predict: disabled -> stays LOW", r["level"] == "LOW")

    p2 = DrowsinessPredictor(c)
    for i in range(20):
        p2.update(pst(score=80.0, perclos=0.5), now=6000.0 + i)
    p2.reset()
    r = p2.current()
    ck("predict: reset clears history", r["samples"] == 0 and r["prob"] == 0.0)


# ============================ Trip Risk Timeline ========================== #
def tst(risk="LOW", safety=100.0, attention=100.0, score=0.0, **flags):
    d = {"risk_level": risk, "safety_score": safety,
         "attention_score": attention, "score": score}
    d.update(flags)
    return d


def test_timeline_segments():
    tl = TripRiskTimeline(c); t = 1000.0
    now = t
    while now <= t + 30.0:
        if now < t + 10.0:
            frame = tst("LOW", 90.0, 95.0, 5.0)
        elif now < t + 20.0:
            frame = tst("MEDIUM", 65.0, 60.0, 55.0)
        else:
            frame = tst("HIGH", 30.0, 30.0, 90.0)
        tl.update(frame, now=now)
        now += 0.5
    s = tl.series(now=t + 30.0)
    ck("timeline: downsampled (~1 sample / 2 s)", 12 <= s["point_count"] <= 18)
    order = [seg["risk"] for seg in s["segments"]]
    ck("timeline: coloured segments in order", order == ["LOW", "MEDIUM", "HIGH"])
    ck("timeline: peak risk captured", s["peak_risk"] == "HIGH")
    ck("timeline: risk distribution sums to ~100",
       abs(sum(s["risk_distribution"].values()) - 100.0) < 1.5)
    p0 = s["points"][0]
    ck("timeline: points carry the expected fields",
       all(k in p0 for k in ("t", "risk", "risk_num", "safety", "attention", "drowsiness")))


def test_timeline_markers():
    tl = TripRiskTimeline(c); t = 2000.0
    tl.update(tst("LOW"), now=t)
    tl.update(tst("HIGH", 20.0, drowsiness_critical=True), now=t + 1)   # rising edge
    tl.update(tst("HIGH", 20.0, drowsiness_critical=True), now=t + 2)   # still true
    tl.update(tst("LOW"), now=t + 3)                                    # falling
    tl.update(tst("LOW", break_recommended=True), now=t + 4)           # break marker
    s = tl.series(now=t + 5)
    mtypes = [m["type"] for m in s["markers"]]
    ck("timeline: critical moment marked once",
       mtypes.count("CRITICAL_DROWSINESS") == 1)
    ck("timeline: break recommendation marked", "BREAK" in mtypes)


def test_timeline_disabled_and_bounded():
    cfg = clone_cfg(TIMELINE_ENABLED=False)
    tl = TripRiskTimeline(cfg)
    tl.update(tst("HIGH", 10.0), now=3000.0)
    s = tl.series(now=3001.0)
    ck("timeline: disabled -> reports disabled", s["enabled"] is False)
    ck("timeline: disabled -> no points", s["point_count"] == 0)

    # bounded memory: many points get decimated under the cap
    cfg2 = clone_cfg(TIMELINE_SAMPLE_INTERVAL=1.0, TIMELINE_MAX_POINTS=10)
    tl2 = TripRiskTimeline(cfg2); t = 3100.0
    for i in range(60):
        tl2.update(tst("MEDIUM", 60.0), now=t + i)
    s = tl2.series(now=t + 60)
    ck("timeline: stays bounded under the cap", 0 < s["point_count"] <= 10)


# ============================ Emergency Contact =========================== #
_CRIT = {"drowsiness_critical": True, "risk_level": "HIGH", "safety_score": 10}
_SAFE = {"drowsiness_critical": False, "risk_level": "LOW", "safety_score": 100}


def test_emergency_disabled_default():
    em = EmergencyContactNotifier(c)
    ck("emergency: disabled by default", em.status()["enabled"] is False)
    fired = False
    for i in range(40):
        if em.evaluate(_CRIT, now=5000.0 + i):
            fired = True
    ck("emergency: disabled -> never fires", not fired)
    ck("emergency: disabled -> nothing recorded", em.status()["sent_count"] == 0)


def test_emergency_sustained_fires_once():
    cfg = clone_cfg(EMERGENCY_CONTACT_ENABLED=True,
                    EMERGENCY_SUSTAIN_SECONDS=5.0,
                    EMERGENCY_CONTACT_COOLDOWN=60.0,
                    EMERGENCY_CONTACT_WEBHOOK="")   # log provider, no network
    em = EmergencyContactNotifier(cfg)
    ck("emergency: no webhook -> not 'configured'", em.configured is False)
    t = 6000.0; fired = []
    for i in range(12):
        if em.evaluate(_CRIT, now=t + i):
            fired.append(t + i)
    ck("emergency: sustained critical fires exactly once", len(fired) == 1)
    ck("emergency: fires only after the sustain window", abs(fired[0] - (t + 5)) < 1.01)


def test_emergency_not_sustained_never_fires():
    cfg = clone_cfg(EMERGENCY_CONTACT_ENABLED=True,
                    EMERGENCY_SUSTAIN_SECONDS=5.0,
                    EMERGENCY_CONTACT_COOLDOWN=60.0)
    em = EmergencyContactNotifier(cfg); t = 7000.0; fired = []
    for i in range(20):
        state = _CRIT if (i % 4) != 3 else _SAFE     # 3 s critical, 1 s clear
        if em.evaluate(state, now=t + i):
            fired.append(i)
    ck("emergency: brief blips never reach the top level", fired == [])


def test_emergency_cooldown_and_test():
    cfg = clone_cfg(EMERGENCY_CONTACT_ENABLED=True,
                    EMERGENCY_SUSTAIN_SECONDS=2.0,
                    EMERGENCY_CONTACT_COOLDOWN=30.0,
                    EMERGENCY_CONTACT_WEBHOOK="")
    em = EmergencyContactNotifier(cfg); t = 8000.0
    first = None
    for i in range(4):
        if em.evaluate(_CRIT, now=t + i):
            first = t + i
    ck("emergency: first alert at the sustain mark", first == t + 2)
    more = []
    for i in range(3, 40):
        if em.evaluate(_CRIT, now=t + i):
            more.append(t + i)
    ck("emergency: cooldown blocks until it elapses", bool(more) and more[0] == t + 32)

    res = em.send_test()
    ck("emergency: test alert succeeds", res["ok"] is True)
    ck("emergency: test reports the emergency provider", res["provider"] == "emergency")


if __name__ == "__main__":
    print("=" * 62)
    print(" Intelligence v2 test-suite: prediction / timeline / emergency")
    print("=" * 62)
    test_predict_rising()
    test_predict_flat_low()
    test_predict_imminent_band()
    test_predict_disabled_and_reset()
    test_timeline_segments()
    test_timeline_markers()
    test_timeline_disabled_and_bounded()
    test_emergency_disabled_default()
    test_emergency_sustained_fires_once()
    test_emergency_not_sustained_never_fires()
    test_emergency_cooldown_and_test()
    print("\n" + ("ALL INTELLIGENCE CHECKS PASSED"
                  if not _fail else f"{len(_fail)} CHECK(S) FAILED: {_fail}"))
    sys.exit(1 if _fail else 0)
