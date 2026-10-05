"""
Tenant access helpers.

Contains the `get_recruiter_owner_ids` and `get_user_org_id` functions as
FastAPI-compatible dependency functions (accepting Header parameters directly)
that mirror their original signatures in the monolith.

The underlying logic lives in app.security.authentication; this module
provides the FastAPI Header-based wrappers that can be used with Depends().

Extracted from main_commented (1).py lines 734–824.
"""
from typing import Optional, Set, Tuple

from fastapi import Header
from supabase import Client

from app.core.logging import logger
from app.integrations.supabase_client import get_admin_supabase_client
from app.security.authentication import (
    get_current_user_id,
    get_email_from_token,
    get_org_member_ids,
)


def get_recruiter_owner_ids(
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email"),
) -> Tuple[Set[str], Optional[str]]:
    """
    FastAPI dependency that returns (owner_ids, user_org_id) for the caller.

    Collects every possible identity the logged-in recruiter might be recorded
    under across `profiles` and `members` tables, plus their organization ID.
    Used to scope DB queries so Recruiter A never sees Recruiter B's data.
    """
    if not isinstance(authorization, str):
        authorization = None
    if not isinstance(x_user_email, str):
        x_user_email = None

    if not authorization and not x_user_email:
        return set(), None

    admin_db = get_admin_supabase_client()
    auth_user_id = get_current_user_id(authorization, x_user_email, get_admin_supabase_client)
    user_email = get_email_from_token(authorization) or (
        x_user_email.strip().lower()
        if x_user_email and x_user_email.strip()
        else None
    )

    owner_ids: Set[str] = set()
    if auth_user_id:
        owner_ids.add(auth_user_id)

    user_org_id: Optional[str] = None

    if user_email:
        owner_ids.add(f"user_{user_email}")
        owner_ids.add(user_email)
        try:
            profs = (
                admin_db.table("profiles")
                .select("id")
                .ilike("email", user_email)
                .execute()
                .data
                or []
            )
            for p in profs:
                owner_ids.add(p["id"])
        except Exception as exc:
            logger.error(f"Error resolving profiles by email {user_email}: {exc}")

        try:
            mems = (
                admin_db.table("members")
                .select("id, organization_id")
                .ilike("email", user_email)
                .execute()
                .data
                or []
            )
            for m in mems:
                owner_ids.add(m["id"])
                if not user_org_id and m.get("organization_id"):
                    user_org_id = m.get("organization_id")
        except Exception as exc:
            logger.error(f"Error resolving members by email {user_email}: {exc}")

    return owner_ids, user_org_id


def get_user_org_id(
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email"),
) -> Optional[str]:
    """
    FastAPI dependency that resolves the caller's organization ID.

    Looks up the organization from the `members` table using the caller's
    email (from JWT or the x-user-email header). Returns None if unknown.
    """
    if not authorization and not x_user_email:
        return None

    email: Optional[str] = None
    if authorization:
        email = get_email_from_token(authorization)
    if not email and x_user_email and x_user_email.strip():
        email = x_user_email.strip().lower()

    if not email:
        return None

    try:
        admin_db = get_admin_supabase_client()
        mem_res = (
            admin_db.table("members")
            .select("organization_id")
            .ilike("email", email)
            .limit(1)
            .execute()
        )
        if mem_res and mem_res.data:
            return mem_res.data[0].get("organization_id")
    except Exception as exc:
        logger.error(f"Error resolving org_id for email '{email}': {exc}")

    return None
