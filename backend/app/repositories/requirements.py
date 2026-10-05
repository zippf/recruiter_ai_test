from typing import Iterable, Optional

from supabase import Client


def list_active_requirements_for_members(
    db: Client, member_ids: Iterable[str]
) -> Optional[list[dict]]:
    ids = list(member_ids)
    if not ids:
        return None
    result = (
        db.table("requirements")
        .select("*")
        .eq("is_deleted", False)
        .in_("created_by", ids)
        .execute()
    )
    return result.data if result.data else None


def list_active_requirements_for_owners(
    db: Client, owner_ids: Iterable[str]
) -> list[dict]:
    ids = list(owner_ids)
    if not ids:
        return []
    result = (
        db.table("requirements")
        .select("*")
        .in_("created_by", ids)
        .eq("is_deleted", False)
        .execute()
    )
    return result.data or []


def list_active_requirements(db: Client) -> list[dict]:
    return (
        db.table("requirements").select("*").eq("is_deleted", False).execute().data
        or []
    )


def insert_requirement(db: Client, payload: dict):
    return db.table("requirements").insert(payload).execute()


def find_requirement(db: Client, requirement_id: str):
    return db.table("requirements").select("*").eq("id", requirement_id).execute()


def count_active_jobs_for_requirement(db: Client, requirement_id: str) -> int:
    result = (
        db.table("job_openings")
        .select("id")
        .eq("requirement_id", requirement_id)
        .eq("is_deleted", False)
        .execute()
    )
    return len(result.data) if result.data else 0


def soft_delete_jobs_for_requirement(db: Client, requirement_id: str):
    return (
        db.table("job_openings")
        .update({"is_deleted": True})
        .eq("requirement_id", requirement_id)
        .execute()
    )


def update_requirement_record(db: Client, requirement_id: str, update_data: dict):
    return (
        db.table("requirements").update(update_data).eq("id", requirement_id).execute()
    )


def soft_delete_requirement(db: Client, requirement_id: str):
    return (
        db.table("requirements")
        .update({"is_deleted": True})
        .eq("id", requirement_id)
        .execute()
    )
