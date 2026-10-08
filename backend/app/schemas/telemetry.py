"""
Telemetry schemas.

Defines the request model for frontend analytics/telemetry events.
"""
from typing import Optional
from pydantic import BaseModel


class TelemetryEventModel(BaseModel):
    event_name: str
    timestamp: Optional[str] = None
    url: Optional[str] = None
    metadata: Optional[dict] = None
    correlation_id: Optional[str] = None
