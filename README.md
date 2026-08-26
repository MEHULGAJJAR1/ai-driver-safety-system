# 🚗 AI Driver Monitoring & Safety System

A complete, real-time **AI driver monitoring and safety system** with a Flask
web dashboard. Beyond drowsiness, it tracks **attention**, scores overall
**driving safety**, estimates a **risk level**, escalates alerts intelligently,
speaks **voice warnings**, recommends **breaks**, can push **mobile
notifications**, and produces **session analytics** — all while processing
video **locally** and storing only event statistics (privacy-first).

It fuses multiple detection techniques into a single drowsiness score, adds a
higher-level **safety brain** on top, raises **distinct escalating alarms**,
plots **live charts**, and **logs every event** to a database and portable
CSV/JSON files you can review later.

> ⚠️ **Disclaimer:** This is an assistive prototype for research and learning.
> It is **not** a certified safety device and must not be relied upon to
> prevent accidents. Always drive rested and alert.

---

## ✨ Features

| # | Feature | How it works |
|---|---------|--------------|
| 1 | **Eye closure (EAR)** | Eye Aspect Ratio from facial landmarks; sustained low EAR = micro-sleep |
| 2 | **Yawn detection (MAR)** | Mouth Aspect Ratio; sustained high MAR = yawn |
| 3 | **Head nod / pose** | 3D head pose (pitch/yaw/roll) via `solvePnP`; head dropping = nodding off |
| 4 | **CNN eye-state model** | Optional trained Keras CNN classifies eye crops open/closed and is blended with EAR |
| 5 | **PERCLOS** | Rolling % of time eyes are closed — the gold-standard fatigue metric |
| 6 | **Composite score** | Weighted 0–100 score → `ALERT` / `WARNING` / `DROWSY` |
| 7 | **Audio alarm** | Browser alarm + red screen flash when `DROWSY` (with cooldown) |
| 8 | **Live charts & stats** | Real-time score, EAR/MAR graphs, blink/yawn/nod counters |
| 9 | **Event logging** | Every event saved to SQLite with a History page + charts |
| 10 | **File analysis** | Upload a video/image and get an offline drowsiness report |
| 11 | **Side-way looking** | Head-yaw + duration debounce → `LOOKING LEFT/RIGHT` attention alert (own sound) |
| 12 | **Sunglasses detection** | Lightweight CV (dark-vs-skin + low-texture) flags dark glasses — status only |
| 13 | **Face covered / obstruction** | 4-state visibility machine → `FACE COVERED` / `FACE NOT VISIBLE` (own sound) |
| 14 | **Central AlertManager** | Priority resolution so only **one** alarm sound is ever active at a time |

### 🧭 Safety-intelligence layer (driver-monitoring add-ons)

| # | Feature | How it works |
|---|---------|--------------|
| 15 | **Driver Attention Score** | Smoothed 0–100 score from gaze direction, head pose & eye state |
| 16 | **Distraction Timer** | Continuous look-away seconds; raises a distraction alert past a threshold |
| 17 | **Safety Score** | Smoothed 0–100 combining drowsiness, attention, face visibility, yawning |
| 18 | **Risk Level** | `LOW / MEDIUM / HIGH` derived from safety score, with **hysteresis** (no flicker) |
| 19 | **Escalating alarms** | L1 visual → L2 audible → L3 critical (louder) → L4 mobile — never jumps to the top |
| 20 | **Voice warnings** | Spoken, context-aware prompts via the browser Web Speech API (own cooldown) |
| 21 | **Break recommendation** | Suggests a break from real fatigue signals (drowsy episodes, yawns, sustained risk) |
| 22 | **Fatigue trend** | `STABLE / INCREASING / DECREASING` from the drowsiness-score history |
| 23 | **Attention distribution** | % of time forward / left / right / down / no-face (doughnut chart) |
| 24 | **Session analytics** | End-of-session summary modal + numbers when you stop the camera |
| 25 | **Event export** | Download the portable event log as **CSV** or **JSON** |
| 26 | **Mobile push (FCM)** | Optional Firebase Cloud Messaging for critical events, with cooldown + test button |
| 27 | **Privacy mode** | Video processed **locally**, **no recording**; only event stats are stored |

---

## 🧠 How detection works

### Eye Aspect Ratio (EAR)
Introduced by Soukupová & Čech (2016). For the six eye landmarks *p1…p6*:

```
        ‖p2 − p6‖ + ‖p3 − p5‖
EAR =  ─────────────────────────
              2 · ‖p1 − p4‖
```

Open eye ≈ **0.30**, closed ≈ **0.10**. When EAR stays below
`EAR_THRESHOLD` (default **0.23**) for `EAR_CONSEC_FRAMES` frames, a
micro-sleep is flagged. Short dips are counted as **blinks** instead.

### Mouth Aspect Ratio (MAR)
Vertical lip distance ÷ mouth width. A wide **yawn** pushes MAR above
`MAR_THRESHOLD` (default **0.55**).

### Head pose
Six landmarks + a canonical 3D face model → `cv2.solvePnP` → rotation matrix
→ Euler angles. A large **pitch** means the head is dropping (nodding off);
large **yaw** means looking away from the road.

### PERCLOS
Percentage of frames in a rolling window (~5–6 s) where the eyes are closed.
> `PERCLOS_WARN = 0.25`, `PERCLOS_ALARM = 0.40`.

### Composite score (0–100)
```
score = 45·eye + 25·perclos + 15·yawn + 15·head
```
Weights live in `config.py` (`W_EYE`, `W_PERCLOS`, `W_YAWN`, `W_HEAD`).
Thresholds: `SCORE_WARNING = 40`, `SCORE_ALARM = 70`.

---

## 🛡️ Real-time monitoring add-ons

Four extra monitors run alongside the drowsiness core. They **add** to the
`/api/state` JSON and the on-screen status panel without changing any of the
drowsiness logic above. A central **AlertManager** fuses them and guarantees
**only one alarm sound plays at a time**.

**1 · Drowsiness alarm.** When the composite level hits `DROWSY`, the browser
loops `drowsiness_alarm.wav` and flashes the frame red. The sound is driven by
state *transitions* (start / active / reset) with a cooldown — it is **not**
re-triggered every frame — and auto-stops when you return to normal.

**2 · Side-way looking (attention).** Uses the head-pose **yaw**. Looking past
`SIDE_YAW_THRESHOLD` (default 22°) *continuously* for `SIDE_LOOK_DURATION`
(default 1.5 s) raises `LOOKING LEFT` / `LOOKING RIGHT` and plays a **distinct**
`side_look_alarm.wav`. Small natural glances are ignored, and a brief look back
to the road (`SIDE_LOOK_EXIT_GRACE`) won't reset the timer. If left/right feel
reversed for your camera, set `SIDE_LOOK_INVERT=1`.

**3 · Sunglasses detection.** A lightweight, model-free heuristic: a dark lens
is both **darker than the surrounding skin** *and* **low-texture** (no sclera /
iris / lash detail). A **closed** eye is skin-toned and still textured, so it is
**not** flagged as sunglasses. Reported as a status (no alarm); tune with
`SUNGLASSES_DARK_RATIO`, `SUNGLASSES_STD_MAX`, `SUNGLASSES_CONFIDENCE`,
`SUNGLASSES_MIN_FRAMES`.

**4 · Face covered / camera obstruction.** A 4-state machine —
`clear → partial → covered → none` — based on a rolling detection ratio plus
timeouts. A face that suddenly disappears after being present is treated as
**covered** (`FACE_COVERED_TIMEOUT`); a scene with no face is **not visible**
(`FACE_MISSING_TIMEOUT`). A single dropped frame never triggers it, and it
auto-resets when the face is reliably visible again. Plays
`face_covered_alarm.wav`.

**Priority (highest first):** `CRITICAL DROWSINESS` → `FACE COVERED / NOT
VISIBLE` → `SEVERE DISTRACTION` → `DROWSINESS` → `SIDE-WAY LOOKING` →
`YAWNING` → `SUNGLASSES` (status only). The higher-priority alert wins the
single audio channel; the others remain visible in the status panel. **Mobile**
priority is independent of the audio channel.

---

## 🧠 Safety brain (attention, safety score, risk & escalation)

On top of the drowsiness core, a `DriverStateMonitor` derives the higher-level
intelligence that makes this a *monitoring* system, not just a detector. It
reads the **merged** per-frame state (never random data) so everything is
reproducible and unit-testable with an injectable clock.

**Attention score (0–100).** Smoothed (EMA) toward a per-gaze target: forward
is high, brief glances dip, sustained side-looks sink further the longer they
last, head-down and no-face are low, and closed eyes cap it regardless of head
angle.

**Distraction timer.** Counts continuous look-away seconds (with the same
brief-glance grace as the side-look detector) and raises a distraction alert
past `DISTRACTION_ALERT_THRESHOLD`.

**Safety score (0–100) & risk level.** The safety score is `100 −` weighted
penalties (drowsiness, low attention, face blocked, yawning, sunglasses),
smoothed over time. It maps to `LOW / MEDIUM / HIGH` with **hysteresis**
(`RISK_HYSTERESIS` seconds) so the badge never flickers on the boundary.

**Escalating alarms (L1→L4).** Each alert starts at a **severity-appropriate**
base level (so ordinary drowsiness is audible immediately — it never stays
silent), then escalates by *duration*: L3 adds the louder critical sound after
`ESCALATE_CRITICAL_AFTER`, and L4 becomes a mobile-push candidate after
`ESCALATE_NOTIFY_AFTER`. It **does not jump straight to the top.**

**Voice warnings.** When an alert is audible the browser speaks a short,
context-aware phrase (drowsy / look-forward / keep-face-visible) via the Web
Speech API, gated by the **Voice** toggle and a per-phrase cooldown
(`VOICE_ALERT_COOLDOWN`) so voices never overlap or repeat every second.

**Break recommendation.** A banner appears when real fatigue signals accumulate
(≥ `BREAK_DROWSY_EVENTS` drowsy episodes, ≥ `BREAK_YAWN_COUNT` yawns, sustained
HIGH risk, or a rising fatigue trend while not low-risk).

**Fatigue trend & attention distribution.** The trend compares recent vs. older
halves of the drowsiness-score window (`STABLE / INCREASING / DECREASING`); the
distribution shows the % of time spent forward / left / right / down / no-face.

**Session analytics.** Stopping the camera opens a summary modal (duration, avg
attention, final safety & risk, drowsy episodes, yawns, glances, time
distracted) built from the session's real history.

---

## 🔐 Privacy & 📱 mobile push

**Privacy-first.** All video is processed **on-device**; frames are never
uploaded or written to disk. Only event *statistics* are stored (SQLite +
portable JSONL/CSV). The dashboard shows a **`🔒 LOCAL · REC OFF`** badge, and
`PRIVACY_MODE` / `VIDEO_STORAGE_ENABLED` make this explicit in config.

**Mobile push (optional).** Critical events can push to your phone via Firebase
Cloud Messaging. It is **off by default** and degrades gracefully — with no SDK
or credentials it *simulates* delivery (logs it) so nothing breaks. A **Send
Test Notification** button / `POST /api/notify/test` endpoint verifies delivery
without waiting for a real driving event. Notifications are debounced (one push
per rule per `MOBILE_NOTIFICATION_COOLDOWN`, one push per evaluation). Full
setup: [`docs/FCM_SETUP.md`](docs/FCM_SETUP.md). **Credentials are read from an
env var or a git-ignored JSON file — never hard-coded.**

---

## 📦 Project structure

```
driver_drowsiness_dashboard/
├── app.py                  # Flask app + routes (live, analytics, notify, export)
├── camera.py               # Threaded webcam capture + processing + session reset
├── analyzer.py             # Offline video/image analysis
├── config.py               # ALL thresholds & settings (env-overridable)
├── train_model.py          # Train the CNN eye-state classifier
├── requirements.txt
├── run.sh / run.bat        # One-command launchers
├── detection/
│   ├── landmarks.py         # MediaPipe FaceMesh → EAR, MAR, head pose
│   ├── cnn_model.py         # CNN architecture + inference wrapper
│   ├── sunglasses.py        # Lightweight sunglasses / dark-glasses detector
│   ├── alerts.py            # SideLook + FaceCoverage + AlertManager (priority/escalation/voice)
│   └── drowsiness.py        # Scorer state machine + full pipeline + overlay
├── analytics/
│   ├── scoring.py           # DriverStateMonitor: attention/safety/risk/fatigue/session
│   └── event_logger.py      # Portable JSONL event log + CSV/JSON export
├── notifications/
│   ├── manager.py           # NotificationManager: rules + cooldown/debounce
│   └── providers.py         # FCMProvider (optional) + LogProvider fallback
├── database/
│   └── db.py                # SQLite event logging + stats
├── docs/
│   └── FCM_SETUP.md         # Step-by-step mobile push setup (optional)
├── templates/               # dashboard / upload / history (Jinja2)
├── static/
│   ├── css/style.css
│   ├── js/{dashboard,upload,history}.js
│   └── audio/               # alarm.wav + drowsiness_/side_look_/face_covered_/critical_alarm.wav
├── tests/
│   ├── test_features.py     # offline tests for the detection/alert features
│   └── test_monitoring.py   # offline tests for scoring/risk/notifications/logging
├── logs/                    # portable event logs (JSONL) — git-ignored, created at runtime
├── models/                  # trained CNN goes here (eye_state_cnn.h5)
├── uploads/                 # uploaded files for analysis
└── sample_data/             # (optional) put demo clips here
```

---

## 🚀 Quick start

### Option A — one command
```bash
# macOS / Linux
bash run.sh

# Windows
run.bat
```

### Option B — manual
```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Then open **http://localhost:5000** and click **Start Camera**.

> **Python 3.10 or 3.11 recommended** (MediaPipe supports 3.8–3.12).
> On Apple Silicon, replace `tensorflow` with `tensorflow-macos` in
> `requirements.txt` (TensorFlow is only needed for the CNN path).

---

## 🖥️ Using the dashboard

- **Live Monitor** — live annotated webcam, status card, live metrics
  (EAR/MAR/pitch/yaw/PERCLOS/CNN), blink/yawn/nod/drowsy counters, and live
  charts. A **Driver Safety** card shows the attention & safety gauges, risk
  level, distraction timer and fatigue trend; a **Mobile Alerts** card shows
  push status + a **Send Test Notification** button; and there are **Attention
  & Safety** and **Attention Distribution** charts. Toggle the **Audio alarm**
  and **Voice** warnings on/off; **Reset Counters** zeroes the session.
  Pressing **Stop** opens a **session summary** with CSV/JSON export.
- **Analyze File** — upload a video/image; get a verdict, per-frame score
  chart, key stats, and the most-drowsy annotated frame.
- **History** — total/24h/high-severity/yawn stats, an events-by-type
  doughnut, a 24-hour timeline bar chart, and a searchable event table.
  **Clear log** wipes the database.

---

## 🧪 Training the CNN eye-state model (optional)

The dashboard works out of the box **without** the CNN (landmarks only).
To enable the deep-learning path:

1. **Get a dataset** — the [MRL Eye Dataset](http://mrl.cs.vsb.cz/eyedataset)
   (~85k labelled eye crops) works well. Arrange it as:
   ```
   data/
     train/{open,closed}/*.png
     val/{open,closed}/*.png
   ```
   (or a single folder with `open/` + `closed/` and use `--split`).
2. **Train:**
   ```bash
   python train_model.py --data data --epochs 20
   ```
   The best model is saved to `models/eye_state_cnn.h5`.
3. **Restart** the dashboard — the **CNN** badge turns **ON** and predictions
   are blended with EAR automatically.

---

## ⚙️ Configuration

Every threshold is in `config.py` and can be overridden with an environment
variable of the same name, e.g.:

```bash
EAR_THRESHOLD=0.21 MAR_THRESHOLD=0.6 CAMERA_INDEX=1 PORT=8000 python app.py
```

Common knobs: `EAR_THRESHOLD`, `EAR_CONSEC_FRAMES`, `MAR_THRESHOLD`,
`HEAD_PITCH_THRESHOLD`, `PERCLOS_ALARM`, `SCORE_ALARM`, `ALARM_COOLDOWN`,
`USE_CNN`, `CAMERA_INDEX`.

**Monitoring add-on knobs:** `SIDE_YAW_THRESHOLD`, `SIDE_LOOK_DURATION`,
`SIDE_LOOK_EXIT_GRACE`, `SIDE_LOOK_INVERT` (Feature 2);
`SUNGLASSES_DARK_RATIO`, `SUNGLASSES_STD_MAX`, `SUNGLASSES_CONFIDENCE`,
`SUNGLASSES_MIN_FRAMES` (Feature 3);
`FACE_WINDOW`, `FACE_PARTIAL_RATIO`, `FACE_MISSING_TIMEOUT`,
`FACE_COVERED_TIMEOUT`, `FACE_RECENT_SEEN`, `FACE_EDGE_MARGIN` (Feature 4);
plus the audio filenames `DROWSINESS_ALARM_FILE`, `SIDE_LOOK_ALARM_FILE`,
`FACE_COVERED_ALARM_FILE`, `CRITICAL_ALARM_FILE`.

**Safety-brain knobs.** *Attention (6):* `ATTENTION_SMOOTHING`,
`ATTENTION_TARGET_FORWARD/GLANCE/SIDE/DOWN/NOFACE`, `ATTENTION_GREEN_MIN`,
`ATTENTION_YELLOW_MIN`. *Distraction (7):* `DISTRACTION_ALERT_THRESHOLD`,
`CRITICAL_DISTRACTION_DURATION`. *Safety (8):* `SAFETY_SMOOTHING`,
`SAFETY_PENALTY_DROWSY/ATTENTION/FACE/YAWN/SUNGLASSES`. *Risk (9):*
`RISK_LOW_MIN`, `RISK_MED_MIN`, `RISK_HYSTERESIS`. *Escalation (10):*
`ESCALATE_AUDIBLE_AFTER`, `ESCALATE_CRITICAL_AFTER`, `ESCALATE_NOTIFY_AFTER`,
`DROWSINESS_DURATION`, `CRITICAL_DROWSINESS_DURATION`, `CRITICAL_SAFETY_SCORE`.
*Voice (11):* `VOICE_ALERT_ENABLED`, `VOICE_ALERT_COOLDOWN`,
`VOICE_TEXT_DROWSY/SIDE/FACE/GENERIC`. *Break (12):* `BREAK_DROWSY_EVENTS`,
`BREAK_YAWN_COUNT`, `BREAK_HIGH_RISK_SUSTAIN`. *Fatigue (15):* `FATIGUE_WINDOW`,
`FATIGUE_DELTA`.

**Privacy & mobile-push knobs.** `PRIVACY_MODE`, `VIDEO_STORAGE_ENABLED`,
`EVENT_LOG_ENABLED`, `EVENT_LOG_DIR` (privacy / event log); and
`MOBILE_NOTIFICATION_ENABLED`, `MOBILE_NOTIFICATION_COOLDOWN`,
`FCM_CREDENTIALS_FILE`, `FCM_PROJECT_ID`, `FCM_DEVICE_TOKEN` (mobile push — see
[`docs/FCM_SETUP.md`](docs/FCM_SETUP.md); credentials come from env / a
git-ignored file, never source).

---

## 🧪 Tests

Offline, hardware-free checks (no webcam, mediapipe or TensorFlow needed):

```bash
python tests/test_features.py     # detection & alert features
python tests/test_monitoring.py   # safety brain, notifications & logging
```

`test_features.py` covers side-look debounce + L/R + invert, the face-coverage
state machine and timeouts (incl. single-frame tolerance), sunglasses vs.
closed-eye separation, and AlertManager priority / single-active-sound
guarantees. `test_monitoring.py` covers attention/safety scoring, risk-level
hysteresis, the distraction timer, fatigue trend, escalation levels (L1→L4),
the notification rules + cooldown (via the always-available log provider), and
the portable event logger's CSV/JSON export.

---

## 🔌 API reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/video_feed` | MJPEG annotated webcam stream |
| GET | `/api/state` | Latest live state (JSON) — drowsiness **plus** `attention`, `side_look`, `side_direction`, `severe_distraction`, `sunglasses_detected`, `face_detected`, `face_coverage`, `face_covered`, `alert_type`, `alert_label`, `alert_sound`, `escalation_level`, `voice_key`, `voice_text`, `attention_score`, `safety_score`, `risk_level`, `distraction_active`, `distraction_duration`, `fatigue_trend`, `attention_distribution`, `break_recommended`, `privacy_mode`, `video_storage`, `camera_processing`, `notifications` |
| POST | `/api/camera/start\|stop\|reset` | Control the webcam pipeline (start resets the session) |
| POST | `/api/analyze` | Analyze an uploaded file (multipart `file`) |
| GET | `/api/events?limit=&source=` | Recent logged events |
| GET | `/api/stats` | Aggregate statistics |
| POST | `/api/events/clear` | Wipe the SQLite event log |
| GET | `/api/session/summary` | End-of-session analytics (summary modal) |
| GET | `/api/notify/status` | Mobile-push provider status |
| POST | `/api/notify/test` | Send a test push notification |
| GET | `/api/events/export?fmt=csv\|json` | Download the portable event log |
| GET | `/api/health` | Health/liveness probe |

---

## 🩺 Troubleshooting

- **“Could not open camera”** — another app is using the webcam, or the index
  is wrong. Try `CAMERA_INDEX=1` (or 2). On macOS, grant Terminal camera
  permission in *System Settings → Privacy & Security → Camera*.
- **No audio alarm** — browsers block autoplay until you interact with the
  page. Clicking **Start Camera** unlocks audio; the alarms then play. Ensure
  the five files exist in `static/audio/` (`alarm.wav`, `drowsiness_alarm.wav`,
  `side_look_alarm.wav`, `face_covered_alarm.wav`, `critical_alarm.wav` — the
  louder L3 escalation sound). Use the **Audio alarm** toggle to mute.
- **No voice warnings** — spoken prompts use the browser **Web Speech API**;
  make sure the **Voice** toggle is on and your browser/OS has a speech voice
  installed. Voice is independent of the alarm toggle and has its own cooldown
  (`VOICE_ALERT_COOLDOWN`) so phrases never overlap.
- **`mediapipe` install fails** — use Python 3.10/3.11 and upgrade pip
  (`pip install -U pip`).
- **CNN badge stays OFF** — that’s expected until you train and place
  `models/eye_state_cnn.h5`. The landmark detectors still work fully.
- **Laggy video** — lower `FRAME_WIDTH`/`FRAME_HEIGHT` in `config.py`, or set
  `USE_CNN=0`.

---

## 📚 Tech stack
Flask · OpenCV · MediaPipe FaceMesh · NumPy/SciPy · TensorFlow/Keras (optional) ·
SQLite · Chart.js · Web Speech API (voice) · Firebase Cloud Messaging (optional
mobile push).

Made as a full-stack computer-vision demo. PRs and tweaks welcome.
