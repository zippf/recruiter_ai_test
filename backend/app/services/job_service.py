"""
Job service.

Coordinates job opening use cases: fetching, updating status, enriching
the response with form configuration, and the job-form-config helper.

Extracted from main_commented (1).py — enrich_job_with_form_config (line 3278)
and status update wrappers.
"""
import json
from typing import Any, Dict, Optional

from supabase import Client

from app.repositories.jobs import (
    find_active_job,
    find_job,
    soft_delete_job,
    update_job_processing_status,
    update_job_status,
)


def enrich_job_with_form_config(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge the _form_config sub-object stored inside candidate_view_settings
    back out to the top-level job dict so the frontend can read form fields
    directly.

    Preserves exact behavior from the monolith (line 3278).
    """
    if not row or not isinstance(row, dict):
        return row
    cv_settings = row.get("candidate_view_settings")
    if isinstance(cv_settings, str):
        try:
            cv_settings = json.loads(cv_settings)
        except Exception:
            cv_settings = {}
    if isinstance(cv_settings, dict) and "_form_config" in cv_settings:
        form_cfg = cv_settings.get("_form_config") or {}
        if isinstance(form_cfg, str):
            try:
                form_cfg = json.loads(form_cfg)
            except Exception:
                form_cfg = {}
        if isinstance(form_cfg, dict):
            for k, v in form_cfg.items():
                if v is not None:
                    row[k] = v
    return row


def get_active_job(db: Client, job_id: str) -> Optional[Dict[str, Any]]:
    return find_active_job(db, job_id)


def get_job_record(db: Client, job_id: str) -> Optional[Dict[str, Any]]:
    return find_job(db, job_id)


def delete_job_record(db: Client, job_id: str) -> None:
    return soft_delete_job(db, job_id)


def mark_job_generating(db: Client, job_id: str) -> None:
    return update_job_processing_status(db, job_id, "generating")


def mark_job_skill_approval(db: Client, job_id: str) -> None:
    return update_job_processing_status(db, job_id, "skill_approval")


def confirm_job_record(db: Client, job_id: str) -> None:
    return update_job_status(db, job_id, "confirmed")
