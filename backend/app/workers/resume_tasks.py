"""
Resume processing worker.

Background tasks related to resume files:
- Downloading Google Drive resumes and parsing them
- Generating fallback screening questions locally

Extracted from main_commented (1).py lines 1165–1220 and 5978–6008.
"""
import uuid
from typing import Dict, List

import httpx

from app.core.config import SUPABASE_KEY, SUPABASE_URL
from app.core.logging import logger
from app.integrations.google_drive import get_drive_download_url, is_google_drive_url
from app.integrations.supabase_client import get_safe_supabase_client
from app.services.notification_service import create_system_notification, log_activity_event
from app.workers.resume_parser import extract_text_from_bytes


def download_resumes_background(candidates_list: List[Dict], jwt_token: str) -> None:
    """
    Background task: download Google Drive resume links and save extracted text.

    Runs after candidates are already created in the DB so the user doesn't wait.
    Sends success/error notifications to the uploading recruiter.

    Extracted from main_commented (1).py line 1165.
    """
    logger.info(
        f"Starting background download of Google Drive resumes for {len(candidates_list)} candidates"
    )
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)

    for item in candidates_list:
        cand_id = item.get("id")
        url = item.get("resume_url")
        email = item.get("email")

        if not cand_id or not url:
            continue

        cand_name = email
        uploaded_by = None
        try:
            cand_res = (
                db.table("candidates").select("full_name, uploaded_by").eq("id", cand_id).execute()
            )
            if cand_res.data:
                cand_name = cand_res.data[0].get("full_name") or email
                uploaded_by = cand_res.data[0].get("uploaded_by")
        except Exception as exc:
            logger.error(f"Failed to resolve candidate details in download_resumes_background: {exc}")

        try:
            download_url = get_drive_download_url(url)
            logger.info(f"Downloading resume for {email} from: {download_url}")

            with httpx.Client(follow_redirects=True) as client:
                res = client.get(download_url, timeout=30.0)
                if res.status_code != 200:
                    logger.error(
                        f"Failed to download GD resume for {email}: HTTP {res.status_code}"
                    )
                    if uploaded_by:
                        create_system_notification(
                            db, uploaded_by, "GD Resume Download Failed",
                            f"Failed to download Google Drive resume for candidate '{cand_name}' (HTTP {res.status_code}).",
                            "error",
                            {"candidate_id": cand_id, "candidate_name": cand_name, "status": "failed"},
                        )
                        log_activity_event(
                            db, action="candidate_cv_download_failed",
                            entity_type="candidates", entity_id=cand_id,
                            actor_name="System",
                            metadata={"candidate_name": cand_name, "status_code": res.status_code},
                        )
                    continue

                content_type = res.headers.get("content-type", "")
                raw_text = extract_text_from_bytes(res.content, content_type)

                db.table("candidates").update({"raw_text": raw_text}).eq("id", cand_id).execute()
                logger.info(f"Resume text extracted and saved for candidate {cand_id}")

                if uploaded_by:
                    create_system_notification(
                        db, uploaded_by, "Resume Parsed Successfully",
                        f"Resume for candidate '{cand_name}' has been downloaded and parsed.",
                        "info", {"candidate_id": cand_id, "candidate_name": cand_name},
                    )
                    log_activity_event(
                        db, action="candidate_cv_downloaded",
                        entity_type="candidates", entity_id=cand_id,
                        actor_name="System", metadata={"candidate_name": cand_name},
                    )
        except Exception as exc:
            logger.error(f"Error processing resume download for candidate {cand_id}: {exc}")


def generate_questions_background(
    app_id: str,
    candidate_name: str,
    skills: List[str],
    exp_years: int,
    raw_text: str,
    jwt_token: str,
) -> None:
    """
    Local fallback: generate 3 template screening questions and save them.

    Used when n8n question generation is unavailable.

    Extracted from main_commented (1).py line 5978.
    """
    logger.info(f"Starting background question generation for application {app_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)

    try:
        questions = [
            {
                "question": f"Can you detail your experience working with {skills[0] if skills else 'modern tech'} and how you applied it in your previous role?",
                "difficulty": "easy",
            },
            {
                "question": "How do you handle client-side rendering bottlenecks when managing large datagrid lists?",
                "difficulty": "medium",
            },
            {
                "question": "Describe a time you solved a challenging concurrency/state synchronization issue.",
                "difficulty": "hard",
            },
        ]

        questions_array = []
        for idx, q in enumerate(questions):
            questions_array.append({
                "id": str(uuid.uuid4()),
                "question": q["question"],
                "difficulty": q["difficulty"],
                "question_order": idx + 1,
                "ai_generated": True,
                "modified": False,
            })

        db.table("applications").update(
            {"screening_questions": questions_array}
        ).eq("id", app_id).execute()
    except Exception as exc:
        logger.error(f"Error generating screening questions: {exc}")
