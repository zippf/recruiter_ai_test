"""
Skills repository.

Owns all Supabase queries against the `job_opening_skills` table.
Skills are stored as a JSONB column keyed by job_opening_id.

Extracted from main_commented (1).py — all `job_opening_skills` table access.
"""
from typing import Any, Dict, List, Optional

from supabase import Client


def get_skills_for_job(db: Client, job_opening_id: str) -> List[Dict[str, Any]]:
    """Return the approved skills list for a job opening, or [] if none."""
    res = (
        db.table("job_opening_skills")
        .select("skills")
        .eq("job_opening_id", job_opening_id)
        .execute()
    )
    if res.data:
        return res.data[0].get("skills") or []
    return []


def save_skills_for_job(
    db: Client, job_opening_id: str, skills: List[Dict[str, Any]]
) -> None:
    """
    Upsert the skills list for a job opening.

    The `job_opening_id` column is the unique conflict key.
    """
    db.table("job_opening_skills").upsert(
        {"job_opening_id": job_opening_id, "skills": skills},
        on_conflict="job_opening_id",
    ).execute()
