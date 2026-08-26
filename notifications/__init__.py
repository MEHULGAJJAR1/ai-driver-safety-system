"""Mobile push-notification layer (Features 18/19).

    NotificationManager - decides *when* a phone should be pinged (meaningful
                          events only), enforces a global cooldown + per-rule
                          debounce, and dispatches on a background thread so
                          the capture loop never blocks.
    FCMProvider          - thin Firebase Cloud Messaging sender that degrades
                          gracefully: if firebase-admin isn't installed or no
                          credentials are configured, it logs instead of
                          crashing. A LogProvider is the always-on fallback.

SECURITY: credentials are read from an environment variable or a gitignored
JSON file - never hard-coded. See docs/FCM_SETUP.md.
"""

from .manager import NotificationManager        # noqa: F401
from .providers import (                          # noqa: F401
    FCMProvider, LogProvider, EmergencyContactProvider,
)
from .emergency import EmergencyContactNotifier   # noqa: F401

__all__ = ["NotificationManager", "FCMProvider", "LogProvider",
           "EmergencyContactProvider", "EmergencyContactNotifier"]
