"""Analytics layer for the AI Driver Monitoring & Safety System.

Modules
-------
scoring       : DriverStateMonitor - turns per-frame detections into an
                Attention Score, Safety Score, Risk Level (with hysteresis),
                distraction timer, fatigue trend, attention distribution,
                break recommendation and an end-of-session summary.
prediction    : DrowsinessPredictor - forecasts *imminent* drowsiness (0-1
                probability, level, ETA) from the momentum of the signals.
timeline      : TripRiskTimeline - downsampled per-trip risk/safety series +
                coloured segments and event markers for charting.
event_logger  : EventLogger - append structured events to a JSONL file and
                export them to CSV/JSON. Never stores raw camera frames.
"""

from .scoring import DriverStateMonitor          # noqa: F401
from .prediction import DrowsinessPredictor      # noqa: F401
from .timeline import TripRiskTimeline           # noqa: F401
from .event_logger import EventLogger            # noqa: F401

__all__ = ["DriverStateMonitor", "DrowsinessPredictor",
           "TripRiskTimeline", "EventLogger"]
