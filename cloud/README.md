# Driver Safety Cloud (FastAPI + MongoDB Atlas)

A **separate, production-shaped** sync & analytics service that runs *alongside*
the existing Flask app and on-device AI pipeline — it does **not** replace any
existing API. The Flask dashboard and its `/api/*` routes keep working exactly
as before; this service adds cross-device trip history and cloud aggregation.

## What it does

| Concern | How |
|---|---|
| **Sync** | Receives trip *sessions*, per-frame *state* batches, and *event* logs from the edge (Flask app / mobile companion). |
| **Analyse** | Replays synced state through the **same** `analytics.DrowsinessPredictor` and `analytics.TripRiskTimeline` classes the edge uses — **zero duplicated logic** (see `cloud/shared.py`). |
| **Serve** | Returns trip history + aggregate safety stats to the mobile app across devices and restarts. |

**Privacy:** only scores / event statistics are accepted and stored — never raw
camera frames. This mirrors the edge-side guarantee.

## Reuse, not reimplementation

`cloud/shared.py` imports the real modules from the project root:

```
from analytics import DrowsinessPredictor, TripRiskTimeline
from config import config
```

`cloud/analytics_runner.py` replays a session's states through those exact
classes, so the cloud's forecast and timeline are computed by the same code as
the edge. The `GET /api/v1/health` response includes a `reuse` block proving the
wiring is live.

## Storage

MongoDB Atlas via **Motor** (async). With **no** `MONGODB_URI` configured, the
service transparently uses an **in-memory** repository — handy for local dev,
demos, and tests. Same async interface either way (`cloud/db.py`).

## Run locally

```bash
cp cloud/.env.example cloud/.env         # fill in as needed (works blank in dev)
pip install -r cloud/requirements.txt
uvicorn cloud.main:app --reload --port 8000     # from the project root
# open http://localhost:8000/docs
```

## API (all under `/api/v1`, JSON)

| Method & path | Purpose | Auth |
|---|---|---|
| `GET  /health` | liveness + storage + reuse status | public |
| `POST /sessions` | open a trip session → returns the session doc | key |
| `GET  /sessions?device_id&limit&skip` | list sessions | key |
| `GET  /sessions/{id}` | one session (summary + prediction + timeline) | key |
| `POST /sessions/{id}/states` | sync per-frame state batch → server re-derives | key |
| `POST /sessions/{id}/events` | sync event batch (stats only) | key |
| `GET  /sessions/{id}/timeline` | trip risk timeline (shared module output) | key |
| `GET  /sessions/{id}/prediction` | drowsiness forecast (shared module output) | key |
| `POST /sessions/{id}/close` | finalize a session (store summary) | key |
| `GET  /stats?device_id` | aggregate safety stats | key |

### Auth

Send `X-API-Key: <key>` where `<key>` is one of the comma-separated `API_KEYS`.
Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Auth is **on by default** and **fails closed** in production; it is only off in
`ENV=development` when no keys are configured.

## Tests (offline, no FastAPI/Mongo needed)

```bash
python cloud/tests/test_cloud_logic.py
```

Exercises the reuse core (`analytics_runner`) and the in-memory repository +
service layer via `asyncio`, proving the cloud reproduces the edge's numbers.

## Docker

```bash
# from the project root (context must be root so shared modules copy in)
docker build -f cloud/Dockerfile -t driver-safety-cloud .
docker run --rm -p 8000:8000 --env-file cloud/.env driver-safety-cloud
```

See the repo-root `docker-compose.yml` and `docs/DEPLOYMENT.md` for the full
stack (Mongo + cloud + Flask behind an HTTPS nginx reverse proxy).
