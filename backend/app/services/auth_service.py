"""
Auth service.

Orchestrates authentication and user session management.
Delegates to security helpers and Supabase Auth.

Extracted from main_commented (1).py — auth-related route logic.
"""
from typing import Optional

from supabase import Client

from app.core.logging import logger
from app.security.authentication import get_current_user_id, get_email_from_token


def resolve_authenticated_user(
    db: Client,
    authorization: Optional[str],
    x_user_email: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve the authenticated user's ID from headers.

    Returns user_id or None if not authenticated.
    """
    from app.integrations.supabase_client import get_admin_supabase_client
    return get_current_user_id(authorization, x_user_email, get_admin_supabase_client)


def get_user_email(authorization: Optional[str]) -> Optional[str]:
    """Extract the email from a bearer JWT."""
    return get_email_from_token(authorization)
