"""
Approval service.

Coordinates the multi-stage approval pipeline workflows.
Thin orchestration layer; the approval endpoint logic itself lives in
app/api/v1/approvals.py pending the Phase 10 router split.

Delegates approval actions to security/authorization.process_approval_action.
"""
from typing import Any, Dict, Optional

from supabase import Client

from app.core.logging import logger
from app.security.authorization import process_approval_action


def approve_entity(
    db: Client, entity_type: str, entity_id: str
) -> None:
    """
    Mark an entity as approved, propagating the status to the correct table.

    See security.authorization.process_approval_action for the full logic.
    """
    process_approval_action(db, entity_type, entity_id, action="approve")
