"""
analytics/event_logger.py
=========================
Structured event logging (Feature 17).

Appends one JSON object per line (JSONL) to ``logs/events-YYYYMMDD.jsonl`` and
can export the whole log as CSV or JSON on demand. This runs *alongside* the
existing SQLite log (which powers the History page); the file log is the
portable, spec-required artifact.

Each record carries:  timestamp, event_type, severity, message, duration,
value, score, source.

PRIVACY: only event *statistics* are written - never raw camera frames.
All disk I/O is wrapped so a read-only / sandboxed filesystem can never crash
the monitoring loop.
"""

import os
import io
import csv
import json
import time
import threading
from datetime import datetime


class EventLogger:
    _CANONICAL = {
        # map internal event types -> spec's canonical names
        "EYE_CLOSURE": "drowsiness_started",
        "DROWSINESS": "drowsiness_started",
        "CRITICAL_DROWSINESS": "critical_alert",
        "DROWSINESS_ENDED": "drowsiness_ended",
        "YAWN": "yawn_detected",
        "SIDE_LOOK_LEFT": "looking_left",
        "SIDE_LOOK_RIGHT": "looking_right",
        "SEVERE_DISTRACTION_LEFT": "attention_alert",
        "SEVERE_DISTRACTION_RIGHT": "attention_alert",
        "ATTENTION_ALERT": "attention_alert",
        "SUNGLASSES": "sunglasses_detected",
        "FACE_COVERED": "face_covered",
        "FACE_NOT_VISIBLE": "face_not_visible",
        "HEAD_NOD": "head_nod",
        "PERCLOS": "perclos_high",
    }

    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(getattr(cfg, "EVENT_LOG_ENABLED", True))
        self.dir = getattr(cfg, "EVENT_LOG_DIR", "logs")
        self._lock = threading.Lock()
        self._count = 0

    # ------------------------------------------------------------------ #
    def _path(self):
        day = datetime.now().strftime("%Y%m%d")
        return os.path.join(self.dir, f"events-{day}.jsonl")

    def canonical(self, event_type):
        return self._CANONICAL.get(event_type, (event_type or "event").lower())

    def log(self, event, extra=None):
        """Append one event dict (``{type, severity, message, ...}``)."""
        if not self.enabled or not event:
            return None
        rec = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ts": round(time.time(), 3),
            "event_type": self.canonical(event.get("type")),
            "raw_type": event.get("type"),
            "severity": event.get("severity", "medium"),
            "message": event.get("message", ""),
            "duration": event.get("duration"),
            "value": event.get("value"),
            "score": (extra or {}).get("score"),
        }
        if extra:
            for k in ("attention_score", "safety_score", "risk_level"):
                if k in extra:
                    rec[k] = extra[k]
        try:
            with self._lock:
                os.makedirs(self.dir, exist_ok=True)
                with open(self._path(), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
                self._count += 1
        except OSError as exc:                                 # pragma: no cover
            # never let a read-only FS kill the capture loop
            print(f"[EventLogger] write skipped: {exc}")
            return None
        return rec

    def log_many(self, events, extra=None):
        for ev in (events or []):
            self.log(ev, extra=extra)

    # ------------------------------------------------------------------ #
    def read_all(self):
        """Return every logged record across all day-files (oldest first)."""
        out = []
        try:
            files = sorted(f for f in os.listdir(self.dir)
                           if f.startswith("events-") and f.endswith(".jsonl"))
        except OSError:
            return out
        for name in files:
            try:
                with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            out.append(json.loads(line))
            except (OSError, ValueError):                       # pragma: no cover
                continue
        return out

    def export(self, fmt="json"):
        """Return (mimetype, text) of the full log in the requested format."""
        records = self.read_all()
        if fmt == "csv":
            cols = ["timestamp", "event_type", "raw_type", "severity",
                    "message", "duration", "value", "score",
                    "attention_score", "safety_score", "risk_level"]
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in records:
                w.writerow(r)
            return "text/csv", buf.getvalue()
        return "application/json", json.dumps(records, indent=2)
