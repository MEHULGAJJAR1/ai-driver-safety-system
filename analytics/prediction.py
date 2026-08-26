"""
analytics/prediction.py
=======================
Predictive Drowsiness (companion-app upgrade).

Where the DrowsinessScorer answers *"is the driver drowsy right now?"*, this
module answers *"how likely is the driver to become drowsy soon, and when?"*.

It is a transparent, explainable forecaster - not a black box:

    * it measures the MOMENTUM (least-squares slope) of the composite
      drowsiness score over a rolling window,
    * blends that with current PERCLOS, the current score and the number of
      recent fatigue episodes (yawns / head-nods / micro-sleeps) into a single
      0-1 probability,
    * projects the score forward to a configurable horizon and estimates an
      ETA to the DROWSY threshold,
    * and returns the human-readable factors behind the number.

Everything is derived from the SAME per-frame ``state`` the rest of the system
already produces, the clock is injectable (``now=``), and there are no heavy
dependencies - so it runs identically inside the Flask app, the FastAPI cloud
service, and the offline unit tests.
"""

from collections import deque

LEVEL_LOW = "LOW"
LEVEL_MODERATE = "MODERATE"
LEVEL_HIGH = "HIGH"
LEVEL_IMMINENT = "IMMINENT"


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


class DrowsinessPredictor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self):
        self._hist = deque()          # (t, score, perclos)
        self._episodes = deque()      # (t, weight)  yawn / nod / micro-sleep
        self._prev_yawn = False
        self._prev_nod = False
        self._prev_micro = False
        self._prob = 0.0
        self._started = None
        self.latest = self._empty()

    def _empty(self):
        return {
            "enabled": bool(getattr(self.cfg, "PREDICT_ENABLED", True)),
            "prob": 0.0,
            "percent": 0,
            "level": LEVEL_LOW,
            "current_score": 0.0,
            "predicted_score": 0.0,
            "trend_slope": 0.0,
            "eta_seconds": None,
            "eta_text": None,
            "horizon_seconds": float(getattr(self.cfg, "PREDICT_HORIZON", 120.0)),
            "confidence": "low",
            "samples": 0,
            "factors": [],
        }

    # ------------------------------------------------------------------ #
    def update(self, state, now=None):
        """Advance one frame with the merged per-frame ``state``. Returns the
        latest prediction dict (also stored on ``self.latest``)."""
        cfg = self.cfg
        if not getattr(cfg, "PREDICT_ENABLED", True):
            self.latest = self._empty()
            return self.latest

        import time as _time
        now = _time.time() if now is None else now
        if self._started is None:
            self._started = now

        score = float(state.get("drowsiness_score", state.get("score", 0.0)) or 0.0)
        perclos = float(state.get("perclos", 0.0) or 0.0)
        yawning = bool(state.get("yawning"))
        nodding = bool(state.get("nodding"))
        micro = bool(state.get("micro_sleep"))
        fatigue_trend = state.get("fatigue_trend")

        self._hist.append((now, score, perclos))

        # rising-edge fatigue episodes (each onset weighted once)
        if yawning and not self._prev_yawn:
            self._episodes.append((now, 1.0))
        if nodding and not self._prev_nod:
            self._episodes.append((now, 1.5))
        if micro and not self._prev_micro:
            self._episodes.append((now, 2.0))
        self._prev_yawn, self._prev_nod, self._prev_micro = yawning, nodding, micro

        # trim both windows
        cutoff = now - cfg.PREDICT_WINDOW
        while self._hist and self._hist[0][0] < cutoff:
            self._hist.popleft()
        while self._episodes and self._episodes[0][0] < cutoff:
            self._episodes.popleft()

        pts = list(self._hist)
        n = len(pts)
        span = (pts[-1][0] - pts[0][0]) if n >= 2 else 0.0
        slope = self._slope(pts)                       # score-points / second
        confident = (n >= cfg.PREDICT_MIN_SAMPLES and
                     span >= cfg.PREDICT_WINDOW * 0.3)

        # ---- probability factors ----------------------------------------
        perclos_alarm = max(float(getattr(cfg, "PERCLOS_ALARM", 0.4)), 1e-6)
        episode_wt = sum(w for (_, w) in self._episodes)
        f_score = _clamp(score / 100.0)
        f_perclos = _clamp(perclos / perclos_alarm)
        f_trend = _clamp(max(slope, 0.0) / max(cfg.PREDICT_SLOPE_REF, 1e-6))
        f_epi = _clamp(episode_wt / max(cfg.PREDICT_EPISODE_REF, 1e-6))

        raw = (cfg.PREDICT_W_SCORE * f_score
               + cfg.PREDICT_W_PERCLOS * f_perclos
               + cfg.PREDICT_W_TREND * f_trend
               + cfg.PREDICT_W_EPISODES * f_epi)
        raw = _clamp(raw)

        # EMA smoothing so the number does not jitter frame-to-frame
        a = _clamp(float(getattr(cfg, "PREDICT_SMOOTHING", 0.25)))
        self._prob += a * (raw - self._prob)
        prob = _clamp(self._prob)

        level = self._level(prob)

        # ---- forecast + ETA ---------------------------------------------
        horizon = float(cfg.PREDICT_HORIZON)
        predicted = _clamp(score + slope * horizon, 0.0, 100.0)
        drowsy_thr = float(getattr(cfg, "DROWSINESS_THRESHOLD", 70.0))
        eta = None
        if score >= drowsy_thr:
            eta = 0.0
        elif slope > 0.05 and confident:
            eta = (drowsy_thr - score) / slope

        factors = self._factors(score, perclos, slope, episode_wt, fatigue_trend,
                                 perclos_alarm)

        self.latest = {
            "enabled": True,
            "prob": round(prob, 3),
            "percent": int(round(prob * 100)),
            "level": level,
            "current_score": round(score, 1),
            "predicted_score": round(predicted, 1),
            "trend_slope": round(slope, 3),
            "eta_seconds": (None if eta is None else int(round(eta))),
            "eta_text": self._eta_text(eta),
            "horizon_seconds": horizon,
            "confidence": "high" if confident else ("medium" if n >= 3 else "low"),
            "samples": n,
            "factors": factors,
        }
        return self.latest

    def current(self):
        return self.latest

    # ------------------------------------------------------------------ #
    @staticmethod
    def _slope(pts):
        """Least-squares slope of score vs. time (points per second)."""
        n = len(pts)
        if n < 2:
            return 0.0
        t0 = pts[0][0]
        xs = [(t - t0) for (t, _s, _p) in pts]
        ys = [s for (_t, s, _p) in pts]
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        if den <= 1e-9:
            return 0.0
        return num / den

    def _level(self, prob):
        cfg = self.cfg
        if prob >= cfg.PREDICT_PROB_IMMINENT:
            return LEVEL_IMMINENT
        if prob >= cfg.PREDICT_PROB_HIGH:
            return LEVEL_HIGH
        if prob >= cfg.PREDICT_PROB_MODERATE:
            return LEVEL_MODERATE
        return LEVEL_LOW

    @staticmethod
    def _eta_text(eta):
        if eta is None:
            return None
        if eta <= 1.0:
            return "now"
        if eta < 90.0:
            return "in ~%d sec" % int(round(eta))
        return "in ~%d min" % int(round(eta / 60.0))

    def _factors(self, score, perclos, slope, episode_wt, fatigue_trend, perclos_alarm):
        out = []
        if perclos >= 0.5 * perclos_alarm:
            out.append("Eyes closed often (PERCLOS %d%%)" % int(round(perclos * 100)))
        if slope >= 0.3:
            out.append("Drowsiness rising (+%.1f/s)" % slope)
        elif fatigue_trend == "INCREASING":
            out.append("Fatigue trend increasing")
        if score >= 0.5 * float(getattr(self.cfg, "DROWSINESS_THRESHOLD", 70.0)):
            out.append("Elevated drowsiness score")
        if episode_wt >= 2.0:
            out.append("Repeated yawns / head-nods")
        return out
