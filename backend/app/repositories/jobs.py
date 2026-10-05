from collections.abc import Iterable

from supabase import Client


_JOB_COLUMNS = "*, requirements(id, title, clients(name))"
_JOB_DETAIL_COLUMNS = "*, requirements(id, title, created_by, clients(name))"


def _list_requirement_ids(db: Client, owner_ids: Iterable[str]) -> list[str]:
    ids = list(owner_ids)
    if not ids:
        return []
    result = (
        db.table("requirements")
        .select("id")
        .in_("created_by", ids)
        .eq("is_deleted", False)
        .execute()
    )
    return [row["id"] for row in (result.data or []) if row.get("id")]


def list_active_jobs_for_members(
    db: Client, member_ids: Iterable[str]
) -> list[dict] | None:
    requirement_ids = _list_requirement_ids(db, member_ids)
    if not requirement_ids:
        return None
    result = (
        db.table("job_openings")
        .select(_JOB_COLUMNS)
        .eq("is_deleted", False)
        .in_("requirement_id", requirement_ids)
        .execute()
    )
    return result.data if result.data else None


def list_active_jobs_for_owners(db: Client, owner_ids: Iterable[str]) -> list[dict]:
    requirement_ids = _list_requirement_ids(db, owner_ids)
    if not requirement_ids:
        return []
    result = (
        db.table("job_openings")
        .select(_JOB_COLUMNS)
        .eq("is_deleted", False)
        .in_("requirement_id", requirement_ids)
        .execute()
    )
    return result.data or []


def list_active_jobs(db: Client) -> list[dict]:
    return (
        db.table("job_openings")
        .select(_JOB_COLUMNS)
        .eq("is_deleted", False)
        .execute()
        .data
        or []
    )


def find_active_job(db: Client, job_id: str):
    return (
        db.table("job_openings")
        .select(_JOB_DETAIL_COLUMNS)
        .eq("id", job_id)
        .eq("is_deleted", False)
        .execute()
    )


def find_job(db: Client, job_id: str):
    return db.table("job_openings").select("*").eq("id", job_id).execute()


def soft_delete_job(db: Client, job_id: str):
    return (
        db.table("job_openings").update({"is_deleted": True}).eq("id", job_id).execute()
    )


def update_job_status(db: Client, job_id: str, status: str):
    return (
        db.table("job_openings").update({"status": status}).eq("id", job_id).execute()
    )


def update_job_processing_status(db: Client, job_id: str, status: str):
    return (
        db.table("job_openings")
        .update({"processing_status": status})
        .eq("id", job_id)
        .execute()
    )
