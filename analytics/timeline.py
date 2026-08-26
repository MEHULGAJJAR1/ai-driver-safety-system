"""
analytics/timeline.py
=====================
Trip Risk Timeline (companion-app upgrade).

Records a light, downsampled time-series of the driver's risk over a single
trip/session so the dashboard and the mobile app can draw a coloured
"how risky was this drive" timeline (green -> amber -> red) with markers for
the notable moments (critical drowsiness, severe distraction, face blocked,
break recommended).

Design goals:
    * cheap: one sample every ``TIMELINE_SAMPLE_INTERVAL`` seconds, hard-capped
      at ``TIMELINE_MAX_POINTS`` (older points are decimated, never unbounded),
    * portable: pure Python, injectable clock, no camera / numpy needed,
    * privacy-safe: only derived scores + event *labels* are stored, never
      any frame data.

Fed from the same merged per-frame ``state`` used everywhere else, so it is
reused by both the Flask app and the FastAPI cloud service.
"""

from collections import deque

_RISK_NUM = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
# per-frame state keys -> timeline marker labels (notable moments only)
_MARKERS = [
    ("drowsiness_critical", "CRITICAL_DROWSINESS", "Critical drowsiness"),
    ("severe_distraction", "SEVERE_DISTRACTION", "Severe distraction"),
    ("face_covered", "FACE_COVERED", "Face blocked"),
    ("break_recommended", "BREAK", "Break recommended"),
]


class TripRiskTimeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self):
        self._started = None
        self._last_sample = None
        self._interval = float(getattr(self.cfg, "TIMELINE_SAMPLE_INTERVAL", 2.0))
        self._max = int(getattr(self.cfg, "TIMELINE_MAX_POINTS", 900))
        self._points = deque()           # dicts: {t, risk, risk_num, safety, ...}
        self._markers = []               # dicts: {t, type, label}
        self._prev_marker = {}           # rising-edge tracking per marker key
        self._peak = 0                   # peak risk_num seen

    # ------------------------------------------------------------------ #
    def update(self, state, now=None):
        if not getattr(self.cfg, "TIMELINE_ENABLED", True):
            return
        import time as _time
        now = _time.time() if now is None else now
        if self._started is None:
            self._started = now
            self._last_sample = None

        # ---- markers: capture notable moments on their rising edge ------
        for key, mtype, label in _MARKERS:
            cur = bool(state.get(key))
            if cur and not self._prev_marker.get(key):
                self._markers.append({
                    "t": round(now - self._started, 2),
                    "type": mtype,
                    "label": label,
                })
            self._prev_marker[key] = cur

        # ---- downsampled risk/safety/attention series -------------------
        if self._last_sample is not None and (now - self._last_sample) < self._interval:
            return
        self._last_sample = now

        risk = state.get("risk_level", "LOW")
        risk_num = _RISK_NUM.get(risk, 0)
        self._peak = max(self._peak, risk_num)
        self._points.append({
            "t": round(now - self._started, 2),
            "risk": risk,
            "risk_num": risk_num,
            "safety": round(float(state.get("safety_score", 100.0) or 100.0), 1),
            "attention": round(float(state.get("attention_score", 100.0) or 100.0), 1),
            "drowsiness": round(float(state.get("drowsiness_score",
                                               state.get("score", 0.0)) or 0.0), 1),
        })
        self._decimate_if_needed()

    def _decimate_if_needed(self):
        """Keep the series bounded: once we exceed the cap, drop every other
        point and double the effective interval. Cheap and keeps the shape."""
        if len(self._points) <= self._max:
            return
        kept = deque()
        for i, p in enumerate(self._points):
            if i % 2 == 0:
                kept.append(p)
        self._points = kept
        self._interval *= 2.0

    # ------------------------------------------------------------------ #
    def series(self, now=None):
        """Return the full timeline payload for charting."""
        import time as _time
        now = _time.time() if now is None else now
        started = self._started
        duration = 0.0 if started is None else max(0.0, now - started)
        points = list(self._points)

        # collapse consecutive equal-risk points into coloured segments
        segments = []
        for p in points:
            if segments and segments[-1]["risk"] == p["risk"]:
                segments[-1]["end"] = p["t"]
            else:
                if segments:
                    segments[-1]["end"] = p["t"]
                segments.append({"risk": p["risk"], "risk_num": p["risk_num"],
                                 "start": p["t"], "end": p["t"]})
        if segments:
            segments[-1]["end"] = round(duration, 2)

        # % of time in each risk band (by sample count)
        dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
        for p in points:
            dist[p["risk"]] = dist.get(p["risk"], 0) + 1
        total = len(points) or 1
        risk_distribution = {k: round(100.0 * v / total, 1) for k, v in dist.items()}

        peak = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}[self._peak]
        return {
            "enabled": bool(getattr(self.cfg, "TIMELINE_ENABLED", True)),
            "started": started,
            "duration_seconds": round(duration, 1),
            "sample_interval": round(self._interval, 2),
            "point_count": len(points),
            "points": points,
            "segments": segments,
            "markers": list(self._markers),
            "risk_distribution": risk_distribution,
            "peak_risk": peak,
        }
