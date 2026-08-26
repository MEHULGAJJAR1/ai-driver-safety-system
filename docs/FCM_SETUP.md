# Mobile Push Notifications (Firebase Cloud Messaging)

The dashboard can send a push notification to your phone when a **critical**
driving event happens (falling asleep, camera blocked, sustained distraction,
or a critically low safety score).

This is **completely optional**. If Firebase is not configured the app still
runs normally — notifications are simply *simulated* (printed to the server
log) so you can develop and demo without a phone. The **Send Test
Notification** button on the dashboard tells you which mode you are in.

> **Security first.** Never hard-code Firebase credentials in source code and
> never commit them to Git. This project reads them only from an environment
> variable or a local JSON file that is already listed in `.gitignore`
> (`firebase-credentials.json`, `*serviceAccount*.json`, `.env`).

---

## How it works

```
critical event ──► NotificationManager (rules + cooldown) ──► FCMProvider ──► your phone
                        │                                         │
                        │ debounce: 1 push per rule per 30s        │ firebase-admin SDK
                        └── if unconfigured ─► LogProvider (prints instead of sends)
```

* **One push at a time.** Only the highest-priority rule fires per evaluation.
* **Cooldown/debounce.** Each rule has its own cooldown (default 30 s,
  `MOBILE_NOTIFICATION_COOLDOWN`) so the phone is never spammed every second.
* **Graceful fallback.** No SDK / no credentials / bad token → it logs the
  notification instead of crashing.

---

## 1. Create a Firebase project

1. Go to <https://console.firebase.google.com/> and click **Add project**.
2. Give it any name (e.g. `driver-monitor`) and finish the wizard.

## 2. Generate a service-account key (server credentials)

1. In the Firebase console: **⚙ Project settings → Service accounts**.
2. Click **Generate new private key** → **Generate key**. A JSON file
   downloads.
3. Move that file into the project root and rename it:

   ```
   driver_drowsiness_dashboard/firebase-credentials.json
   ```

   This filename is already git-ignored. **Do not commit it.**

## 3. Get a device registration token (where to send)

You need an FCM **registration token** for the device that should receive
alerts. How you obtain it depends on the client:

* **Android / iOS app:** call `FirebaseMessaging.getToken()` in your app.
* **Web app:** use the Firebase JS SDK `getToken(messaging, { vapidKey })`.
* **Quick test:** the Firebase console (**Engage → Messaging → New campaign →
  test on device**) lets you paste a token and verify delivery.

## 4. Install the optional dependency

```bash
pip install firebase-admin
# or uncomment the firebase-admin line in requirements.txt and re-run:
# pip install -r requirements.txt
```

## 5. Configure the app

Set these as **environment variables** (recommended) — never in source:

```bash
export MOBILE_NOTIFICATION_ENABLED=1
export FCM_DEVICE_TOKEN="the-registration-token-from-step-3"
export FCM_CREDENTIALS_FILE="$(pwd)/firebase-credentials.json"   # optional; this is the default
# optional tuning:
export MOBILE_NOTIFICATION_COOLDOWN=30      # seconds between pushes per rule
```

On Windows (PowerShell):

```powershell
$env:MOBILE_NOTIFICATION_ENABLED = "1"
$env:FCM_DEVICE_TOKEN = "the-registration-token"
```

All of these keys also exist in `config.py` (read via `os.environ`), so you can
override them there for local experiments — but keep real tokens/paths out of
version control.

## 6. Verify delivery

1. Start the app: `python app.py`
2. Open the dashboard and click **Send Test Notification** (in the *Mobile
   Alerts* card), **or** hit the endpoint directly:

   ```bash
   curl -X POST http://localhost:5000/api/notify/test
   ```

3. Expected responses:
   * `{"ok": true, "provider": "fcm", ...}` → real push sent to your phone. 🎉
   * `{"ok": true, "provider": "log", ...}` → simulated (Firebase not
     configured). Check the server console for the logged message.

The *Mobile Alerts* card badge shows **READY** (real FCM), **SIMULATED**
(log fallback), or **OFF** (disabled).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Badge stays **SIMULATED** | `MOBILE_NOTIFICATION_ENABLED` not set, missing token, or `firebase-credentials.json` not found. |
| `firebase-admin not installed` in logs | `pip install firebase-admin`. |
| `credentials file not found` | Check `FCM_CREDENTIALS_FILE` path / filename. |
| `send failed: ... registration-token-not-registered` | The device token is stale — fetch a fresh one from the client. |
| No push but response says `sent` | Check the phone's notification permissions and that the app/site is registered for FCM. |

## Which events trigger a push?

| Rule | Condition |
|---|---|
| `critical_drowsiness` | Driver appears to be falling asleep (critical drowsiness). |
| `face_blocked` | Face covered or not visible to the camera. |
| `severe_distraction` | Eyes off the road for a sustained period. |
| `low_safety` | Safety score falls to/below `CRITICAL_SAFETY_SCORE`. |
| `escalation` | An alert has persisted to the top of the escalation ladder (L4). |

Each is independently rate-limited so at most one push is sent per evaluation
and no more than one per rule per cooldown window.
