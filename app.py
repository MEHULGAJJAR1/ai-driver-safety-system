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
from database import (
    init_db,
    log_event,
    get_events,
    get_stats,
    clear_events,
)
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


# ======================================================================
# FLASK APP
# ======================================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = (
    config.MAX_CONTENT_MB * 1024 * 1024
)


os.makedirs(
    config.UPLOAD_FOLDER,
    exist_ok=True
)

os.makedirs(
    os.path.dirname(config.DATABASE_PATH),
    exist_ok=True
)

init_db()


# ======================================================================
# DROWSINESS PIPELINE
# ======================================================================

DrowsinessPipeline = None

try:

    from detection import DrowsinessPipeline

    print(
        "[OK] DrowsinessPipeline import successful."
    )

except Exception as exc:

    print(
        "[ERROR] DrowsinessPipeline import FAILED."
    )

    print(
        "[ERROR] Exception type:",
        type(exc).__name__
    )

    print(
        "[ERROR] Exception:",
        repr(exc)
    )

    DrowsinessPipeline = None


pipeline = None

pipeline_lock = threading.Lock()


# ======================================================================
# BROWSER CAMERA STATE
# ======================================================================

browser_camera_running = False

latest_state = {
    "found": False,
    "status_text": "Idle",
    "score": 0,
    "level": "ALERT",
    "camera_processing": "BROWSER",
}

latest_jpeg = None


# ======================================================================
# ANALYTICS
# ======================================================================

event_logger = EventLogger(config)

notifier = NotificationManager(config)

predictor = DrowsinessPredictor(config)

timeline = TripRiskTimeline(config)

emergency = EmergencyContactNotifier(config)


_last_logged_ts = 0.0


# ======================================================================
# PIPELINE CREATION
# ======================================================================

def create_pipeline():

    global pipeline

    # --------------------------------------------------------------
    # Import failed
    # --------------------------------------------------------------

    if DrowsinessPipeline is None:

        print(
            "[ERROR] Cannot create pipeline."
        )

        print(
            "[ERROR] DrowsinessPipeline is not available."
        )

        return False


    # --------------------------------------------------------------
    # Prevent multiple pipeline creation
    # --------------------------------------------------------------

    with pipeline_lock:

        if pipeline is not None:

            return True


        try:

            print(
                "[INFO] Creating DrowsinessPipeline..."
            )

            print(
                "[INFO] Python:",
                os.sys.version
            )


            pipeline = DrowsinessPipeline(
                config
            )


            if hasattr(
                pipeline,
                "reset"
            ):

                pipeline.reset()


            print(
                "[OK] DrowsinessPipeline initialized."
            )


            try:

                print(
                    "[INFO] CNN active:",
                    bool(
                        getattr(
                            pipeline,
                            "cnn_active",
                            False
                        )
                    )
                )

            except Exception:

                pass


            return True


        except Exception as exc:

            print(
                "=" * 70
            )

            print(
                "[ERROR] DROWSINESS PIPELINE INITIALIZATION FAILED"
            )

            print(
                "[ERROR] Exception type:",
                type(exc).__name__
            )

            print(
                "[ERROR] Exception:",
                repr(exc)
            )

            print(
                "=" * 70
            )


            pipeline = None

            return False


# ======================================================================
# PIPELINE RESET
# ======================================================================

def reset_pipeline():

    global pipeline

    if pipeline is None:

        if not create_pipeline():

            return False


    if pipeline is not None:

        if hasattr(
            pipeline,
            "reset"
        ):

            try:

                pipeline.reset()

                print(
                    "[OK] Pipeline reset."
                )

            except Exception as exc:

                print(
                    "[WARNING] Pipeline reset failed:",
                    repr(exc)
                )


    return True


# ======================================================================
# EVENT PROCESSING
# ======================================================================

def process_events(state):

    global _last_logged_ts


    if not state:

        return


    now = time.time()


    try:

        notifier.evaluate(
            state
        )

    except Exception as exc:

        print(
            "[NOTIFY]",
            repr(exc)
        )


    try:

        predictor.update(
            state
        )

    except Exception as exc:

        print(
            "[PREDICT]",
            repr(exc)
        )


    try:

        timeline.update(
            state
        )

    except Exception as exc:

        print(
            "[TIMELINE]",
            repr(exc)
        )


    try:

        emergency.evaluate(
            state
        )

    except Exception as exc:

        print(
            "[EMERGENCY]",
            repr(exc)
        )


    if (
        now - _last_logged_ts
        < 1.0
    ):

        return


    _last_logged_ts = now


    events = (
        state.get("events")
        or []
    )


    if not events:

        return


    extra = {

        "attention_score":
            state.get(
                "attention_score"
            ),

        "safety_score":
            state.get(
                "safety_score"
            ),

        "risk_level":
            state.get(
                "risk_level"
            ),

        "score":
            state.get(
                "score"
            ),

    }


    for ev in events:

        try:

            log_event(

                ev.get(
                    "type",
                    "UNKNOWN"
                ),

                ev.get(
                    "severity",
                    "medium"
                ),

                ev.get(
                    "message",
                    ""
                ),

                ear=state.get(
                    "ear"
                ),

                mar=state.get(
                    "mar"
                ),

                score=state.get(
                    "score"
                ),

                source="browser_camera",

            )

        except Exception as exc:

            print(
                "[DB EVENT]",
                repr(exc)
            )


    try:

        event_logger.log_many(
            events,
            extra=extra
        )

    except Exception as exc:

        print(
            "[EVENT LOGGER]",
            repr(exc)
        )


# ======================================================================
# HOME
# ======================================================================

@app.route("/")
def index():

    cnn_active = False


    if pipeline is not None:

        try:

            cnn_active = bool(
                getattr(
                    pipeline,
                    "cnn_active",
                    False
                )
            )

        except Exception:

            cnn_active = False


    return render_template(

        "dashboard.html",

        config=config,

        cnn_active=cnn_active,

    )


# ======================================================================
# UPLOAD PAGE
# ======================================================================

@app.route("/upload")
def upload_page():

    return render_template(
        "upload.html",
        config=config,
    )


# ======================================================================
# HISTORY PAGE
# ======================================================================

@app.route("/history")
def history_page():

    return render_template(
        "history.html",
        config=config,
    )


# ======================================================================
# CAMERA START / STOP / RESET
# ======================================================================

@app.route(
    "/api/camera/<action>",
    methods=["POST"]
)
def api_camera(action):

    global browser_camera_running
    global latest_state
    global latest_jpeg


    # ==============================================================
    # START
    # ==============================================================

    if action == "start":

        print(
            "[CAMERA] Browser camera START requested."
        )


        # ----------------------------------------------------------
        # Load AI pipeline
        # ----------------------------------------------------------

        if not create_pipeline():

            return jsonify({

                "ok": False,

                "error":
                    "Drowsiness detection pipeline could not be loaded.",

                "details":
                    "Check Render logs for the exact pipeline initialization error.",

            }), 500


        # ----------------------------------------------------------
        # Reset AI
        # ----------------------------------------------------------

        reset_pipeline()


        try:

            predictor.reset()

        except Exception as exc:

            print(
                "[WARNING] Predictor reset:",
                repr(exc)
            )


        try:

            timeline.reset()

        except Exception as exc:

            print(
                "[WARNING] Timeline reset:",
                repr(exc)
            )


        try:

            emergency.reset()

        except Exception as exc:

            print(
                "[WARNING] Emergency reset:",
                repr(exc)
            )


        browser_camera_running = True


        latest_state = {

            "found": False,

            "status_text":
                "Waiting for browser camera...",

            "score": 0,

            "level": "ALERT",

            "camera_processing":
                "BROWSER",

        }


        latest_jpeg = None


        print(
            "[CAMERA] Browser camera session started."
        )


        return jsonify({

            "ok": True,

            "running": True,

            "mode":
                "browser_camera",

        })


    # ==============================================================
    # STOP
    # ==============================================================

    if action == "stop":

        print(
            "[CAMERA] Browser camera STOP requested."
        )


        browser_camera_running = False


        latest_state = {

            "found": False,

            "status_text":
                "Camera stopped",

            "score": 0,

            "level": "ALERT",

            "camera_processing":
                "BROWSER",

        }


        latest_jpeg = None


        return jsonify({

            "ok": True,

            "running": False,

        })


    # ==============================================================
    # RESET
    # ==============================================================

    if action == "reset":

        print(
            "[CAMERA] Browser camera RESET requested."
        )


        reset_pipeline()


        try:

            predictor.reset()

        except Exception:
            pass


        try:

            timeline.reset()

        except Exception:
            pass


        try:

            emergency.reset()

        except Exception:
            pass


        latest_state = {

            "found": False,

            "status_text":
                "Idle",

            "score": 0,

            "level": "ALERT",

            "camera_processing":
                "BROWSER",

        }


        latest_jpeg = None


        return jsonify({

            "ok": True,

            "running":
                browser_camera_running,

        })


    return jsonify({

        "ok": False,

        "error":
            "Unknown camera action"

    }), 400


# ======================================================================
# BROWSER FRAME PROCESSING
# ======================================================================

@app.route(
    "/api/process_frame",
    methods=["POST"]
)
def process_browser_frame():

    global latest_state
    global latest_jpeg


    # --------------------------------------------------------------
    # Camera session check
    # --------------------------------------------------------------

    if not browser_camera_running:

        return jsonify({

            "ok": False,

            "error":
                "Camera session is not active."

        }), 400


    # --------------------------------------------------------------
    # Pipeline check
    # --------------------------------------------------------------

    if pipeline is None:

        if not create_pipeline():

            return jsonify({

                "ok": False,

                "error":
                    "Detection pipeline unavailable."

            }), 500


    # --------------------------------------------------------------
    # Receive browser frame
    # --------------------------------------------------------------

    image_file = request.files.get(
        "frame"
    )


    if image_file is None:

        return jsonify({

            "ok": False,

            "error":
                "No camera frame received."

        }), 400


    try:

        # ----------------------------------------------------------
        # Read JPEG
        # ----------------------------------------------------------

        raw = image_file.read()


        if not raw:

            return jsonify({

                "ok": False,

                "error":
                    "Empty camera frame."

            }), 400


        # ----------------------------------------------------------
        # Decode JPEG
        # ----------------------------------------------------------

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

                "error":
                    "Invalid JPEG camera frame."

            }), 400


        # ----------------------------------------------------------
        # Resize
        # ----------------------------------------------------------

        height, width = (
            frame.shape[:2]
        )


        target_width = int(
            getattr(
                config,
                "FRAME_WIDTH",
                640
            )
        )


        target_height = int(
            getattr(
                config,
                "FRAME_HEIGHT",
                480
            )
        )


        if width > target_width:

            scale = (
                target_width
                / float(width)
            )


            frame = cv2.resize(

                frame,

                (
                    target_width,

                    int(
                        height * scale
                    )
                ),

                interpolation=
                    cv2.INTER_AREA,

            )


        # ----------------------------------------------------------
        # Mirror browser camera
        # ----------------------------------------------------------

        frame = cv2.flip(
            frame,
            1
        )


        # ----------------------------------------------------------
        # AI processing
        # ----------------------------------------------------------

        with pipeline_lock:

            annotated, state = (
                pipeline.process_frame(
                    frame,
                    draw=True
                )
            )


        if state is None:

            state = {

                "found": False,

                "status_text":
                    "Processing",

                "score": 0,

                "level":
                    "ALERT",

            }


        latest_state = dict(
            state
        )


        latest_state[
            "camera_processing"
        ] = "BROWSER"


        # ----------------------------------------------------------
        # Events
        # ----------------------------------------------------------

        process_events(
            latest_state
        )


        # ----------------------------------------------------------
        # Encode processed frame
        # ----------------------------------------------------------

        jpeg_quality = int(
            getattr(
                config,
                "CAMERA_JPEG_QUALITY",
                80
            )
        )


        ok, buffer = cv2.imencode(

            ".jpg",

            annotated,

            [
                cv2.IMWRITE_JPEG_QUALITY,
                jpeg_quality
            ],

        )


        if not ok:

            return jsonify({

                "ok": False,

                "error":
                    "Could not encode processed frame."

            }), 500


        jpeg_bytes = (
            buffer.tobytes()
        )


        latest_jpeg = jpeg_bytes


        encoded = (
            base64.b64encode(
                jpeg_bytes
            )
            .decode("ascii")
        )


        # ----------------------------------------------------------
        # Return result
        # ----------------------------------------------------------

        return jsonify({

            "ok": True,

            "image":
                "data:image/jpeg;base64,"
                + encoded,

            "state":
                latest_state,

        })


    except Exception as exc:

        print(
            "=" * 70
        )

        print(
            "[ERROR] BROWSER FRAME PROCESSING FAILED"
        )

        print(
            "[ERROR] Exception type:",
            type(exc).__name__
        )

        print(
            "[ERROR] Exception:",
            repr(exc)
        )

        print(
            "=" * 70
        )


        return jsonify({

            "ok": False,

            "error":
                str(exc)

        }), 500


# ======================================================================
# STATE
# ======================================================================

@app.route("/api/state")
def api_state():

    state = dict(
        latest_state
    )


    state["privacy_mode"] = bool(
        getattr(
            config,
            "PRIVACY_MODE",
            False
        )
    )


    state["video_storage"] = bool(
        getattr(
            config,
            "VIDEO_STORAGE_ENABLED",
            False
        )
    )


    state["camera_processing"] = (
        "BROWSER"
    )


    state["browser_camera"] = True


    try:

        state["notifications"] = (
            notifier.status()
        )

    except Exception:

        state["notifications"] = {}


    try:

        state["prediction"] = (
            predictor.current()
        )

    except Exception:

        state["prediction"] = {}


    try:

        state["emergency"] = (
            emergency.status()
        )

    except Exception:

        state["emergency"] = {}


    return jsonify(
        state
    )


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


            time.sleep(
                0.05
            )


    return Response(

        generate(),

        mimetype=
            "multipart/x-mixed-replace; boundary=frame"

    )


# ======================================================================
# UPLOAD ANALYSIS
# ======================================================================

def allowed_file(filename):

    return (

        "."

        in filename

        and filename.rsplit(
            ".",
            1
        )[1].lower()

        in config.ALLOWED_EXTENSIONS

    )


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


    file = request.files[
        "file"
    ]


    if file.filename == "":

        return jsonify({

            "ok": False,

            "error":
                "No file selected"

        }), 400


    if not allowed_file(
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


    file.save(
        save_path
    )


    try:

        summary = analyze_file(

            save_path,

            config

        )

    except Exception as exc:

        return jsonify({

            "ok": False,

            "error":
                str(exc)

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

            score=
                summary.get(
                    "max_score"
                ),

            source="upload",

        )


    summary["ok"] = True

    summary["filename"] = filename


    return jsonify(
        summary
    )


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

    removed = clear_events()


    return jsonify({

        "ok": True,

        "removed":
            removed,

    })


# ======================================================================
# SESSION SUMMARY
# ======================================================================

@app.route("/api/session/summary")
def api_session_summary():

    summary = {}


    if (

        pipeline is not None

        and hasattr(
            pipeline,
            "session_summary"
        )

    ):

        try:

            summary = (
                pipeline.session_summary()
                or {}
            )

        except Exception as exc:

            print(
                "[SUMMARY]",
                repr(exc)
            )


    try:

        summary["timeline"] = (
            timeline.series()
        )

    except Exception:

        summary["timeline"] = {}


    try:

        summary["final_prediction"] = (
            predictor.current()
        )

    except Exception:

        summary["final_prediction"] = {}


    return jsonify(
        summary
    )


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


@app.route(
    "/api/notify/test",
    methods=["POST"]
)
def api_notify_test():

    try:

        return jsonify(
            notifier.send_test()
        )

    except Exception as exc:

        return jsonify({

            "ok": False,

            "detail":
                str(exc)

        }), 500


# ======================================================================
# EMERGENCY
# ======================================================================

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

    try:

        return jsonify(
            emergency.send_test()
        )

    except Exception as exc:

        return jsonify({

            "ok": False,

            "detail":
                str(exc)

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
        event_logger.export(
            fmt
        )
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

        "camera_running":
            browser_camera_running,

        "camera_mode":
            "browser",

        "pipeline_loaded":
            pipeline is not None,

        "cnn_active": (

            bool(
                getattr(
                    pipeline,
                    "cnn_active",
                    False
                )
            )

            if pipeline is not None

            else False

        ),

        "time":
            time.time(),

    })


# ======================================================================
# ERROR 413
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

    print("=" * 70)

    print(
        " Driver Drowsiness Detection Dashboard"
    )

    print("=" * 70)

    print(
        f" Local URL: "
        f"http://127.0.0.1:{config.PORT}"
    )

    print(
        " Camera mode: BROWSER CAMERA"
    )

    print("=" * 70)


    app.run(

        host=config.HOST,

        port=5001,

        debug=config.DEBUG,

        threaded=True,

    )