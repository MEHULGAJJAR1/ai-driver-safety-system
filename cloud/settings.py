"""
cloud/settings.py
=================
Twelve-factor configuration for the cloud service. Every value comes from the
environment (or a local ``.env`` file in dev), so NO secrets live in source.

Supports pydantic-settings (Pydantic v2) with a graceful fallback to a plain
``os.environ`` reader, so the module works across environments.
"""

import os

_DEFAULTS = {
    "ENV": "development",
    "HOST": "0.0.0.0",
    "PORT": "8000",
    "MONGODB_URI": "",                 # empty -> in-memory fallback
    "MONGODB_DB": "driver_safety",
    "API_KEYS": "",                    # comma-separated; empty + dev -> auth off
    "REQUIRE_AUTH": "",                # "1"/"0"; default: on unless dev w/ no keys
    "CORS_ORIGINS": "*",               # comma-separated allow-list
    "STATE_BUFFER_CAP": "5000",
}


def _get(name):
    return os.environ.get(name, _DEFAULTS.get(name, ""))


def _csv(value):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


class Settings:
    """Plain settings object (works with or without pydantic-settings)."""

    def __init__(self):
        self.env = _get("ENV")
        self.host = _get("HOST")
        self.port = int(_get("PORT") or 8000)
        self.mongodb_uri = _get("MONGODB_URI")
        self.mongodb_db = _get("MONGODB_DB")
        self.cors_origins = _csv(_get("CORS_ORIGINS")) or ["*"]
        self.api_keys = set(_csv(_get("API_KEYS")))

        require = _get("REQUIRE_AUTH")
        if require in ("1", "true", "True", "yes", "on"):
            self.require_auth = True
        elif require in ("0", "false", "False", "no", "off"):
            self.require_auth = False
        else:
            # default: require auth UNLESS we're in dev with no keys configured
            self.require_auth = not (self.env == "development" and not self.api_keys)

    @property
    def is_production(self):
        return self.env.lower().startswith("prod")

    def public_dict(self):
        """Non-secret view for the /health probe."""
        return {
            "env": self.env,
            "storage": "mongodb" if self.mongodb_uri else "memory",
            "auth_required": self.require_auth,
            "cors_origins": self.cors_origins,
            "api_keys_configured": len(self.api_keys),
        }


def get_settings():
    return Settings()
