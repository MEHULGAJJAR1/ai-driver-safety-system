"""
notifications/emergency.py
==========================
Optional Emergency Contact escalation (companion-app upgrade).

This is the *top* of the alert ladder and is deliberately conservative:

    * DISABLED by default (opt-in via EMERGENCY_CONTACT_ENABLED),
    * only fires when a critical situation (driver falling asleep, HIGH risk,
      or a critically low safety score) has been SUSTAINED continuously for
      ``EMERGENCY_SUSTAIN_SECONDS`` - so it never jumps straight to the top on
      a momentary blip,
    * has its own long cooldown (``EMERGENCY_CONTACT_COOLDOWN``) so the contact
      is never spammed,
    * dispatches on a background thread and can never crash the capture loop.

It runs ALONGSIDE the existing NotificationManager (phone push) rather than
replacing it, so nothing about the current push behaviour changes.
"""

import time
import threading
from collections import deque

from .providers import EmergencyContactProvider


class EmergencyContactNotifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(getattr(cfg, "EMERGENCY_CONTACT_ENABLED", False))
        self.sustain = float(getattr(cfg, "EMERGENCY_SUSTAIN_SECONDS", 10.0))
        self.cooldown = float(getattr(cfg, "EMERGENCY_CONTACT_COOLDOWN", 120.0))
        self.provider = EmergencyContactProvider(cfg)
        self.sent = deque(maxlen=50)
        self._lock = threading.Lock()
        self._critical_since = None
        self._last_sent = -1e9

    # ------------------------------------------------------------------ #
    def reset(self):
        self._critical_since = None
        self._last_sent = -1e9

    def _is_critical(self, state):
        cfg = self.cfg
        if state.get("drowsiness_critical"):
            return True
        if state.get("risk_level") == "HIGH":
            return True
        safety = state.get("safety_score")
        if safety is not None and float(safety) <= cfg.CRITICAL_SAFETY_SCORE:
            return True
        return False

    @property
    def configured(self):
        return getattr(self.provider, "configured", False)

    def status(self):
        return {
            "enabled": self.enabled,
            "configured": self.configured,          # True only if a webhook is set
            "contact_name": getattr(self.cfg, "EMERGENCY_CONTACT_NAME", ""),
            "has_webhook": bool(getattr(self.cfg, "EMERGENCY_CONTACT_WEBHOOK", "")),
            "sustain_seconds": self.sustain,
            "cooldown": self.cooldown,
            "sent_count": len(self.sent),
            "last": (self.sent[-1] if self.sent else None),
        }

    # ------------------------------------------------------------------ #
    def evaluate(self, state, now=None):
        """Advance one frame. Returns the dispatched record dict, or None.

        Fires at most once per cooldown and only after a sustained critical
        situation. Safe to call every frame.
        """
        if not self.enabled or not state:
            self._critical_since = None
            return None
        now = time.time() if now is None else now

        if self._is_critical(state):
            if self._critical_since is None:
                self._critical_since = now
            held = now - self._critical_since
            if held >= self.sustain and (now - self._last_sent) >= self.cooldown:
                self._last_sent = now
                return self._dispatch(state, now, held)
        else:
            self._critical_since = None
        return None

    # ------------------------------------------------------------------ #
    def _dispatch(self, state, now, held, blocking=False):
        name = getattr(self.cfg, "EMERGENCY_CONTACT_NAME", "") or "your emergency contact"
        title = "🚨 Driver Emergency Alert"
        body = ("A driver-monitoring alert has stayed critical for "
                f"{int(round(held))}s. Contacting {name}.")
        data = {
            "reason": "sustained_critical",
            "risk_level": str(state.get("risk_level", "")),
            "safety_score": str(state.get("safety_score", "")),
            "held_seconds": int(round(held)),
        }
        record = {"ts": round(now, 3), "time": time.strftime("%H:%M:%S"),
                  "title": title, "body": body, "provider": self.provider.name,
                  "ok": None, "detail": "pending"}
        with self._lock:
            self.sent.append(record)

        def _run():
            ok, detail = self.provider.send(title, body, data)
            record["ok"], record["detail"] = ok, detail

        if blocking:
            _run()
        else:
            threading.Thread(target=_run, daemon=True).start()
        return record

    # ------------------------------------------------------------------ #
    def send_test(self):
        """Fire a test emergency alert immediately (bypasses gate + cooldown)."""
        now = time.time()
        name = getattr(self.cfg, "EMERGENCY_CONTACT_NAME", "") or "your emergency contact"
        title = "🚗 Emergency Contact - Test"
        body = f"Test alert. If {name} receives this, emergency escalation works."
        record = {"ts": round(now, 3), "time": time.strftime("%H:%M:%S"),
                  "title": title, "body": body, "provider": self.provider.name,
                  "ok": None, "detail": "pending"}
        with self._lock:
            self.sent.append(record)
        ok, detail = self.provider.send(title, body, {"reason": "test"})
        record["ok"], record["detail"] = ok, detail
        return {
            "ok": bool(ok),
            "provider": self.provider.name,
            "configured": self.configured,
            "enabled": self.enabled,
            "detail": detail,
        }
