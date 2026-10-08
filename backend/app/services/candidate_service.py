"""
Candidate service.

Handles candidate retrieval, creation, and CSV upload processing.

Extracted from main_commented (1).py — candidates CRUD routes.
"""
from typing import Any, Dict, List, Optional

from supabase import Client

from app.core.logging import logger
from app.repositories.candidates import (
    find_accessible_candidates,
    find_candidate_by_id,
    find_candidate_by_email,
)


def get_accessible_candidates(
    db: Client, owner_ids: set, org_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return candidates visible to the authenticated recruiter."""
    return find_accessible_candidates(db, owner_ids, org_id)


def get_candidate_by_id(db: Client, candidate_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single candidate record by ID."""
    return find_candidate_by_id(db, candidate_id)


def get_candidate_by_email(db: Client, email: str) -> Optional[Dict[str, Any]]:
    """Find a candidate by email address (case-insensitive)."""
    return find_candidate_by_email(db, email)
