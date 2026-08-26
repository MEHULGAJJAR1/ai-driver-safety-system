"""
cloud/shared.py
===============
The single place the cloud service reaches back into the EXISTING project to
reuse its intelligence. Nothing here is re-implemented: we import the very same
``analytics.DrowsinessPredictor`` / ``analytics.TripRiskTimeline`` classes and
the shared, env-overridable ``config`` object that the Flask app uses.

Import strategy (works in every layout, no packaging step required):

    1. try a plain ``import analytics`` (works when the repo root is already on
       the path - e.g. the Docker image copies the project root in),
    2. otherwise add the repo root (the parent of this ``cloud/`` folder) to
       ``sys.path`` and try again.

If the analytics package genuinely can't be found we fall back to ``None`` and
expose ``ANALYTICS_AVAILABLE = False`` so the service can still boot and report
its health honestly instead of crashing.
"""

import os
import sys

ANALYTICS_AVAILABLE = False
DrowsinessPredictor = None          # type: ignore
TripRiskTimeline = None             # type: ignore
shared_config = None                # type: ignore
_import_error = ""


def _load():
    global ANALYTICS_AVAILABLE, DrowsinessPredictor, TripRiskTimeline
    global shared_config, _import_error
    try:
        from analytics import DrowsinessPredictor as _Pred, TripRiskTimeline as _Tl
        from config import config as _cfg
    except Exception:                                     # add repo root, retry
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from analytics import DrowsinessPredictor as _Pred, TripRiskTimeline as _Tl
            from config import config as _cfg
        except Exception as exc:                          # pragma: no cover
            _import_error = str(exc)
            return
    DrowsinessPredictor = _Pred
    TripRiskTimeline = _Tl
    shared_config = _cfg
    ANALYTICS_AVAILABLE = True


_load()


def reuse_status():
    """Small dict for the /health probe - proves the reuse wiring is live."""
    return {
        "analytics_available": ANALYTICS_AVAILABLE,
        "predictor": None if DrowsinessPredictor is None else DrowsinessPredictor.__name__,
        "timeline": None if TripRiskTimeline is None else TripRiskTimeline.__name__,
        "import_error": _import_error or None,
    }
