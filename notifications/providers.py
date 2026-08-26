"""
notifications/providers.py
==========================
Pluggable push-notification back-ends.

FCMProvider  - real Firebase Cloud Messaging via the (optional) firebase-admin
               SDK. Imports are guarded so the app runs fine without the SDK.
LogProvider  - always-available fallback that records/prints the notification
               instead of sending it, so the test endpoint works out of the box.

Each provider exposes:
    .name                 -> str
    .configured           -> bool  (can it actually deliver?)
    .send(token, title, body, data) -> (ok: bool, detail: str)
"""

import os


class LogProvider:
    name = "log"
    configured = True   # always "works" (it just records)

    def __init__(self, cfg=None):
        self.cfg = cfg

    def send(self, token, title, body, data=None):
        print(f"[Notify:log] {title} | {body} | token={_mask(token)} data={data}")
        return True, "logged (no real device push - LogProvider)"


class FCMProvider:
    name = "fcm"

    def __init__(self, cfg):
        self.cfg = cfg
        self._messaging = None
        self._app = None
        self.configured = False
        self.reason = ""
        self._init()

    def _init(self):
        cfg = self.cfg
        creds = getattr(cfg, "FCM_CREDENTIALS_FILE", "")
        token = getattr(cfg, "FCM_DEVICE_TOKEN", "")
        if not token:
            self.reason = "no FCM_DEVICE_TOKEN configured"
            return
        if not creds or not os.path.exists(creds):
            self.reason = f"credentials file not found ({creds or 'unset'})"
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
        except Exception as exc:                                # pragma: no cover
            self.reason = f"firebase-admin not installed ({exc})"
            return
        try:
            if not firebase_admin._apps:
                cert = credentials.Certificate(creds)
                self._app = firebase_admin.initialize_app(cert)
            else:
                self._app = firebase_admin.get_app()
            self._messaging = messaging
            self.configured = True
            self.reason = "ok"
        except Exception as exc:                                # pragma: no cover
            self.reason = f"init failed: {exc}"

    def send(self, token, title, body, data=None):
        if not self.configured or self._messaging is None:      # pragma: no cover
            return False, f"FCM not configured: {self.reason}"
        try:
            msg = self._messaging.Message(
                token=token,
                notification=self._messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
            )
            msg_id = self._messaging.send(msg)
            return True, f"sent id={msg_id}"
        except Exception as exc:                                # pragma: no cover
            return False, f"send failed: {exc}"


def _mask(token):
    if not token:
        return "<none>"
    return token[:6] + "..." + token[-4:] if len(token) > 12 else "***"


class EmergencyContactProvider:
    """Delivers an emergency-contact alert.

    If ``EMERGENCY_CONTACT_WEBHOOK`` is configured it POSTs a small JSON
    payload to that URL (a Twilio proxy, an IFTTT/webhook endpoint, your own
    server, ...) using only the standard library. With no webhook configured
    it falls back to logging, so the test button still works out of the box.

    Nothing here ever blocks the caller: the manager dispatches on a
    background thread. All network use is wrapped so a failure can never crash
    the monitoring loop.
    """

    name = "emergency"

    def __init__(self, cfg):
        self.cfg = cfg
        self.webhook = getattr(cfg, "EMERGENCY_CONTACT_WEBHOOK", "") or ""
        self.timeout = float(getattr(cfg, "EMERGENCY_HTTP_TIMEOUT", 5.0))
        # "configured" == can actually reach a real contact (webhook present)
        self.configured = bool(self.webhook)

    def send(self, title, body, data=None):
        payload = {
            "title": title,
            "body": body,
            "contact_name": getattr(self.cfg, "EMERGENCY_CONTACT_NAME", ""),
            "contact_phone": getattr(self.cfg, "EMERGENCY_CONTACT_PHONE", ""),
        }
        payload.update(data or {})
        if not self.webhook:
            print(f"[Notify:emergency] (no webhook) {title} | {body} | {payload}")
            return True, "logged (no EMERGENCY_CONTACT_WEBHOOK - EmergencyContactProvider)"
        try:
            import json
            import urllib.request
            req = urllib.request.Request(
                self.webhook,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                code = getattr(resp, "status", resp.getcode())
            return (200 <= int(code) < 300), f"webhook responded {code}"
        except Exception as exc:                                # pragma: no cover
            return False, f"webhook failed: {exc}"
