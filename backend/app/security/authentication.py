import base64
import json
from typing import Callable, List, Optional, Set, Tuple

import jwt
from supabase import Client

from app.core.logging import logger
from app.integrations.supabase_client import get_admin_supabase_client


AdminClientFactory = Callable[[], Client]


def get_current_user_id(
    authorization: Optional[str] = None,
    x_user_email: Optional[str] = None,
    admin_client_factory: AdminClientFactory = get_admin_supabase_client,
) -> Optional[str]:
    if not isinstance(authorization, str):
        authorization = None
    if not isinstance(x_user_email, str):
        x_user_email = None

    # Direct email lookup supports the trusted internal header used by the app.
    if x_user_email:
        clean_email = x_user_email.strip().lower()
        try:
            db = admin_client_factory()
            profile = (
                db.table("profiles").select("id").ilike("email", clean_email).execute()
            )
            if profile.data:
                return profile.data[0]["id"]
            member = (
                db.table("members").select("id").ilike("email", clean_email).execute()
            )
            if member.data:
                return member.data[0]["id"]
            return f"user_{clean_email}"
        except Exception as exc:
            logger.error(f"Failed to resolve member by X-User-Email: {exc}")
            return f"user_{clean_email}"

    if not authorization:
        return None

    token = None
    if authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    elif authorization.startswith("eyJ"):
        token = authorization
    if not token:
        return None

    # Legacy SSO tokens are base64-encoded JSON rather than JWTs.
    try:
        sso_data = json.loads(base64.b64decode(token).decode("utf-8"))
        if sso_data and sso_data.get("id"):
            return sso_data["id"]
        if sso_data and sso_data.get("email"):
            clean_email = sso_data["email"].strip().lower()
            db = admin_client_factory()
            profile = (
                db.table("profiles").select("id").ilike("email", clean_email).execute()
            )
            if profile.data:
                return profile.data[0]["id"]
            member = (
                db.table("members").select("id").ilike("email", clean_email).execute()
            )
            if member.data:
                return member.data[0]["id"]
            return f"user_{clean_email}"
    except Exception:
        pass

    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        sub_id = payload.get("sub")
        email = payload.get("email")
        if email:
            db = admin_client_factory()
            profile = (
                db.table("profiles")
                .select("id")
                .ilike("email", email.strip().lower())
                .execute()
            )
            if profile.data:
                return profile.data[0]["id"]
        return sub_id
    except Exception as exc:
        logger.error(f"Failed to decode JWT: {exc}")
        return None


def get_email_from_token(authorization: Optional[str]) -> Optional[str]:
    """Extract the normalized email claim from a bearer JWT."""
    if not authorization:
        return None
    token = (
        authorization.split(" ", 1)[1]
        if authorization.startswith("Bearer ")
        else authorization
    )
    if not token.startswith("eyJ"):
        return None
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        email = payload.get("email") or (payload.get("user_metadata") or {}).get(
            "email"
        )
        return email.strip().lower() if email else None
    except Exception as exc:
        logger.error(f"Failed to extract email from JWT: {exc}")
        return None


def resolve_member_id_from_auth(
    authorization: Optional[str],
    admin_client_factory: AdminClientFactory = get_admin_supabase_client,
) -> Optional[str]:
    """Resolve members.id by email, then fall back to the JWT subject."""
    if not authorization:
        return None

    admin_db = admin_client_factory()
    email = get_email_from_token(authorization)
    if email:
        try:
            member = (
                admin_db.table("members")
                .select("id")
                .ilike("email", email)
                .limit(1)
                .execute()
            )
            if member.data:
                return member.data[0]["id"]
        except Exception as exc:
            logger.error(f"Failed to resolve member_id from email '{email}': {exc}")

    try:
        raw_token = authorization.replace("Bearer ", "").strip()
        payload = jwt.decode(raw_token, options={"verify_signature": False})
        subject = payload.get("sub")
        if subject:
            member = (
                admin_db.table("members")
                .select("id")
                .eq("id", subject)
                .limit(1)
                .execute()
            )
            if member.data:
                return member.data[0]["id"]
    except Exception as exc:
        logger.debug(f"Fallback sub lookup failed: {exc}")
    return None


def get_recruiter_owner_ids(
    authorization: Optional[str],
    admin_client_factory: AdminClientFactory = get_admin_supabase_client,
) -> Tuple[Set[str], Optional[str]]:
    """Return all profile/member IDs and the recruiter's organization ID."""
    if not authorization:
        return set(), None

    admin_db = admin_client_factory()
    auth_user_id = get_current_user_id(
        authorization, admin_client_factory=admin_client_factory
    )
    user_email = get_email_from_token(authorization)
    owner_ids = {auth_user_id} if auth_user_id else set()
    user_org_id = None

    if user_email:
        try:
            profiles = (
                admin_db.table("profiles")
                .select("id")
                .ilike("email", user_email)
                .execute()
                .data
                or []
            )
            owner_ids.update(profile["id"] for profile in profiles)
        except Exception as exc:
            logger.error(f"Error resolving profiles by email {user_email}: {exc}")
        try:
            members = (
                admin_db.table("members")
                .select("id, organization_id")
                .ilike("email", user_email)
                .execute()
                .data
                or []
            )
            for member in members:
                owner_ids.add(member["id"])
                user_org_id = user_org_id or member.get("organization_id")
        except Exception as exc:
            logger.error(f"Error resolving members by email {user_email}: {exc}")

    return owner_ids, user_org_id


def get_user_org_id(
    authorization: Optional[str] = None,
    x_user_email: Optional[str] = None,
    admin_client_factory: AdminClientFactory = get_admin_supabase_client,
) -> Optional[str]:
    if not isinstance(authorization, str):
        authorization = None
    if not isinstance(x_user_email, str):
        x_user_email = None

    user_id = get_current_user_id(authorization, x_user_email, admin_client_factory)
    email = x_user_email or (
        user_id.replace("user_", "")
        if user_id and user_id.startswith("user_")
        else None
    )
    email = email or (get_email_from_token(authorization) if authorization else None)
    if not user_id and not email:
        return None

    try:
        db = admin_client_factory()
        if user_id and not user_id.startswith("user_"):
            result = (
                db.table("members")
                .select("organization_id")
                .eq("id", user_id)
                .execute()
            )
            if result.data and result.data[0].get("organization_id"):
                return result.data[0]["organization_id"]
        if email:
            clean_email = email.strip().lower()
            result = (
                db.table("members")
                .select("organization_id")
                .ilike("email", clean_email)
                .limit(1)
                .execute()
            )
            if result.data and result.data[0].get("organization_id"):
                return result.data[0]["organization_id"]
            roles = (
                db.table("member_roles")
                .select("roles(organization_id), members!inner(email)")
                .ilike("members.email", clean_email)
                .execute()
            )
            if roles.data and roles.data[0].get("roles"):
                role = roles.data[0]["roles"]
                if isinstance(role, dict) and role.get("organization_id"):
                    return role["organization_id"]
        organizations = db.table("organizations").select("id").limit(1).execute()
        if organizations.data and organizations.data[0].get("id"):
            return organizations.data[0]["id"]
    except Exception as exc:
        logger.error(f"Failed to resolve organization_id: {exc}")
    return None


def get_org_member_ids(db: Client, org_id: str) -> List[str]:
    """Return member IDs plus matching profile IDs for tenant-scoped queries."""
    if not org_id:
        return []
    try:
        members = (
            db.table("members")
            .select("id, email")
            .eq("organization_id", org_id)
            .execute()
            .data
            or []
        )
        ids = [member["id"] for member in members if "id" in member]
        emails = [
            member["email"].strip().lower() for member in members if member.get("email")
        ]
        if emails:
            profiles = (
                db.table("profiles").select("id").in_("email", emails).execute().data
                or []
            )
            ids.extend(profile["id"] for profile in profiles if "id" in profile)
        return list(set(ids))
    except Exception as exc:
        logger.error(f"Error fetching member IDs for org {org_id}: {exc}")
        return []


import uuid

def filter_valid_uuids(ids: set | list) -> list:
    valid = []
    for raw_id in ids:
        try:
            uuid.UUID(raw_id)
            valid.append(raw_id)
        except Exception:
            pass
    return valid


def obfuscate_id(raw_id: str) -> str:
    if not raw_id:
        return ""
    try:
        u = uuid.UUID(raw_id)
        encoded = base64.urlsafe_b64encode(u.bytes).decode("utf-8").rstrip("=")
        return f"rec_{encoded}"
    except Exception:
        return raw_id


def deobfuscate_id(obfuscated_id: str) -> str:
    if not obfuscated_id:
        return ""
    clean_id = obfuscated_id
    if clean_id.startswith("rec_"):
        clean_id = clean_id[4:]
    try:
        padding = "=" * (4 - len(clean_id) % 4)
        bytes_data = base64.urlsafe_b64decode(clean_id + padding)
        return str(uuid.UUID(bytes=bytes_data))
    except Exception:
        return obfuscated_id
