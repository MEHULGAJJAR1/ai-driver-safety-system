"""
tests/test_monitoring.py
========================
Offline, dependency-light verification of the higher-level AI Driver
Monitoring & Safety System (the "safety brain") layered on top of the
drowsiness core:

    Feature 6/8/9   DriverStateMonitor  - attention & safety scoring, risk
                                          level with hysteresis
    Feature 7       Distraction timer   - continuous look-away + alert
    Feature 15      Fatigue trend       - STABLE / INCREASING / DECREASING
    Feature 14      Attention distribution + Feature 16 session analytics
    Feature 12      Break recommendation
    Feature 10      AlertManager escalation ladder (L1->L4) + distinct sounds
    Feature 18/19   NotificationManager - rules, priority, cooldown/debounce
    Feature 17      EventLogger         - portable JSONL + CSV/JSON export

Runs without a webcam, mediapipe, tensorflow or firebase-admin. Time is
injected (`now=`) so everything is deterministic, and the event logger writes
to a throwaway temp dir so a read-only project tree is never touched.

    python3 tests/test_monitoring.py      # from the project root
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config as c
from analytics.scoring import DriverStateMonitor
from analytics.event_logger import EventLogger
from notifications.manager import NotificationManager
from detection.alerts import AlertManager

_fail = []
def ck(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        _fail.append(name)


def clone_cfg(**over):
    """A throwaway config clone (copies UPPERCASE attrs) with overrides."""
    class Cfg(object):
        pass
    cfg = Cfg()
    for k in dir(c):
        if k.isupper():
            setattr(cfg, k, getattr(c, k))
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# tiny state builders ------------------------------------------------------- #
def fwd(score=0):
    return {"found": True, "face_detected": True, "yaw": 0.0, "pitch": 0.0, "score": score}

def away(yaw=30.0, score=0):
    return {"found": True, "face_detected": True, "yaw": yaw, "pitch": 0.0, "score": score}


# ============================ Feature 6/8: scoring ======================== #
def test_scores_forward():
    m = DriverStateMonitor(c); t = 5000.0; r = None
    for i in range(50):
        r = m.update(fwd(0), now=t + i * 0.1)
    ck("score: forward -> attention stays high", r["attention_score"] >= 90)
    ck("score: forward -> safety stays high", r["safety_score"] >= 90)
    ck("score: forward -> risk LOW", r["risk_level"] == "LOW")
    ck("score: forward -> attention band green", r["attention_band"] == "green")


def test_scores_noface_penalty():
    m = DriverStateMonitor(c); t = 7000.0; r = None
    for i in range(80):
        r = m.update({"found": False, "face_coverage": "none",
                      "yaw": 0.0, "score": 0}, now=t + i * 0.1)
    ck("score: no-face -> attention drops", r["attention_score"] < 60)
    ck("score: face-not-visible -> safety drops below safe band",
       r["safety_score"] < c.RISK_LOW_MIN)
    ck("score: no-face counted in distribution", r["attention_distribution"]["none"] > 0)


# ============================ Feature 7: distraction ====================== #
def test_distraction_timer():
    m = DriverStateMonitor(c); t = 6000.0
    m.update(fwd(0), now=t)                      # warm up looking forward
    r = None; fired = False
    for i in range(1, 45):
        r = m.update(away(30.0), now=t + i * 0.1)
        if r["distraction_alert"]:
            fired = True
            break
    ck("distract: sustained look-away raises alert", fired)
    ck("distract: timer active while away", r["distraction_active"])
    ck("distract: duration past threshold",
       r["distraction_duration"] >= c.DISTRACTION_ALERT_THRESHOLD)

    # look forward again beyond the grace window -> timer clears
    r = m.update(fwd(0), now=t + 10.0)
    ck("distract: forward beyond grace resets timer", not r["distraction_active"])


# ============================ Feature 15: fatigue trend =================== #
def _trend_of(scores, dt=2.0):
    m = DriverStateMonitor(c); t = 8000.0; r = None
    for i, sc in enumerate(scores):
        r = m.update(fwd(sc), now=t + i * dt)
    return r["fatigue_trend"]

def test_fatigue_trend():
    up = _trend_of([i * 4 for i in range(16)])          # 0 -> 60 over 30s
    down = _trend_of([60 - i * 4 for i in range(16)])   # 60 -> 0 over 30s
    flat = _trend_of([30] * 16)
    ck("trend: rising drowsiness -> INCREASING", up == "INCREASING")
    ck("trend: falling drowsiness -> DECREASING", down == "DECREASING")
    ck("trend: steady drowsiness -> STABLE", flat == "STABLE")


# ============================ Feature 9: risk hysteresis ================== #
def test_risk_hysteresis():
    m = DriverStateMonitor(c); t = 9600.0
    bad = {"found": False, "face_coverage": "none", "score": 100,
           "yawning": True, "yaw": 0.0}
    first_high_band = None
    risk_high = None
    for i in range(80):
        tt = t + i * 0.1
        r = m.update(bad, now=tt)
        s = r["safety_score"]
        band = "HIGH" if s < c.RISK_MED_MIN else ("MEDIUM" if s < c.RISK_LOW_MIN else "LOW")
        if band == "HIGH" and first_high_band is None:
            first_high_band = tt
        if r["risk_level"] == "HIGH" and risk_high is None:
            risk_high = tt
    ck("risk: sustained danger eventually reaches HIGH", risk_high is not None)
    ck("risk: HIGH band observed", first_high_band is not None)
    if risk_high is not None and first_high_band is not None:
        delay = risk_high - first_high_band
        ck("risk: hysteresis delays the switch (~RISK_HYSTERESIS)",
           delay >= c.RISK_HYSTERESIS - 0.06 and delay < c.RISK_HYSTERESIS + 0.5)

    # a single bad frame after a clean run must NOT flip risk to HIGH
    m2 = DriverStateMonitor(c); t2 = 9500.0
    for i in range(30):
        m2.update(fwd(0), now=t2 + i * 0.1)
    r = m2.update(bad, now=t2 + 3.1)
    ck("risk: one bad frame can't flip to HIGH (hysteresis + smoothing)",
       r["risk_level"] != "HIGH")


# ============================ Feature 12: break rec ======================= #
def test_break_recommendation():
    m = DriverStateMonitor(c)
    r = m.update({"found": True, "yaw": 0.0, "score": 0,
                  "drowsy_events": c.BREAK_DROWSY_EVENTS}, now=9000.0)
    ck("break: enough drowsy episodes -> recommend break", r["break_recommended"])
    ck("break: recommendation carries text", bool(r["break_text"]))

    m2 = DriverStateMonitor(c)
    r = m2.update({"found": True, "yaw": 0.0, "score": 0,
                   "yawn_count": c.BREAK_YAWN_COUNT}, now=9100.0)
    ck("break: enough yawns -> recommend break", r["break_recommended"])

    m3 = DriverStateMonitor(c)
    r = m3.update(fwd(0), now=9200.0)
    ck("break: fresh alert driver -> no break", not r["break_recommended"])


# ============================ Feature 14/16: session ====================== #
def test_session_summary():
    m = DriverStateMonitor(c); t = 9700.0
    for i in range(30):
        st = fwd(10) if i < 15 else away(30.0, 10)
        m.update(st, now=t + i * 0.2)
    s = m.session_summary(now=t + 6.0)
    for key in ("duration_seconds", "duration_hms", "avg_attention_score",
                "final_safety_score", "final_risk_level", "attention_distribution",
                "total_distraction_time", "right_look_events"):
        ck("session: summary has '%s'" % key, key in s)
    ck("session: duration is positive", s["duration_seconds"] > 0)
    ck("session: final risk is a valid band",
       s["final_risk_level"] in ("LOW", "MEDIUM", "HIGH"))
    ck("session: avg attention in range", 0.0 <= s["avg_attention_score"] <= 100.0)

    dist = s["attention_distribution"]
    ck("dist: forward time recorded", dist["forward"] > 0)
    ck("dist: side (right) time recorded", dist["right"] > 0)
    ck("dist: distribution sums to ~100", abs(sum(dist.values()) - 100.0) < 1.5)


# ============================ Feature 10: escalation ====================== #
_SG_OFF = {"detected": False, "confidence": 0.0}

def _m(found=True):
    return {"found": found}

def _st(level="ALERT", yaw=0.0, score=10, **extra):
    d = {"level": level, "yaw": yaw, "score": score}
    d.update(extra)
    return d

def test_escalation_ladder():
    am = AlertManager(c); t0 = 1000.0

    def drowsy():
        return _st("DROWSY", 0.0, 85, eye_closed_frames=0)

    # onset: audible immediately (L2) but NOT critical, ordinary drowsiness sound
    r = am.update(_m(True), drowsy(), _SG_OFF, now=t0)
    ck("esc: drowsy onset -> DROWSINESS", r["alert_type"] == "DROWSINESS")
    ck("esc: drowsy onset audible at L2", r["escalation_level"] == 2)
    ck("esc: drowsy onset uses drowsiness sound",
       r["alert_sound"] == c.DROWSINESS_ALARM_FILE)
    ck("esc: drowsy speaks the drowsy voice line", r["voice_key"] == "drowsy")

    # still ordinary before the critical-duration mark
    r = am.update(_m(True), drowsy(), _SG_OFF, now=t0 + 2.0)
    ck("esc: pre-2.5s stays ordinary DROWSINESS",
       r["alert_type"] == "DROWSINESS" and r["escalation_level"] == 2)

    # sustained -> CRITICAL_DROWSINESS with the louder critical sound (L3)
    r = am.update(_m(True), drowsy(), _SG_OFF, now=t0 + 2.6)
    ck("esc: sustained drowsy -> CRITICAL_DROWSINESS",
       r["alert_type"] == "CRITICAL_DROWSINESS")
    ck("esc: critical is at least L3", r["escalation_level"] >= 3)
    ck("esc: critical uses the critical sound",
       r["alert_sound"] == c.CRITICAL_ALARM_FILE)

    # persists to the top of the ladder -> L4 (mobile-push candidate)
    r = None; reached_l4 = False
    for i in range(1, 60):
        r = am.update(_m(True), drowsy(), _SG_OFF, now=t0 + 2.6 + i * 0.2)
        if r["escalation_level"] >= 4:
            reached_l4 = True
            break
    ck("esc: long alert climbs to L4", reached_l4 and r["notify_ready"])


def test_distinct_sounds_and_severe():
    # sustained side-look -> SEVERE_DISTRACTION on the *side* sound (never the
    # drowsiness or critical sound) - proves "drowsiness != side" is preserved.
    am = AlertManager(c); t0 = 2000.0; r = None; severe = False
    for i in range(70):
        r = am.update(_m(True), _st("ALERT", 30.0), _SG_OFF, now=t0 + i * 0.2)
        if r["alert_type"] in ("SEVERE_DISTRACTION_LEFT", "SEVERE_DISTRACTION_RIGHT"):
            severe = True
            break
    ck("severe: sustained side-look -> SEVERE_DISTRACTION", severe)
    ck("severe: uses the side-look sound", r["alert_sound"] == c.SIDE_LOOK_ALARM_FILE)
    ck("severe: is escalated (>=L3)", r["escalation_level"] >= 3)
    ck("severe: NOT the drowsiness/critical sound",
       r["alert_sound"] not in (c.DROWSINESS_ALARM_FILE, c.CRITICAL_ALARM_FILE))

    # the four alarm files are all distinct (one sound per meaning)
    files = [c.DROWSINESS_ALARM_FILE, c.SIDE_LOOK_ALARM_FILE,
             c.FACE_COVERED_ALARM_FILE, c.CRITICAL_ALARM_FILE]
    ck("sounds: four distinct alarm files", len(set(files)) == 4)


# ============================ Feature 18/19: notify ======================= #
# a state that trips ONLY the critical-drowsiness rule (high safety score so the
# independent low-safety rule stays silent) - keeps the cooldown test unambiguous
_CRIT = {"drowsiness_critical": True, "risk_level": "HIGH", "safety_score": 100}

def test_notifications():
    # disabled by default -> nothing fires, even on a critical state
    nm = NotificationManager(c)
    ck("notify: disabled by default", nm.status()["enabled"] is False)
    ck("notify: disabled -> no push", nm.evaluate(_CRIT, now=1000.0) == [])

    # enabled (no real FCM creds) -> falls back to the always-on log provider
    cfg = clone_cfg(MOBILE_NOTIFICATION_ENABLED=True,
                    MOBILE_NOTIFICATION_COOLDOWN=30.0,
                    FCM_DEVICE_TOKEN="")
    nm = NotificationManager(cfg)
    ck("notify: graceful fallback to log provider", nm.provider.name == "log")
    ck("notify: log provider is not 'configured' FCM", nm.configured is False)

    # one push per evaluation even when several rules are true (priority wins)
    both = {"drowsiness_critical": True, "face_covered": True,
            "risk_level": "HIGH", "safety_score": 20}
    fired = nm.evaluate(both, now=2000.0)
    ck("notify: at most one push per evaluation", len(fired) == 1)
    ck("notify: highest-priority rule wins", fired == ["critical_drowsiness"])

    # cooldown/debounce: same rule can't fire again immediately
    nm2 = NotificationManager(cfg)
    ck("notify: first critical fires",
       nm2.evaluate(_CRIT, now=3000.0) == ["critical_drowsiness"])
    ck("notify: within cooldown -> suppressed",
       nm2.evaluate(_CRIT, now=3005.0) == [])
    ck("notify: after cooldown -> fires again",
       nm2.evaluate(_CRIT, now=3000.0 + cfg.MOBILE_NOTIFICATION_COOLDOWN + 1) == ["critical_drowsiness"])

    # rule ordering when critical drowsiness is absent
    nm3 = NotificationManager(cfg)
    face_and_distract = {"face_covered": True, "severe_distraction": True,
                         "safety_score": 100}
    ck("notify: face-blocked outranks distraction",
       nm3.evaluate(face_and_distract, now=4000.0) == ["face_blocked"])

    # the test button always works (bypasses rules/cooldown)
    res = nm.send_test()
    ck("notify: test notification succeeds", res["ok"] is True)
    ck("notify: test reports the provider", res["provider"] == "log")


# ============================ Feature 17: event log ======================= #
def test_event_logger():
    tmp = tempfile.mkdtemp(prefix="drowsy_log_")
    try:
        cfg = clone_cfg(EVENT_LOG_ENABLED=True, EVENT_LOG_DIR=tmp)
        el = EventLogger(cfg)
        events = [
            {"type": "CRITICAL_DROWSINESS", "severity": "high", "message": "critical"},
            {"type": "SIDE_LOOK_RIGHT", "severity": "medium", "message": "looking right"},
            {"type": "FACE_COVERED", "severity": "high", "message": "covered"},
        ]
        el.log_many(events, extra={"attention_score": 42, "safety_score": 30,
                                   "risk_level": "HIGH", "score": 88})
        recs = el.read_all()
        ck("log: all events written & read back", len(recs) == 3)
        ck("log: canonical mapping applied (critical_alert)",
           recs[0]["event_type"] == "critical_alert")
        ck("log: canonical mapping applied (looking_right)",
           recs[1]["event_type"] == "looking_right")
        ck("log: extra fields captured", recs[0].get("safety_score") == 30
           and recs[0].get("risk_level") == "HIGH")
        ck("log: raw type preserved", recs[0]["raw_type"] == "CRITICAL_DROWSINESS")

        mime, text = el.export("csv")
        ck("log: CSV export mimetype", mime == "text/csv")
        ck("log: CSV has a header + rows",
           text.splitlines()[0].startswith("timestamp,event_type") and len(text.splitlines()) == 4)

        mime, text = el.export("json")
        ck("log: JSON export mimetype", mime == "application/json")
        import json as _json
        ck("log: JSON export parses to 3 records", len(_json.loads(text)) == 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 62)
    print(" Monitoring test-suite: scoring / risk / escalation / notify / log")
    print("=" * 62)
    test_scores_forward()
    test_scores_noface_penalty()
    test_distraction_timer()
    test_fatigue_trend()
    test_risk_hysteresis()
    test_break_recommendation()
    test_session_summary()
    test_escalation_ladder()
    test_distinct_sounds_and_severe()
    test_notifications()
    test_event_logger()
    print("\n" + ("ALL MONITORING CHECKS PASSED"
                  if not _fail else f"{len(_fail)} CHECK(S) FAILED: {_fail}"))
    sys.exit(1 if _fail else 0)
