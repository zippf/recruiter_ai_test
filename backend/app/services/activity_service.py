"""
Activity service.

Thin wrapper over notification_service.log_activity_event, kept as a named
service module so routers import from a stable boundary.

Extracted from main_commented (1).py lines 1051–1067.
"""
from typing import Optional

from supabase import Client

from app.services.notification_service import log_activity_event  # re-export for convenience


def record_activity(
    db: Client,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_name: str = "Recruiter",
    actor_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Record a new activity entry in the audit log."""
    log_activity_event(
        db=db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_name=actor_name,
        actor_id=actor_id,
        organization_id=organization_id,
        metadata=metadata,
    )
