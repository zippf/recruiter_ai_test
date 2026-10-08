from collections.abc import Iterable

from supabase import Client


_CANDIDATE_COLUMNS = "*"


def list_active_candidates_for_members(
    db: Client, member_ids: Iterable[str]
) -> list[dict] | None:
    ids = list(member_ids)
    if not ids:
        return None
    result = (
        db.table("candidates")
        .select(_CANDIDATE_COLUMNS)
        .eq("is_deleted", False)
        .in_("uploaded_by", ids)
        .execute()
    )
    return result.data if result.data else None


def list_active_candidates(db: Client) -> list[dict]:
    return (
        db.table("candidates")
        .select(_CANDIDATE_COLUMNS)
        .eq("is_deleted", False)
        .execute()
        .data
        or []
    )


def find_active_candidate(db: Client, candidate_id: str):
    return (
        db.table("candidates")
        .select(_CANDIDATE_COLUMNS)
        .eq("id", candidate_id)
        .eq("is_deleted", False)
        .execute()
    )


def find_candidate(db: Client, candidate_id: str):
    return (
        db.table("candidates")
        .select(_CANDIDATE_COLUMNS)
        .eq("id", candidate_id)
        .execute()
    )


def find_candidates_by_email(
    db: Client, email: str, job_id: str | None, only_unassigned: bool = False
):
    query = db.table("candidates").select(_CANDIDATE_COLUMNS).eq("email", email)
    if job_id:
        query = query.eq("job_id", job_id)
    elif only_unassigned:
        query = query.is_("job_id", "null")
    return query.execute()


def update_candidate_record(db: Client, candidate_id: str, update_data: dict):
    return db.table("candidates").update(update_data).eq("id", candidate_id).execute()


def soft_delete_candidate(db: Client, candidate_id: str):
    return (
        db.table("candidates")
        .update({"is_deleted": True})
        .eq("id", candidate_id)
        .execute()
    )
