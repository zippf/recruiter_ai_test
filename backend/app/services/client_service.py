"""
Client service.

Handles client (hiring company) retrieval and creation.

Extracted from main_commented (1).py — clients CRUD routes.
"""
from typing import Any, Dict, List, Optional

from supabase import Client

from app.core.logging import logger
from app.repositories.clients import (
    find_accessible_clients,
    create_client,
    find_client_by_id,
)


def get_accessible_clients(
    db: Client, owner_ids: set, org_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return clients visible to the authenticated recruiter."""
    return find_accessible_clients(db, owner_ids, org_id)


def create_new_client(
    db: Client, name: str, created_by: Optional[str] = None
) -> Dict[str, Any]:
    """Create and return a new client record."""
    return create_client(db, name, created_by)


def get_client_by_id(db: Client, client_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single client by ID."""
    return find_client_by_id(db, client_id)
