"""
app.py
======
Flask application for the Driver Drowsiness Detection Dashboard.

Routes
------
GET  /                     dashboard (live webcam)
GET  /upload               upload a video/image for offline analysis
GET  /history              event history + charts
GET  /video_feed           MJPEG stream of the annotated webcam
GET  /api/state            latest live drowsiness state (JSON, polled by UI)
POST /api/camera/<action>  start | stop | reset the webcam pipeline
POST /api/analyze          analyze an uploaded file, returns summary JSON
GET  /api/events           recent logged events
GET  /api/stats            aggregate statistics
POST /api/events/clear     wipe the event log
GET  /api/session/summary  end-of-session analytics (summary modal)
GET  /api/predict          predictive-drowsiness forecast (prob / level / ETA)
GET  /api/timeline         trip risk timeline (downsampled series + markers)
GET  /api/notify/status    mobile-push provider status
POST /api/notify/test      send a test push notification
GET  /api/emergency/status optional emergency-contact escalation status
POST /api/emergency/test   send a test emergency-contact alert
GET  /api/events/export    download event log (?fmt=csv|json)
GET  /api/health           liveness/health probe

Run:  python app.py   (then open http://localhost:5000)
"""

import os
import time
import threading

from flask import (
    Flask, Response, render_template, request, jsonify,
    url_for, redirect, flash,
)
from werkzeug.utils import secure_filename

from config import config
from database import init_db, log_event, get_events, get_stats, clear_events
from camera import CameraStream
from analyzer import analyze_file
from analytics import EventLogger, DrowsinessPredictor, TripRiskTimeline
from notifications import NotificationManager, EmergencyContactNotifier


app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_MB * 1024 * 1024
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

init_db()

# Single shared webcam pipeline (lazily started).
camera = CameraStream(config)
# Feature 17/18: portable file event log + mobile push (both degrade
# gracefully - no crash if the FS is read-only or firebase-admin is absent).
event_logger = EventLogger(config)
notifier = NotificationManager(config)
# Companion-app intelligence (reused, pure-Python): imminent-drowsiness
# forecast, per-trip risk timeline, and the opt-in emergency-contact
# escalation. All fed from the same per-frame state below.
predictor = DrowsinessPredictor(config)
timeline = TripRiskTimeline(config)
emergency = EmergencyContactNotifier(config)
_last_logged_ts = {"ts": 0.0}


def _allowed(filename):
    return ("." in filename and
            filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS)


def _live_tick(state):
    """Per-frame housekeeping, throttled to ~1 Hz:

      * persist notable events to SQLite (History page) **and** the portable
        JSONL/CSV file log (Feature 17),
      * evaluate mobile-push rules (Feature 18) - the NotificationManager
        applies its own cooldown on top, so the phone is never spammed.

    PRIVACY: only event statistics are written - never raw frames.
    """
    if not state:
        return
    now = time.time()
    # notifications are cheap + self-throttling; evaluate every tick
    notifier.evaluate(state)
    # companion-app intelligence, also cheap: forecast + trip timeline +
    # (opt-in) emergency-contact escalation. Run every tick so the forecast
    # and timeline stay live; each has its own internal throttle/cooldown.
    predictor.update(state)
    timeline.update(state)
    emergency.evaluate(state)
    if now - _last_logged_ts["ts"] < 1.0:
        return
    _last_logged_ts["ts"] = now
    events = state.get("events") or []
    if not events:
        return
    extra = {
        "attention_score": state.get("attention_score"),
        "safety_score": state.get("safety_score"),
        "risk_level": state.get("risk_level"),
        "score": state.get("score"),
    }
    for ev in events:
        log_event(ev["type"], ev["severity"], ev["message"],
                  ear=state.get("ear"), mar=state.get("mar"),
                  score=state.get("score"), source="webcam")
    event_logger.log_many(events, extra=extra)


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("dashboard.html", config=config,
                           cnn_active=camera.cnn_active)


@app.route("/upload")
def upload_page():
    return render_template("upload.html", config=config)


@app.route("/history")
def history_page():
    return render_template("history.html", config=config)


# --------------------------------------------------------------------------- #
#  Live webcam
# --------------------------------------------------------------------------- #
def _mjpeg_generator():
    import cv2
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    while True:
        frame = camera.get_annotated_jpeg()
        if frame is None:
            time.sleep(0.03)
            continue
        _live_tick(camera.latest_state)
        yield boundary + frame + b"\r\n"


@app.route("/video_feed")
def video_feed():
    if not camera.running:
        camera.start()
    return Response(_mjpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/state")
def api_state():
    state = dict(camera.latest_state or {"found": False, "status_text": "Idle"})
    # Feature 20 - privacy transparency (constant, surfaced for the UI badge).
    state["privacy_mode"] = bool(config.PRIVACY_MODE)
    state["video_storage"] = bool(config.VIDEO_STORAGE_ENABLED)
    state["camera_processing"] = "LOCAL"
    state["notifications"] = notifier.status()
    # companion-app additive fields (never override existing keys)
    state["prediction"] = predictor.current()
    state["emergency"] = emergency.status()
    return jsonify(state)


@app.route("/api/camera/<action>", methods=["POST"])
def api_camera(action):
    if action == "start":
        ok = camera.start()
        if ok:
            # fresh session: clear companion-app state so the forecast and
            # trip timeline start clean (mirrors the pipeline reset on start).
            predictor.reset()
            timeline.reset()
            emergency.reset()
        return jsonify({"ok": ok, "running": camera.running,
                        "error": None if ok else "Could not open camera"})
    if action == "stop":
        camera.stop()
        return jsonify({"ok": True, "running": camera.running})
    if action == "reset":
        camera.reset()
        predictor.reset()
        timeline.reset()
        emergency.reset()
        return jsonify({"ok": True, "running": camera.running})
    return jsonify({"ok": False, "error": "unknown action"}), 400


# --------------------------------------------------------------------------- #
#  Upload / offline analysis
# --------------------------------------------------------------------------- #
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No file selected"}), 400
    if not _allowed(file.filename):
        return jsonify({"ok": False, "error": "Unsupported file type"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(config.UPLOAD_FOLDER, filename)
    file.save(save_path)

    try:
        summary = analyze_file(save_path, config)
    except Exception as exc:                          # pragma: no cover
        return jsonify({"ok": False, "error": str(exc)}), 500

    # Log a single summary event for the upload.
    if summary.get("drowsy_events", 0) > 0 or summary.get("yawn_count", 0) > 0:
        log_event(
            "UPLOAD_SUMMARY", "medium",
            f"{summary.get('drowsy_events', 0)} drowsy episodes in {filename}",
            score=summary.get("max_score"), source="upload",
        )
    summary["ok"] = True
    summary["filename"] = filename
    return jsonify(summary)


# --------------------------------------------------------------------------- #
#  Data APIs
# --------------------------------------------------------------------------- #
@app.route("/api/events")
def api_events():
    limit = request.args.get("limit", 100, type=int)
    source = request.args.get("source", None)
    return jsonify({"events": get_events(limit=limit, source=source)})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/events/clear", methods=["POST"])
def api_clear():
    n = clear_events()
    return jsonify({"ok": True, "removed": n})


# --------------------------------------------------------------------------- #
#  Session analytics, mobile push, event export (Features 16-18)
# --------------------------------------------------------------------------- #
@app.route("/api/session/summary")
def api_session_summary():
    """End-of-session analytics (shown in the summary modal on stop)."""
    summary = camera.session_summary() or {}
    # additive companion-app fields: the full trip risk timeline + the final
    # drowsiness forecast, so the summary modal / mobile app can show them.
    summary["timeline"] = timeline.series()
    summary["final_prediction"] = predictor.current()
    return jsonify(summary)


@app.route("/api/predict")
def api_predict():
    """Predictive-drowsiness forecast: probability, level, projected score, ETA."""
    return jsonify(predictor.current())


@app.route("/api/timeline")
def api_timeline():
    """Trip risk timeline: downsampled risk/safety/attention series + markers."""
    return jsonify(timeline.series())


@app.route("/api/notify/status")
def api_notify_status():
    return jsonify(notifier.status())


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    """Fire a test push so delivery can be verified without a driving event."""
    result = notifier.send_test()
    return jsonify(result)


@app.route("/api/emergency/status")
def api_emergency_status():
    """Optional emergency-contact escalation status (disabled unless opted in)."""
    return jsonify(emergency.status())


@app.route("/api/emergency/test", methods=["POST"])
def api_emergency_test():
    """Fire a test emergency-contact alert (bypasses the sustain gate/cooldown)."""
    return jsonify(emergency.send_test())


@app.route("/api/events/export")
def api_events_export():
    """Download the portable event log as CSV or JSON (Feature 17)."""
    fmt = (request.args.get("fmt", "json") or "json").lower()
    if fmt not in ("json", "csv"):
        return jsonify({"ok": False, "error": "fmt must be json or csv"}), 400
    mimetype, text = event_logger.export(fmt)
    ext = "csv" if fmt == "csv" else "json"
    fname = f"driver_events.{ext}"
    return Response(
        text, mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "camera_running": camera.running,
        "cnn_active": camera.cnn_active,
        "time": time.time(),
    })


@app.errorhandler(413)
def too_large(_):
    return jsonify({"ok": False,
                    "error": f"File exceeds {config.MAX_CONTENT_MB} MB limit"}), 413


if __name__ == "__main__":
    print("=" * 60)
    print(" Driver Drowsiness Detection Dashboard")
    print(f"   http://{config.HOST}:{config.PORT}")
    print(f"   CNN eye-state model active: {camera.cnn_active}")
    print("=" * 60)
    # threaded=True so the MJPEG stream and API polling run concurrently.
    app.run(host=config.HOST, port=config.PORT,
            debug=config.DEBUG, threaded=True)
