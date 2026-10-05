"""
Questions repository.

Owns all Supabase queries related to screening questions, which are stored
as a JSONB array (`screening_questions`) on the `applications` table.

Extracted from main_commented (1).py — all screening_questions access patterns.
"""
import uuid
from typing import Any, Dict, List, Optional

from supabase import Client


def get_questions_for_application(
    db: Client, application_id: str
) -> List[Dict[str, Any]]:
    """Fetch the raw screening_questions JSONB array for an application."""
    res = (
        db.table("applications")
        .select("screening_questions")
        .eq("id", application_id)
        .execute()
    )
    if not res.data:
        return []
    return res.data[0].get("screening_questions") or []


def find_application_containing_question(
    db: Client, question_id: str
) -> Optional[Dict[str, Any]]:
    """
    Find the application row that contains a given question ID in its
    screening_questions JSONB column.

    Uses the Supabase `cs` (contains) filter and falls back to a full scan
    when the index-level filter doesn't match, preserving the original behavior.
    """
    res = (
        db.table("applications")
        .select("*")
        .filter("screening_questions", "cs", f'[{{"id": "{question_id}"}}]')
        .execute()
    )
    if not res.data:
        # Full-scan fallback (matches monolith behavior)
        res = db.table("applications").select("*").execute()

    for row in res.data or []:
        qs = row.get("screening_questions") or []
        for q in qs:
            if q.get("id") == question_id:
                return row
    return None


def update_questions_for_application(
    db: Client, application_id: str, questions: List[Dict[str, Any]]
) -> None:
    """Persist the updated screening_questions list back to the application row."""
    db.table("applications").update(
        {"screening_questions": questions}
    ).eq("id", application_id).execute()


def find_application_by_question_id(
    db: Client, question_id: str
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Return (application_row, question_dict) for the given question ID,
    or (None, None) if not found.
    """
    app_row = find_application_containing_question(db, question_id)
    if not app_row:
        return None, None
    for q in (app_row.get("screening_questions") or []):
        if q.get("id") == question_id:
            return app_row, q
    return None, None
