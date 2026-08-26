"""
tests/test_features.py
======================
Offline, dependency-light verification of the FOUR real-time monitoring
features added on top of the drowsiness core:

    Feature 1  Drowsiness alarm      (via AlertManager priority + single sound)
    Feature 2  Side-way looking      (SideLookDetector: yaw + duration debounce)
    Feature 3  Sunglasses detection  (SunglassesDetector: dark + smooth cue)
    Feature 4  Face coverage         (FaceCoverageDetector: 4-state machine)

Runs without a webcam, without mediapipe and without tensorflow - it feeds
synthetic metrics / frames and an injectable clock, so timing is deterministic.

    python3 tests/test_features.py      # from the project root
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from config import config as c
from detection.alerts import SideLookDetector, FaceCoverageDetector, AlertManager
from detection.sunglasses import SunglassesDetector

_fail = []
def ck(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        _fail.append(name)


# ============================ Feature 2: side-look ======================== #
def test_side_look():
    s = SideLookDetector(c)
    # forward -> nothing
    a, sl, d = s.update(True, 0.0, 100.0)
    ck("side: forward -> no alert", a == "forward" and not sl)
    # small natural movement below threshold -> nothing
    a, sl, d = s.update(True, c.SIDE_YAW_THRESHOLD - 5, 100.1)
    ck("side: small yaw ignored", not sl)

    # sustained LEFT (negative yaw) past the duration
    s = SideLookDetector(c); base = 200.0; res = None
    for i in range(25):
        res = s.update(True, -30.0, base + i * 0.2)
    a, sl, d = res
    ck("side: sustained left -> confirmed", sl and d == "left" and a == "left")

    # sustained RIGHT (positive yaw)
    s = SideLookDetector(c); base = 300.0; res = None; last_t = base
    for i in range(25):
        last_t = base + i * 0.2
        res = s.update(True, 30.0, last_t)
    ck("side: sustained right -> confirmed", res[1] and res[2] == "right")

    # a brief forward glance inside the grace window keeps the alert
    a, sl, d = s.update(True, 0.0, last_t + c.SIDE_LOOK_EXIT_GRACE * 0.5)
    ck("side: brief glance within grace keeps alert", sl)
    # a longer forward period clears it
    a, sl, d = s.update(True, 0.0, last_t + c.SIDE_LOOK_EXIT_GRACE + 1.0)
    ck("side: sustained forward resets", not sl and a == "forward")

    # short side-look under the duration must NOT alert (debounce)
    s = SideLookDetector(c); base = 400.0; res = None
    for i in range(3):
        res = s.update(True, 30.0, base + i * 0.1)   # only ~0.3s
    ck("side: short glance under duration -> no alert", not res[1])

    # losing the face resets everything
    s = SideLookDetector(c)
    for i in range(25):
        s.update(True, 30.0, 500 + i * 0.2)
    a, sl, d = s.update(False, 0.0, 600)
    ck("side: no face resets", a == "no_face" and not sl)


def test_side_look_invert():
    # a tiny throwaway cfg clone with invert on
    class Cfg(object): pass
    cfg = Cfg()
    for k in dir(c):
        if k.isupper():
            setattr(cfg, k, getattr(c, k))
    cfg.SIDE_LOOK_INVERT = True
    s = SideLookDetector(cfg); base = 100.0; res = None
    for i in range(25):
        res = s.update(True, 30.0, base + i * 0.2)   # positive yaw
    ck("side: INVERT flips right->left", res[1] and res[2] == "left")


# ============================ Feature 4: coverage ========================= #
def test_face_coverage():
    f = FaceCoverageDetector(c); tb = 500.0
    cov = None
    for i in range(40):
        cov, al, k = f.update(True, tb + i * 0.05)
    ck("cover: steady face -> clear", cov == "clear" and not al)

    # one dropped frame right after -> partial, NOT an alarm
    cov, al, k = f.update(False, tb + 2.05)
    ck("cover: single missed frame -> no alarm", cov == "partial" and not al)

    # sustained loss (face was recently here) -> covered after timeout
    cov, al, k = f.update(False, tb + 2.05 + c.FACE_COVERED_TIMEOUT + 0.5)
    ck("cover: sustained block -> COVERED", cov == "covered" and al and k == "FACE_COVERED")

    # recovery clears the alarm
    cov, al, k = f.update(True, tb + 12.0)
    ck("cover: recovery clears alarm", (not al) and cov in ("clear", "partial"))

    # never-seen camera -> 'none' (no face) after the missing timeout
    f2 = FaceCoverageDetector(c)
    f2.update(False, 0.0)
    cov, al, k = f2.update(False, c.FACE_MISSING_TIMEOUT + 0.3)
    ck("cover: never-seen -> NOT VISIBLE", cov == "none" and al and k == "FACE_NOT_VISIBLE")


# ============================ Feature 3: sunglasses ======================= #
def _synthetic(eye_fill, eye_noise, skin_fill=185):
    """Build a (frame, metrics) pair: skin everywhere, eyes overwritten."""
    h, w = 480, 640
    rng = np.random.default_rng(0)
    frame = np.clip(skin_fill + rng.normal(0, 8, (h, w, 3)), 0, 255).astype(np.uint8)
    left = [(240, 202), (255, 190), (285, 190), (300, 202), (285, 214), (255, 214)]
    right = [(380, 202), (395, 190), (425, 190), (440, 202), (425, 214), (395, 214)]
    for pts in (left, right):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x1, x2, y1, y2 = min(xs) - 4, max(xs) + 4, min(ys) - 4, max(ys) + 4
        patch = np.clip(eye_fill + rng.normal(0, eye_noise, (y2 - y1, x2 - x1, 3)), 0, 255)
        frame[y1:y2, x1:x2] = patch.astype(np.uint8)
    metrics = {"found": True, "left_eye_pts": left, "right_eye_pts": right}
    return frame, metrics


def test_sunglasses():
    # (A) bare OPEN eye: brightness close to skin + strong texture -> no
    det = SunglassesDetector(c)
    fr, mt = _synthetic(eye_fill=135, eye_noise=45)
    r = None
    for _ in range(c.SUNGLASSES_MIN_FRAMES + 4):
        r = det.analyze(fr, mt)
    ck("glasses: bright textured eye -> NOT detected", not r["detected"])

    # (B) dark, smooth lens -> detected after debounce
    det = SunglassesDetector(c)
    fr, mt = _synthetic(eye_fill=35, eye_noise=4)
    r = None
    for _ in range(c.SUNGLASSES_MIN_FRAMES + 4):
        r = det.analyze(fr, mt)
    ck("glasses: dark smooth lens -> DETECTED", r["detected"] and r["confidence"] >= c.SUNGLASSES_CONFIDENCE)

    # (C) CLOSED eye (skin-toned, mild crease texture) -> NOT detected
    det = SunglassesDetector(c)
    fr, mt = _synthetic(eye_fill=150, eye_noise=22)
    r = None
    for _ in range(c.SUNGLASSES_MIN_FRAMES + 4):
        r = det.analyze(fr, mt)
    ck("glasses: closed eye NOT flagged as sunglasses", not r["detected"])

    # (D) no face -> gracefully decays, no crash
    r = det.analyze(fr, {"found": False})
    ck("glasses: no-face handled", "detected" in r)


# ============================ AlertManager priority ======================= #
def _m(found=True):
    return {"found": found}

def _st(level="ALERT", yaw=0.0, score=10, **extra):
    d = {"level": level, "yaw": yaw, "score": score}
    d.update(extra)
    return d

_SG_OFF = {"detected": False, "confidence": 0.0}
_SG_ON = {"detected": True, "confidence": 0.9}

# every mapped audible alert -> its own single audio file (Feature 21)
_SOUND = {
    "DROWSINESS": c.DROWSINESS_ALARM_FILE,
    "CRITICAL_DROWSINESS": c.CRITICAL_ALARM_FILE,
    "SIDE_LOOK_LEFT": c.SIDE_LOOK_ALARM_FILE,
    "SIDE_LOOK_RIGHT": c.SIDE_LOOK_ALARM_FILE,
    "SEVERE_DISTRACTION_LEFT": c.SIDE_LOOK_ALARM_FILE,
    "SEVERE_DISTRACTION_RIGHT": c.SIDE_LOOK_ALARM_FILE,
    "FACE_COVERED": c.FACE_COVERED_ALARM_FILE,
    "FACE_NOT_VISIBLE": c.FACE_COVERED_ALARM_FILE,
}

def test_alert_manager():
    # ---- side-look alone (confirmed, but short of "severe") --------------
    am = AlertManager(c); tb = 600.0; r = None
    for i in range(25):                              # up to tb+4.8 (< severe onset)
        r = am.update(_m(), _st("ALERT", 30.0), _SG_OFF, now=tb + i * 0.2)
    ck("mgr: side-look active alone", r["alert_type"] == "SIDE_LOOK_RIGHT")
    ck("mgr: side-look sound is side file", r["alert_sound"] == c.SIDE_LOOK_ALARM_FILE)
    ck("mgr: side-look not yet severe", not r["severe_distraction"])

    # ---- Feature 21 priority: DROWSINESS (4) > ordinary SIDE_LOOK (5) ----
    am = AlertManager(c); tb = 1600.0; r = None
    for i in range(10):                              # confirm side-look (~1.8s)
        r = am.update(_m(), _st("ALERT", 30.0), _SG_OFF, now=tb + i * 0.2)
    ck("mgr: side-look confirmed pre-drowsy",
       r["alert_type"] == "SIDE_LOOK_RIGHT" and not r["severe_distraction"])
    r = am.update(_m(), _st("DROWSY", 30.0, eye_closed_frames=0), _SG_OFF, now=tb + 2.0)
    ck("mgr: ordinary drowsiness > ordinary side-look", r["alert_type"] == "DROWSINESS")
    ck("mgr: drowsiness sound", r["alert_sound"] == c.DROWSINESS_ALARM_FILE)

    # ---- priority: SEVERE_DISTRACTION (3) > ordinary DROWSINESS (4) ------
    am = AlertManager(c); tb = 1700.0; r = None
    for i in range(30):                              # side-look to severe (~5.8s)
        r = am.update(_m(), _st("ALERT", 30.0), _SG_OFF, now=tb + i * 0.2)
    ck("mgr: sustained side-look becomes severe",
       r["severe_distraction"] and r["alert_type"] == "SEVERE_DISTRACTION_RIGHT")
    # same instant the driver also looks drowsy (fresh -> not yet critical)
    r = am.update(_m(), _st("DROWSY", 30.0, eye_closed_frames=0), _SG_OFF, now=tb + 6.0)
    ck("mgr: severe distraction > ordinary drowsiness",
       r["alert_type"] == "SEVERE_DISTRACTION_RIGHT")
    ck("mgr: severe distraction keeps the side sound",
       r["alert_sound"] == c.SIDE_LOOK_ALARM_FILE)

    # ---- priority: FACE_COVERED (2) > ordinary DROWSINESS (4) -----------
    am2 = AlertManager(c); tb = 1800.0
    for i in range(40):                              # clear face first (~2s)
        am2.update(_m(True), _st("ALERT", 0.0), _SG_OFF, now=tb + i * 0.05)
    r = None
    for i in range(40):                              # face lost + freshly drowsy
        r = am2.update(_m(False), _st("DROWSY", 0.0, eye_closed_frames=0),
                       _SG_OFF, now=tb + 2.0 + i * 0.05)
        if r["alert_type"] == "FACE_COVERED":
            break
    ck("mgr: face-covered > ordinary drowsiness", r["alert_type"] == "FACE_COVERED")
    ck("mgr: face-covered sound", r["alert_sound"] == c.FACE_COVERED_ALARM_FILE)

    # ---- priority: CRITICAL_DROWSINESS (1) is top, even over a blocked face
    am5 = AlertManager(c); tb = 1900.0
    for i in range(40):                              # clear face first
        am5.update(_m(True), _st("ALERT", 0.0), _SG_OFF, now=tb + i * 0.05)
    r = None
    for i in range(140):                             # long drowsiness + face lost
        r = am5.update(_m(False), _st("DROWSY", 0.0, eye_closed_frames=0),
                       _SG_OFF, now=tb + 2.0 + i * 0.05)
    ck("mgr: critical drowsiness is top priority",
       r["alert_type"] == "CRITICAL_DROWSINESS")
    ck("mgr: critical uses the critical sound", r["alert_sound"] == c.CRITICAL_ALARM_FILE)

    # exactly ONE sound is ever active (single string, never a list)
    ck("mgr: single active sound",
       isinstance(r["alert_sound"], str) and r["alert_sound"].endswith(".wav"))
    ck("mgr: sound matches type", r["alert_sound"] == _SOUND[r["alert_type"]])

    # sunglasses is status-only: no alert_type, no sound
    am3 = AlertManager(c)
    r = am3.update(_m(True), _st("ALERT"), _SG_ON, now=800)
    ck("mgr: sunglasses status-only (no sound)",
       r["sunglasses_detected"] and r["alert_type"] is None and r["alert_sound"] is None)

    # transitions emit exactly one ALERT_START event on change
    am4 = AlertManager(c); tb = 900.0
    ev_starts = 0
    for i in range(25):
        r = am4.update(_m(), _st("ALERT", 30.0), _SG_OFF, now=tb + i * 0.2)
        ev_starts += sum(1 for e in r["events"] if e["type"] == "SIDE_LOOK_RIGHT")
    ck("mgr: one start event per episode", ev_starts == 1)

    # reset clears active alert
    am4.reset()
    r = am4.update(_m(), _st("ALERT", 0.0), _SG_OFF, now=tb + 100)
    ck("mgr: reset clears alert", r["alert_type"] is None and not r["alert_active"])


if __name__ == "__main__":
    print("=" * 62)
    print(" Feature test-suite: side-look / coverage / sunglasses / alerts")
    print("=" * 62)
    test_side_look()
    test_side_look_invert()
    test_face_coverage()
    test_sunglasses()
    test_alert_manager()
    print("\n" + ("ALL FEATURE CHECKS PASSED"
                  if not _fail else f"{len(_fail)} CHECK(S) FAILED: {_fail}"))
    sys.exit(1 if _fail else 0)
