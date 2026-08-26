"""
notifications/manager.py
========================
Decides WHEN to push to the phone and enforces cooldown/debounce so the device
is never spammed. Only *meaningful* events fire a notification:

    * critical drowsiness            (driver falling asleep)
    * face blocked / not visible     (camera obstructed)
    * severe / sustained distraction (eyes off road)
    * safety score critically low
    * top-of-ladder escalation (L4)

At most one notification is dispatched per evaluation (highest priority wins),
each rule has its own cooldown, and delivery happens on a background thread.
"""

import time
import threading
from collections import deque

from .providers import FCMProvider, LogProvider


class NotificationManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(getattr(cfg, "MOBILE_NOTIFICATION_ENABLED", False))
        self.cooldown = float(getattr(cfg, "MOBILE_NOTIFICATION_COOLDOWN", 30.0))
        self._last = {}                 # rule_key -> last send ts
        self.sent = deque(maxlen=100)   # recent notifications (for inspection/UI)
        self._lock = threading.Lock()
        self.provider = self._pick_provider()

    # ------------------------------------------------------------------ #
    def _pick_provider(self):
        """Real FCM if enabled + configured, else the log fallback."""
        if self.enabled:
            fcm = FCMProvider(self.cfg)
            if fcm.configured:
                return fcm
            print(f"[NotificationManager] FCM unavailable ({fcm.reason}); "
                  "using LogProvider.")
        return LogProvider(self.cfg)

    @property
    def configured(self):
        return getattr(self.provider, "configured", False) and self.provider.name == "fcm"

    def status(self):
        return {
            "enabled": self.enabled,
            "provider": self.provider.name,
            "configured": self.configured,
            "cooldown": self.cooldown,
            "sent_count": len(self.sent),
            "last": (self.sent[-1] if self.sent else None),
        }

    # ------------------------------------------------------------------ #
    def _rules(self, state):
        """Ordered (key, title, body) for every condition currently true."""
        cfg = self.cfg
        out = []
        if state.get("drowsiness_critical"):
            out.append(("critical_drowsiness", "🚨 Drowsiness Alert",
                        "Driver appears to be falling asleep. Immediate attention required."))
        if state.get("face_covered") or state.get("face_coverage") in ("covered", "none"):
            out.append(("face_blocked", "📷 Camera Blocked",
                        "The driver's face is not visible to the monitor."))
        if state.get("severe_distraction") or \
                float(state.get("distraction_duration", 0) or 0) >= cfg.CRITICAL_DISTRACTION_DURATION:
            out.append(("severe_distraction", "👀 Distraction Alert",
                        "Driver has not been watching the road."))
        if float(state.get("safety_score", 100) or 100) <= cfg.CRITICAL_SAFETY_SCORE:
            out.append(("low_safety", "⚠️ Safety Warning",
                        "Driver safety score is critically low."))
        if int(state.get("escalation_level", 0) or 0) >= 4 and not out:
            out.append(("escalation", "⚠️ Driver Attention Required",
                        "A driver-monitoring alert has persisted. Please check in."))
        return out

    def evaluate(self, state, now=None):
        """Check rules against the live state; dispatch at most one push.

        Returns the list of rule keys that fired (usually 0 or 1).
        """
        if not self.enabled or not state:
            return []
        now = time.time() if now is None else now
        for key, title, body in self._rules(state):
            if now - self._last.get(key, -1e9) >= self.cooldown:
                self._last[key] = now
                self._dispatch(key, title, body, state, now)
                return [key]      # one push per evaluation - never spam
        return []

    # ------------------------------------------------------------------ #
    def _dispatch(self, key, title, body, state, now, blocking=False):
        token = getattr(self.cfg, "FCM_DEVICE_TOKEN", "")
        data = {
            "reason": key,
            "risk_level": str(state.get("risk_level", "")),
            "safety_score": str(state.get("safety_score", "")),
        }
        record = {"ts": round(now, 3), "time": time.strftime("%H:%M:%S"),
                  "key": key, "title": title, "body": body,
                  "provider": self.provider.name, "ok": None, "detail": "pending"}
        with self._lock:
            self.sent.append(record)

        def _run():
            ok, detail = self.provider.send(token, title, body, data)
            record["ok"], record["detail"] = ok, detail

        if blocking:
            _run()
        else:
            threading.Thread(target=_run, daemon=True).start()
        return record

    # ------------------------------------------------------------------ #
    def send_test(self):
        """Fire a test notification immediately (bypasses rules/cooldown)."""
        now = time.time()
        rec = self._dispatch(
            "test", "🚗 Driver Monitor - Test",
            "Test notification. If you can read this, delivery works.",
            {"risk_level": "TEST", "safety_score": "100"}, now, blocking=True,
        )
        return {
            "ok": bool(rec["ok"]),
            "provider": self.provider.name,
            "configured": self.configured,
            "enabled": self.enabled,
            "detail": rec["detail"],
        }
