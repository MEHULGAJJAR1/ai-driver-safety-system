"""Database package: SQLite-backed event logging."""
from .db import (                                   # noqa: F401
    init_db, log_event, get_events, get_stats, clear_events,
)

__all__ = ["init_db", "log_event", "get_events", "get_stats", "clear_events"]
