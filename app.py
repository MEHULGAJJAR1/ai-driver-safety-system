import os
import time
import base64
import threading

import cv2
import numpy as np

from flask import (
    Flask,
    Response,
    render_template,
    request,
    jsonify,
)

from werkzeug.utils import secure_filename

from config import config
from database import init_db, log_event, get_events, get_stats, clear_events
from analyzer import analyze_file
from analytics import EventLogger, DrowsinessPredictor, TripRiskTimeline
from notifications import NotificationManager, EmergencyContactNotifier


app = Flask(__name__)

app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_MB * 1024 * 1024

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)

init_db()


# ======================================================================
# BROWSER CAMERA MODE
# ======================================================================

try:
    from detection import DrowsinessPipeline
except Exception as exc:
    DrowsinessPipeline = None
    print("[WARNING] Could not import DrowsinessPipeline:", exc)


pipeline = None
pipeline_lock = threading.Lock()

browser_camera_running = False

latest_state = {
    "found": False,
    "status_text": "Idle",
    "score": 0,
    "level": "ALERT",
}

latest_jpeg = None

event_logger = EventLogger(config)
notifier = NotificationManager(config)
predictor = DrowsinessPredictor(config)
timeline = TripRiskTimeline(config)
emergency = EmergencyContactNotifier(config)

_last_logged_ts = 0.0


# ======================================================================
# PIPELINE
# ======================================================================

def create_pipeline():
    global pipeline

    if DrowsinessPipeline is None:
        return False

    with pipeline_lock:
        if pipeline is None:
            try:
                pipeline = DrowsinessPipeline(config)

                if hasattr(pipeline, "reset"):
                    pipeline.reset()

                print("[OK] Drowsiness pipeline initialized.")

            except Exception as exc:
                print("[ERROR] Pipeline initialization failed:", exc)
                pipeline = None
                return False

    return True


def reset_pipeline():
    global pipeline

    if pipeline is None:
        create_pipeline()

    if pipeline is not None and hasattr(pipeline, "reset"):
        try:
            pipeline.reset()
        except Exception as exc:
            print("[WARNING] Pipeline reset failed:", exc)


# ======================================================================
# EVENT HOUSEKEEPING
# ======================================================================

def process_events(state):
    global _last_logged_ts

    if not state:
        return

    now = time.time()

    try:
        notifier.evaluate(state)
    except Exception as exc:
        print("[NOTIFY]", exc)

    try:
        predictor.update(state)
    except Exception as exc:
        print("[PREDICT]", exc)

    try:
        timeline.update(state)
    except Exception as exc:
        print("[TIMELINE]", exc)

    try:
        emergency.evaluate(state)
    except Exception as exc:
        print("[EMERGENCY]", exc)

    if now - _last_logged_ts < 1.0:
        return

    _last_logged_ts = now

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
        try:
            log_event(
                ev.get("type", "UNKNOWN"),
                ev.get("severity", "medium"),
                ev.get("message", ""),
                ear=state.get("ear"),
                mar=state.get("mar"),
                score=state.get("score"),
                source="browser_camera",
            )
        except Exception as exc:
            print("[DB EVENT]", exc)

    try:
        event_logger.log_many(events, extra=extra)
    except Exception as exc:
        print("[EVENT LOGGER]", exc)


# ======================================================================
# PAGES
# ======================================================================

@app.route("/")
def index():
    cnn_active = False

    if pipeline is not None:
        try:
            cnn_active = bool(pipeline.cnn_active)
        except Exception:
            cnn_active = False

    return render_template(
        "dashboard.html",
        config=config,
        cnn_active=cnn_active,
    )


@app.route("/upload")
def upload_page():
    return render_template(
        "upload.html",
        config=config,
    )


@app.route("/history")
def history_page():
    return render_template(
        "history.html",
        config=config,
    )


# ======================================================================
# BROWSER CAMERA START / STOP / RESET
# ======================================================================

@app.route("/api/camera/<action>", methods=["POST"])
def api_camera(action):

    global browser_camera_running
    global latest_state
    global latest_jpeg

    if action == "start":

        if not create_pipeline():
            return jsonify({
                "ok": False,
                "error": "Drowsiness detection pipeline could not be loaded."
            }), 500

        reset_pipeline()

        predictor.reset()
        timeline.reset()
        emergency.reset()

        browser_camera_running = True

        latest_state = {
            "found": False,
            "status_text": "Camera ready",
            "score": 0,
            "level": "ALERT",
        }

        latest_jpeg = None

        return jsonify({
            "ok": True,
            "running": True,
            "mode": "browser_camera",
        })


    if action == "stop":

        browser_camera_running = False

        latest_state = {
            "found": False,
            "status_text": "Camera stopped",
            "score": 0,
            "level": "ALERT",
        }

        latest_jpeg = None

        return jsonify({
            "ok": True,
            "running": False,
        })


    if action == "reset":

        reset_pipeline()

        predictor.reset()
        timeline.reset()
        emergency.reset()

        latest_state = {
            "found": False,
            "status_text": "Idle",
            "score": 0,
            "level": "ALERT",
        }

        return jsonify({
            "ok": True,
            "running": browser_camera_running,
        })


    return jsonify({
        "ok": False,
        "error": "Unknown camera action"
    }), 400


# ======================================================================
# BROWSER FRAME PROCESSING
# ======================================================================

@app.route("/api/process_frame", methods=["POST"])
def process_frame():

    global latest_state
    global latest_jpeg

    if not browser_camera_running:
        return jsonify({
            "ok": False,
            "error": "Camera session is not active."
        }), 400

    if pipeline is None:

        if not create_pipeline():
            return jsonify({
                "ok": False,
                "error": "Detection pipeline unavailable."
            }), 500

    image_data = request.files.get("frame")

    if image_data is None:
        return jsonify({
            "ok": False,
            "error": "No frame received."
        }), 400

    try:

        raw = image_data.read()

        if not raw:
            return jsonify({
                "ok": False,
                "error": "Empty frame."
            }), 400

        arr = np.frombuffer(
            raw,
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            arr,
            cv2.IMREAD_COLOR
        )

        if frame is None:
            return jsonify({
                "ok": False,
                "error": "Invalid image frame."
            }), 400

        # Keep server processing lightweight.
        frame = cv2.resize(
            frame,
            (
                config.FRAME_WIDTH,
                config.FRAME_HEIGHT
            ),
            interpolation=cv2.INTER_AREA,
        )

        # Mirror frame to match normal webcam view.
        frame = cv2.flip(frame, 1)

        with pipeline_lock:

            annotated, state = pipeline.process_frame(
                frame,
                draw=True
            )

        if state is None:
            state = {
                "found": False,
                "status_text": "Processing",
                "score": 0,
                "level": "ALERT",
            }

        latest_state = dict(state)

        process_events(state)

        ok, buffer = cv2.imencode(
            ".jpg",
            annotated,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                config.CAMERA_JPEG_QUALITY
            ],
        )

        if not ok:
            return jsonify({
                "ok": False,
                "error": "Could not encode processed frame."
            }), 500

        jpeg_bytes = buffer.tobytes()

        latest_jpeg = jpeg_bytes

        encoded = base64.b64encode(
            jpeg_bytes
        ).decode("ascii")

        return jsonify({
            "ok": True,
            "image": "data:image/jpeg;base64," + encoded,
            "state": state,
        })

    except Exception as exc:

        print("[FRAME ERROR]", repr(exc))

        return jsonify({
            "ok": False,
            "error": str(exc)
        }), 500


# ======================================================================
# STATE
# ======================================================================

@app.route("/api/state")
def api_state():

    state = dict(
        latest_state or {
            "found": False,
            "status_text": "Idle",
            "score": 0,
        }
    )

    state["privacy_mode"] = bool(
        config.PRIVACY_MODE
    )

    state["video_storage"] = bool(
        config.VIDEO_STORAGE_ENABLED
    )

    state["camera_processing"] = "BROWSER"

    state["browser_camera"] = True

    state["notifications"] = notifier.status()

    state["prediction"] = predictor.current()

    state["emergency"] = emergency.status()

    return jsonify(state)


# ======================================================================
# VIDEO FEED
# ======================================================================

@app.route("/video_feed")
def video_feed():

    def generate():

        while browser_camera_running:

            frame = latest_jpeg

            if frame is not None:

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )

            time.sleep(0.05)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ======================================================================
# UPLOAD ANALYSIS
# ======================================================================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(
            ".",
            1
        )[1].lower()
        in config.ALLOWED_EXTENSIONS
    )


@app.route("/api/analyze", methods=["POST"])
def api_analyze():

    if "file" not in request.files:

        return jsonify({
            "ok": False,
            "error": "No file part"
        }), 400

    file = request.files["file"]

    if file.filename == "":

        return jsonify({
            "ok": False,
            "error": "No file selected"
        }), 400

    if not allowed_file(file.filename):

        return jsonify({
            "ok": False,
            "error": "Unsupported file type"
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
        summary.get("drowsy_events", 0) > 0
        or summary.get("yawn_count", 0) > 0
    ):

        log_event(
            "UPLOAD_SUMMARY",
            "medium",
            f"{summary.get('drowsy_events', 0)} drowsy episodes in {filename}",
            score=summary.get("max_score"),
            source="upload",
        )

    summary["ok"] = True
    summary["filename"] = filename

    return jsonify(summary)


# ======================================================================
# EVENTS
# ======================================================================

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
        "events": get_events(
            limit=limit,
            source=source
        )
    })


@app.route("/api/stats")
def api_stats():

    return jsonify(
        get_stats()
    )


@app.route("/api/events/clear", methods=["POST"])
def api_clear():

    removed = clear_events()

    return jsonify({
        "ok": True,
        "removed": removed,
    })


# ======================================================================
# SESSION SUMMARY
# ======================================================================

@app.route("/api/session/summary")
def api_session_summary():

    summary = {}

    if pipeline is not None and hasattr(
        pipeline,
        "session_summary"
    ):

        try:
            summary = (
                pipeline.session_summary()
                or {}
            )

        except Exception:
            summary = {}

    summary["timeline"] = timeline.series()

    summary["final_prediction"] = predictor.current()

    return jsonify(summary)


# ======================================================================
# PREDICTION
# ======================================================================

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


# ======================================================================
# NOTIFICATIONS
# ======================================================================

@app.route("/api/notify/status")
def api_notify_status():

    return jsonify(
        notifier.status()
    )


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():

    try:
        return jsonify(
            notifier.send_test()
        )
    except Exception as exc:

        return jsonify({
            "ok": False,
            "detail": str(exc)
        }), 500


# ======================================================================
# EMERGENCY
# ======================================================================

@app.route("/api/emergency/status")
def api_emergency_status():

    return jsonify(
        emergency.status()
    )


@app.route("/api/emergency/test", methods=["POST"])
def api_emergency_test():

    try:
        return jsonify(
            emergency.send_test()
        )
    except Exception as exc:

        return jsonify({
            "ok": False,
            "detail": str(exc)
        }), 500


# ======================================================================
# EXPORT
# ======================================================================

@app.route("/api/events/export")
def api_events_export():

    fmt = (
        request.args.get(
            "fmt",
            "json"
        )
        or "json"
    ).lower()

    if fmt not in ("json", "csv"):

        return jsonify({
            "ok": False,
            "error": "fmt must be json or csv"
        }), 400

    mimetype, text = event_logger.export(
        fmt
    )

    extension = (
        "csv"
        if fmt == "csv"
        else "json"
    )

    filename = (
        f"driver_events.{extension}"
    )

    return Response(
        text,
        mimetype=mimetype,
        headers={
            "Content-Disposition":
                f"attachment; filename={filename}"
        },
    )


# ======================================================================
# HEALTH
# ======================================================================

@app.route("/api/health")
def api_health():

    return jsonify({
        "ok": True,
        "camera_running": browser_camera_running,
        "camera_mode": "browser",
        "cnn_active": (
            bool(
                getattr(
                    pipeline,
                    "cnn_active",
                    False
                )
            )
            if pipeline
            else False
        ),
        "time": time.time(),
    })


# ======================================================================
# ERROR HANDLERS
# ======================================================================

@app.errorhandler(413)
def too_large(_):

    return jsonify({
        "ok": False,
        "error":
            f"File exceeds "
            f"{config.MAX_CONTENT_MB} MB limit"
    }), 413


# ======================================================================
# LOCAL DEVELOPMENT
# ======================================================================

if __name__ == "__main__":

    print("=" * 60)
    print(" Driver Drowsiness Detection Dashboard")
    print("=" * 60)
    print(
        f" Local URL: "
        f"http://127.0.0.1:{config.PORT}"
    )
    print(
        " Camera mode: BROWSER CAMERA"
    )
    print("=" * 60)

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        threaded=True,
    )