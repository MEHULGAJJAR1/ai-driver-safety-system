"""
cloud/models.py
===============
Pydantic request models for input validation at the API boundary. Responses are
plain dicts straight from the service layer (already JSON-safe).

PRIVACY: state/event items are free-form dicts of SCORES and STATISTICS only.
The API contract never includes image or frame data, so none can be uploaded.
"""

from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field
except Exception:                                           # pragma: no cover
    raise


class SessionCreate(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128,
                           description="Stable identifier for the phone/edge device")
    started_at: Optional[float] = Field(None, description="Epoch seconds; server time if omitted")
    meta: Dict[str, Any] = Field(default_factory=dict,
                                 description="Free-form, non-sensitive metadata (app version, etc.)")


class StateBatch(BaseModel):
    states: List[Dict[str, Any]] = Field(default_factory=list,
                                          description="Ordered per-frame state dicts (scores only)")


class EventBatch(BaseModel):
    events: List[Dict[str, Any]] = Field(default_factory=list,
                                          description="Event records (type/severity/message/scores)")


class SessionClose(BaseModel):
    summary: Dict[str, Any] = Field(default_factory=dict,
                                    description="End-of-session summary from the edge")
