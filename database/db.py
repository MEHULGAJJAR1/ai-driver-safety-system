"""
database/db.py
==============
Tiny SQLite wrapper for logging drowsiness events and computing stats for
the history dashboard. A fresh connection is opened per call so it is safe
to use from Flask's multiple request/stream threads.
"""

import os
import sqlite3
from datetime import datetime, timedelta

from config import config

_DB_PATH = config.DATABASE_PATH


def _connect():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the events table if it does not already exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                severity    TEXT    NOT NULL,
                message     TEXT,
                ear         REAL,
                mar         REAL,
                score       REAL,
                source      TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)"
        )


def log_event(event_type, severity="medium", message="", ear=None, mar=None,
              score=None, source="webcam"):
    """Insert one event row. Returns the new row id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO events
               (timestamp, event_type, severity, message, ear, mar, score, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"),
             event_type, severity, message, ear, mar, score, source),
        )
        return cur.lastrowid


def get_events(limit=100, source=None):
    """Return the most recent events (newest first) as a list of dicts."""
    query = "SELECT * FROM events"
    params = []
    if source:
        query += " WHERE source = ?"
        params.append(source)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_stats():
    """Aggregate stats for the dashboard header / history page."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        by_type = {
            r["event_type"]: r["c"]
            for r in conn.execute(
                "SELECT event_type, COUNT(*) AS c FROM events GROUP BY event_type"
            ).fetchall()
        }
        by_sev = {
            r["severity"]: r["c"]
            for r in conn.execute(
                "SELECT severity, COUNT(*) AS c FROM events GROUP BY severity"
            ).fetchall()
        }
        since = (datetime.now() - timedelta(hours=24)).isoformat()
        last_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE timestamp >= ?", (since,)
        ).fetchone()["c"]
        # events per hour for the last 24h (for the history chart)
        rows = conn.execute(
            """SELECT substr(timestamp, 1, 13) AS hour, COUNT(*) AS c
               FROM events WHERE timestamp >= ?
               GROUP BY hour ORDER BY hour""",
            (since,),
        ).fetchall()
        timeline = [{"hour": r["hour"], "count": r["c"]} for r in rows]
    return {
        "total": total,
        "by_type": by_type,
        "by_severity": by_sev,
        "last_24h": last_24h,
        "timeline": timeline,
    }


def clear_events():
    """Delete every event row. Returns number of rows removed."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM events")
        return cur.rowcount
