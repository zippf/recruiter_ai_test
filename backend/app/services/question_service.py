"""
Question service.

Handles screening question operations on applications:
- Adding questions to an application
- Ensuring all questions have IDs (healing legacy data)

Extracted from main_commented (1).py lines 6013–6033 and surrounding endpoints.
"""
import uuid
from typing import Any, Dict, List

from supabase import Client

from app.core.logging import logger


def ensure_questions_have_ids(
    questions_list: list, app_id: str, db: Client
) -> list:
    """
    Guarantee every question dict in the list has an `id` field.

    Writes the repaired list back to the database if any IDs were missing.
    Preserves the original healing behavior from the monolith (line 6013).
    """
    modified = False
    healed_list = []
    for q in (questions_list or []):
        if not isinstance(q, dict):
            continue
        if not q.get("id"):
            q["id"] = str(uuid.uuid4())
            modified = True
        q["application_id"] = app_id
        healed_list.append(q)

    if modified:
        try:
            db.table("applications").update(
                {"screening_questions": healed_list}
            ).eq("id", app_id).execute()
        except Exception as exc:
            logger.error(f"Failed to save auto-healed screening question IDs: {exc}")

    return healed_list


def add_question_to_application(
    db: Client,
    application_id: str,
    question: str,
    difficulty: str = "medium",
) -> Dict[str, Any]:
    """
    Append a manually-created screening question to an application's
    screening_questions JSONB array.

    Returns the new question dict.
    """
    app_res = db.table("applications").select("*").eq("id", application_id).execute()
    if not app_res.data:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Application not found")

    app_rec = app_res.data[0]
    questions_list = app_rec.get("screening_questions") or []
    max_order = max([q.get("question_order", 0) for q in questions_list]) if questions_list else 0

    new_q: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "question": question,
        "difficulty": difficulty,
        "question_order": max_order + 1,
        "ai_generated": False,
        "modified": False,
    }
    questions_list.append(new_q)

    db.table("applications").update(
        {"screening_questions": questions_list}
    ).eq("id", application_id).execute()

    return new_q
