from typing import Optional, Set, Tuple

from fastapi import Header
from supabase import Client

from app.integrations.supabase_client import get_admin_supabase_client, get_supabase, get_safe_supabase_client
from app.security.callback_auth import verify_callback_secret
from app.security.authentication import (
    get_current_user_id as _get_current_user_id,
    get_org_member_ids as _get_org_member_ids,
    get_recruiter_owner_ids as _get_recruiter_owner_ids,
    get_user_org_id as _get_user_org_id,
    resolve_member_id_from_auth as _resolve_member_id_from_auth,
)


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email"),
) -> Optional[str]:
    return _get_current_user_id(authorization, x_user_email, get_admin_supabase_client)


def get_current_user_id_with_factory(
    authorization: Optional[str],
    x_user_email: Optional[str],
    admin_client_factory,
) -> Optional[str]:
    return _get_current_user_id(authorization, x_user_email, admin_client_factory)


def resolve_member_id_from_auth(authorization: Optional[str]) -> Optional[str]:
    return _resolve_member_id_from_auth(authorization, get_admin_supabase_client)


def resolve_member_id_from_auth_with_factory(
    authorization: Optional[str], admin_client_factory
):
    return _resolve_member_id_from_auth(authorization, admin_client_factory)


def get_recruiter_owner_ids(
    authorization: Optional[str],
) -> Tuple[Set[str], Optional[str]]:
    return _get_recruiter_owner_ids(authorization, get_admin_supabase_client)


def get_recruiter_owner_ids_with_factory(
    authorization: Optional[str], admin_client_factory
):
    return _get_recruiter_owner_ids(authorization, admin_client_factory)


def get_user_org_id(
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email"),
) -> Optional[str]:
    return _get_user_org_id(authorization, x_user_email, get_admin_supabase_client)


def get_user_org_id_with_factory(
    authorization: Optional[str], x_user_email: Optional[str], admin_client_factory
) -> Optional[str]:
    return _get_user_org_id(authorization, x_user_email, admin_client_factory)


def get_org_member_ids(db: Client, org_id: str):
    return _get_org_member_ids(db, org_id)
