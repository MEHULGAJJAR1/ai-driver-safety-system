"""
cloud/  -  Cloud sync & analytics service (FastAPI + MongoDB Atlas)
==================================================================
A SEPARATE, production-shaped service that runs ALONGSIDE the existing Flask
app - it never replaces the Flask API or the on-device AI pipeline.

It exists to do three things the edge device shouldn't:

    * SYNC     - receive trip sessions, per-frame state batches and event logs
                 from the edge (the Flask app / the mobile companion),
    * ANALYSE  - re-run the SAME analytics modules the edge uses
                 (analytics.DrowsinessPredictor + analytics.TripRiskTimeline)
                 over the synced stream, so the cloud's forecast and trip
                 timeline are byte-for-byte the same logic - ZERO duplication,
    * SERVE    - hand trip history + aggregate safety stats back to the mobile
                 app across devices and restarts.

Storage is MongoDB Atlas via Motor, with a graceful in-memory fallback so the
service (and its tests) run with no database configured.

PRIVACY: only event statistics / scores are ever accepted or stored - never
raw camera frames. This mirrors the edge-side privacy guarantee.
"""

__all__ = []
