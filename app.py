"""
app.py
======
Driver Drowsiness Detection Dashboard.

Supports:

LOCAL:
    OpenCV webcam.

PRODUCTION:
    Browser/mobile camera using getUserMedia().
"""

import os
import time

from flask import (
    Flask,
    Response,
    render_template,
    request,
    jsonify,
)

from werkzeug.utils import secure_filename

from config import config
from database import (
    init_db,
    log_event,
    get_events,
    get_stats,
    clear_events,
)

from camera import CameraStream
from analyzer import analyze_file

from analytics import (
    EventLogger,
    DrowsinessPredictor,
    TripRiskTimeline,
)

from notifications import (
    NotificationManager,
    EmergencyContactNotifier,
)


# ------------------------------------------------------------------ #
# Flask
# ------------------------------------------------------------------ #

app = Flask(__name__)

app.config["SECRET_KEY"] = config.SECRET_KEY

app.config["MAX_CONTENT_LENGTH"] = (
    config.MAX_CONTENT_MB * 1024 * 1024
)

os.makedirs(
    config.UPLOAD_FOLDER,
    exist_ok=True
)

init_db()


# ------------------------------------------------------------------ #
# Core services
# ------------------------------------------------------------------ #

camera = CameraStream(config)

event_logger = EventLogger(config)

notifier = NotificationManager(config)

predictor = DrowsinessPredictor(config)

timeline = TripRiskTimeline(config)

emergency = EmergencyContactNotifier(config)

_last_logged_ts = {
    "ts": 0.0
}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _allowed(filename):

    return (
        "." in filename
        and filename.rsplit(
            ".",
            1
        )[1].lower()
        in config.ALLOWED_EXTENSIONS
    )


def _live_tick(state):

    if not state:
        return

    now = time.time()

    notifier.evaluate(state)

    predictor.update(state)

    timeline.update(state)

    emergency.evaluate(state)

    if (
        now
        - _last_logged_ts["ts"]
        < 1.0
    ):
        return

    _last_logged_ts["ts"] = now

    events = state.get("events") or []

    if not events:
        return

    extra = {
        "attention_score":
            state.get("attention_score"),

        "safety_score":
            state.get("safety_score"),

        "risk_level":
            state.get("risk_level"),

        "score":
            state.get("score"),
    }

    for ev in events:

        log_event(
            ev["type"],
            ev["severity"],
            ev["message"],
            ear=state.get("ear"),
            mar=state.get("mar"),
            score=state.get("score"),
            source="webcam",
        )

    event_logger.log_many(
        events,
        extra=extra
    )


# ------------------------------------------------------------------ #
# Pages
# ------------------------------------------------------------------ #

@app.route("/")
def index():

    return render_template(
        "dashboard.html",
        config=config,
        cnn_active=camera.cnn_active
    )


@app.route("/upload")
def upload_page():

    return render_template(
        "upload.html",
        config=config
    )


@app.route("/history")
def history_page():

    return render_template(
        "history.html",
        config=config
    )


# ------------------------------------------------------------------ #
# LOCAL MJPEG
# ------------------------------------------------------------------ #

def _mjpeg_generator():

    boundary = (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n\r\n"
    )

    while True:

        frame = (
            camera.get_annotated_jpeg()
        )

        if frame is None:

            time.sleep(0.03)
            continue

        _live_tick(
            camera.latest_state
        )

        yield (
            boundary
            + frame
            + b"\r\n"
        )


@app.route("/video_feed")
def video_feed():

    # Only use physical webcam locally.
    if config.PRODUCTION:

        return jsonify({
            "ok": False,
            "error":
                "Production uses browser/mobile camera mode."
        }), 400

    if not camera.running:

        camera.start()

    return Response(
        _mjpeg_generator(),
        mimetype=(
            "multipart/x-mixed-replace;"
            " boundary=frame"
        )
    )


# ------------------------------------------------------------------ #
# BROWSER / MOBILE CAMERA
# ------------------------------------------------------------------ #

@app.route(
    "/api/camera/browser/start",
    methods=["POST"]
)
def browser_camera_start():

    ok = camera.start_browser()

    if ok:

        predictor.reset()
        timeline.reset()
        emergency.reset()

    return jsonify({
        "ok": ok,
        "running": camera.running,
        "browser_mode": True,
        "error":
            None
            if ok
            else
            "AI pipeline could not start"
    })


@app.route(
    "/api/camera/frame",
    methods=["POST"]
)
def browser_camera_frame():

    data = request.get_json(
        silent=True
    ) or {}

    image = data.get("image")

    if not image:

        return jsonify({
            "ok": False,
            "error":
                "No camera frame received"
        }), 400

    result = camera.process_browser_frame(
        image
    )

    if not result.get("ok"):

        return jsonify(result), 400

    _live_tick(
        camera.latest_state
    )

    return jsonify({
        "ok": True,
        "state":
            camera.latest_state,
        "frame":
            result.get("frame")
    })


# ------------------------------------------------------------------ #
# Camera controls
# ------------------------------------------------------------------ #

@app.route(
    "/api/camera/<action>",
    methods=["POST"]
)
def api_camera(action):

    if action == "start":

        # Production never opens server webcam.
        if config.PRODUCTION:

            return jsonify({
                "ok": False,
                "browser_required": True,
                "error":
                    "Use browser camera mode."
            })

        ok = camera.start()

        if ok:

            predictor.reset()
            timeline.reset()
            emergency.reset()

        return jsonify({
            "ok": ok,
            "running":
                camera.running,
            "browser_mode":
                camera.browser_mode,
            "error":
                None
                if ok
                else
                "Could not open camera"
        })

    if action == "stop":

        camera.stop()

        return jsonify({
            "ok": True,
            "running":
                camera.running
        })

    if action == "reset":

        camera.reset()

        predictor.reset()
        timeline.reset()
        emergency.reset()

        return jsonify({
            "ok": True,
            "running":
                camera.running
        })

    return jsonify({
        "ok": False,
        "error":
            "unknown action"
    }), 400


# ------------------------------------------------------------------ #
# State
# ------------------------------------------------------------------ #

@app.route("/api/state")
def api_state():

    state = dict(
        camera.latest_state
        or {
            "found": False,
            "status_text": "Idle"
        }
    )

    state["privacy_mode"] = bool(
        config.PRIVACY_MODE
    )

    state["video_storage"] = bool(
        config.VIDEO_STORAGE_ENABLED
    )

    state["camera_processing"] = (
        "BROWSER"
        if camera.browser_mode
        else "LOCAL"
    )

    state["camera_mode"] = (
        "browser"
        if camera.browser_mode
        else "local"
    )

    state["notifications"] = (
        notifier.status()
    )

    state["prediction"] = (
        predictor.current()
    )

    state["emergency"] = (
        emergency.status()
    )

    return jsonify(state)


# ------------------------------------------------------------------ #
# Upload analysis
# ------------------------------------------------------------------ #

@app.route(
    "/api/analyze",
    methods=["POST"]
)
def api_analyze():

    if "file" not in request.files:

        return jsonify({
            "ok": False,
            "error":
                "No file part"
        }), 400

    file = request.files["file"]

    if file.filename == "":

        return jsonify({
            "ok": False,
            "error":
                "No file selected"
        }), 400

    if not _allowed(
        file.filename
    ):

        return jsonify({
            "ok": False,
            "error":
                "Unsupported file type"
        }), 400

    filename = secure_filename(
        file.filename
    )

    save_path = os.path.join(
        config.UPLOAD_FOLDER,
        filename
    )

    file.save(save_path)

    try:

        summary = analyze_file(
            save_path,
            config
        )

    except Exception as exc:

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500

    if (
        summary.get(
            "drowsy_events",
            0
        ) > 0
        or
        summary.get(
            "yawn_count",
            0
        ) > 0
    ):

        log_event(
            "UPLOAD_SUMMARY",
            "medium",
            (
                f"{summary.get('drowsy_events', 0)} "
                f"drowsy episodes in {filename}"
            ),
            score=summary.get(
                "max_score"
            ),
            source="upload",
        )

    summary["ok"] = True
    summary["filename"] = filename

    return jsonify(summary)


# ------------------------------------------------------------------ #
# Data APIs
# ------------------------------------------------------------------ #

@app.route("/api/events")
def api_events():

    limit = request.args.get(
        "limit",
        100,
        type=int
    )

    source = request.args.get(
        "source",
        None
    )

    return jsonify({
        "events":
            get_events(
                limit=limit,
                source=source
            )
    })


@app.route("/api/stats")
def api_stats():

    return jsonify(
        get_stats()
    )


@app.route(
    "/api/events/clear",
    methods=["POST"]
)
def api_clear():

    n = clear_events()

    return jsonify({
        "ok": True,
        "removed": n
    })


# ------------------------------------------------------------------ #
# Session analytics
# ------------------------------------------------------------------ #

@app.route("/api/session/summary")
def api_session_summary():

    summary = (
        camera.session_summary()
        or {}
    )

    summary["timeline"] = (
        timeline.series()
    )

    summary["final_prediction"] = (
        predictor.current()
    )

    return jsonify(summary)


@app.route("/api/predict")
def api_predict():

    return jsonify(
        predictor.current()
    )


@app.route("/api/timeline")
def api_timeline():

    return jsonify(
        timeline.series()
    )


# ------------------------------------------------------------------ #
# Notifications
# ------------------------------------------------------------------ #

@app.route("/api/notify/status")
def api_notify_status():

    return jsonify(
        notifier.status()
    )


@app.route(
    "/api/notify/test",
    methods=["POST"]
)
def api_notify_test():

    return jsonify(
        notifier.send_test()
    )


# ------------------------------------------------------------------ #
# Emergency
# ------------------------------------------------------------------ #

@app.route("/api/emergency/status")
def api_emergency_status():

    return jsonify(
        emergency.status()
    )


@app.route(
    "/api/emergency/test",
    methods=["POST"]
)
def api_emergency_test():

    return jsonify(
        emergency.send_test()
    )


# ------------------------------------------------------------------ #
# Export
# ------------------------------------------------------------------ #

@app.route("/api/events/export")
def api_events_export():

    fmt = (
        request.args.get(
            "fmt",
            "json"
        )
        or "json"
    ).lower()

    if fmt not in (
        "json",
        "csv"
    ):

        return jsonify({
            "ok": False,
            "error":
                "fmt must be json or csv"
        }), 400

    mimetype, text = (
        event_logger.export(fmt)
    )

    ext = (
        "csv"
        if fmt == "csv"
        else "json"
    )

    fname = (
        f"driver_events.{ext}"
    )

    return Response(
        text,
        mimetype=mimetype,
        headers={
            "Content-Disposition":
                (
                    "attachment; "
                    f"filename={fname}"
                )
        }
    )


# ------------------------------------------------------------------ #
# Health
# ------------------------------------------------------------------ #

@app.route("/api/health")
def api_health():

    return jsonify({
        "ok": True,
        "camera_running":
            camera.running,
        "camera_mode":
            (
                "browser"
                if camera.browser_mode
                else "local"
            ),
        "cnn_active":
            camera.cnn_active,
        "production":
            config.PRODUCTION,
        "time":
            time.time()
    })


# ------------------------------------------------------------------ #
# Errors
# ------------------------------------------------------------------ #

@app.errorhandler(413)
def too_large(_):

    return jsonify({
        "ok": False,
        "error":
            (
                f"File exceeds "
                f"{config.MAX_CONTENT_MB} MB limit"
            )
    }), 413


# ------------------------------------------------------------------ #
# Local development
# ------------------------------------------------------------------ #

if __name__ == "__main__":

    print("=" * 60)

    print(
        " Driver Drowsiness Detection Dashboard"
    )

    print(
        f"   http://{config.HOST}:{config.PORT}"
    )

    print(
        "   Production:"
        f" {config.PRODUCTION}"
    )

    print(
        "   Camera mode:"
        + (
            " BROWSER"
            if config.PRODUCTION
            else " LOCAL"
        )
    )

    print(
        "   CNN eye-state model active:"
        f" {camera.cnn_active}"
    )

    print("=" * 60)

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=True
    )