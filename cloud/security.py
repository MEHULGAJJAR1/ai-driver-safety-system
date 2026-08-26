"""
cloud/security.py
=================
API-key authentication dependency.

Clients present ``X-API-Key: <key>``. The key must be one of the comma-separated
values in the ``API_KEYS`` env var. Auth can be turned off for local dev (no keys
configured + ENV=development), but in production a missing/blank key set makes
every protected route return 401 - fail closed, never open.

Keys are compared with ``hmac.compare_digest`` to avoid timing leaks.
"""

import hmac

try:
    from fastapi import Header, HTTPException, status
except Exception:                                           # pragma: no cover
    raise


class APIKeyGuard:
    """Callable FastAPI dependency bound to the service settings."""

    def __init__(self, settings):
        self.settings = settings

    async def __call__(self, x_api_key: str = Header(default="")):
        s = self.settings
        if not s.require_auth:
            return "anonymous"                              # dev convenience only
        if not s.api_keys:                                  # fail closed
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Server has no API keys configured")
        for key in s.api_keys:
            if hmac.compare_digest(str(x_api_key), str(key)):
                return "device"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or missing X-API-Key")
