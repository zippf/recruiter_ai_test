from fastapi import APIRouter, Request
import json
from app.core.logging import logger, correlation_id_ctx
from app.schemas.common import TelemetryEventModel

router = APIRouter()

@router.post("/api/v1/telemetry/event")
async def ingest_telemetry_event(event: TelemetryEventModel, request: Request):
    logger.info(json.dumps({
        "event": "frontend_telemetry",
        "telemetry_event_name": event.event_name,
        "page_url": event.url,
        "client_metadata": event.metadata,
        "client_correlation_id": event.correlation_id or correlation_id_ctx.get()
    }))
    return {"status": "recorded"}


