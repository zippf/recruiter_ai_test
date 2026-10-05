"""
Requirement service.

Handles requirement (hiring mandate) creation and retrieval.

Extracted from main_commented (1).py — requirements CRUD routes.
"""
from typing import Any, Dict, List, Optional

from supabase import Client

from app.core.logging import logger
from app.repositories.requirements import (
    find_accessible_requirements,
    find_requirement_by_id,
    create_requirement,
    update_requirement,
)


def get_accessible_requirements(
    db: Client, owner_ids: set, org_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return requirements visible to the authenticated recruiter."""
    return find_accessible_requirements(db, owner_ids, org_id)


def get_requirement_by_id(
    db: Client, requirement_id: str
) -> Optional[Dict[str, Any]]:
    """Fetch a single requirement by ID."""
    return find_requirement_by_id(db, requirement_id)


def create_new_requirement(
    db: Client, data: Dict[str, Any], created_by: Optional[str] = None
) -> Dict[str, Any]:
    """Create and persist a new requirement record."""
    return create_requirement(db, data, created_by)


def update_requirement_record(
    db: Client, requirement_id: str, updates: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Apply a partial update to a requirement record."""
    return update_requirement(db, requirement_id, updates)
