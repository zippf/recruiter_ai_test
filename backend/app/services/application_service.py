from typing import Dict, Any, List, Optional
"""
Application Service module.

This service acts as the orchestration layer between the HTTP routes (API) and
the data access layer (Repositories). It enforces business rules and manages 
workflows related to candidate applications.
"""

from supabase import Client

from app.core.logging import logger
from app.services.matching_service import evaluate_candidate_matching_with_history
from app.services.notification_service import send_application_confirmation_email

from app.repositories.applications import (
    find_application,
    find_application_containing_question,
    find_application_questions,
    find_job_custom_stages,
    insert_interview_stage,
    list_application_stages,
    list_stage_ids,
    update_application_questions,
    update_application_stage_record,
    update_application_status,
)


def get_application_record(db: Client, application_id: str):
    """
    Retrieve a single application record by its ID.
    
    Args:
        db: The Supabase client instance
        application_id: The UUID of the application
    """
    return find_application(db, application_id)


def accept_application_record(db: Client, application_id: str):
    """
    Accept an application by updating its status.
    This might trigger further workflow steps (e.g. notifications) in the future.
    """
    return update_application_status(db, application_id, "accepted")


def reject_application_record(db: Client, application_id: str):
    """
    Reject an application by updating its status.
    """
    return update_application_status(db, application_id, "rejected")


def get_application_stages_record(db: Client, application_id: str):
    """
    Retrieve all custom or default stages an application has progressed through.
    """
    return list_application_stages(db, application_id)


def update_application_stage_record_service(
    db: Client, application_id: str, stage: str, stage_status: str, notes: str
):
    """
    Update a specific interview or progression stage for an application.
    """
    return update_application_stage_record(
        db, application_id, stage, stage_status, notes
    )


def get_job_custom_stages(db: Client, job_id: str):
    """
    Retrieve all custom interview stages defined for a specific job.
    """
    return find_job_custom_stages(db, job_id)


def get_stage_ids(db: Client, application_id: str):
    """
    Get a list of stage IDs currently associated with an application.
    """
    return list_stage_ids(db, application_id)


def add_interview_stage(db: Client, payload: dict):
    """
    Add a new interview stage record.
    """
    return insert_interview_stage(db, payload)


def get_application_questions(db: Client, application_id: str):
    """
    Retrieve screening questions and answers for a given application.
    """
    return find_application_questions(db, application_id)


def find_question_application(db: Client, question_id: str):
    """
    Look up the application ID that a particular question belongs to.
    """
    return find_application_containing_question(db, question_id)


def save_application_questions(db: Client, application_id: str, questions: list[dict]):
    """
    Save or update the screening questions and their answers for an application.
    """
    return update_application_questions(db, application_id, questions)


def auto_link_candidate_to_job(db: Client, job_id: str, cand_id: str, cand_data: Dict[str, Any]):
    try:
        skills_res = db.table("job_opening_skills").select("skills").eq("job_opening_id", job_id).execute()
        approved_skills = skills_res.data[0].get("skills", []) if skills_res.data else []
        
        cand_skills = [s.lower() for s in (cand_data.get("skills") or [])]
        cand_raw_text = cand_data.get("raw_text") or cand_data.get("parsed_resume_json", {}).get("raw_text") or ""
        
        matched_score, match_reason, strengths, skill_gaps = evaluate_candidate_matching_with_history(
            db, cand_id, job_id, approved_skills, cand_skills, cand_raw_text
        )
        
        app_res = db.table("applications").upsert({
            "candidate_id": cand_id,
            "job_opening_id": job_id,
            "fuzzy_score": matched_score,
            "match_score": int(matched_score),
            "match_reason": match_reason,
            "strengths": strengths[:3],
            "skill_gaps": skill_gaps[:3],
            "screening_status": "pending",
            "stage": "screening",
            "stage_status": "pending"
        }, on_conflict="candidate_id,job_opening_id").execute()
        
        if app_res.data:
            new_app = app_res.data[0]
            try:
                db.table("activity_log").insert({
                    "action": "candidate_linked",
                    "entity_type": "applications",
                    "entity_id": new_app["id"],
                    "actor_name": "System",
                    "metadata": {"candidate_name": cand_data.get("full_name"), "source": "public_apply"}
                }).execute()
            except Exception as log_err:
                logger.error(f"Failed to log auto-link activity: {log_err}")
    except Exception as e:
        logger.error(f"Error auto-linking candidate {cand_id} to job {job_id}: {e}")



def handle_candidate_application(candidate_id: str, email: str, full_name: str, job_id: str, form_responses: dict, db: Client):
    email_sent = False
    email_error = None
    try:
        # Check if application already exists
        app_check = db.table("applications").select("id").eq("candidate_id", candidate_id).eq("job_opening_id", job_id).execute()
        
        application_id = None
        
        if app_check.data:
            application_id = app_check.data[0]["id"]
        else:
            # Create new application
            app_res = db.table("applications").insert({
                "candidate_id": candidate_id,
                "job_opening_id": job_id,
                "screening_status": "pending",
                "stage": "screening",
                "stage_status": "pending"
            }).execute()
            if app_res.data:
                application_id = app_res.data[0]["id"]
        
        if application_id:
            # Fetch job title and client name for the email
            job_title = "Active Opening"
            client_name = "Generic Client"
            try:
                job_res = db.table("job_openings").select("title, requirements(clients(name))").eq("id", job_id).execute()
                if job_res.data:
                    row = job_res.data[0]
                    job_title = row.get("title") or "Active Opening"
                    req = row.get("requirements") or {}
                    cli = req.get("clients") or {}
                    client_name = cli.get("name") or "Generic Client"
            except Exception as je:
                logger.error(f"Failed to fetch job details for confirmation email: {je}")
                
            # Call confirmation email sending synchronously
            try:
                send_application_confirmation_email(
                    to_email=email,
                    full_name=full_name,
                    job_title=job_title,
                    client_name=client_name,
                    application_id=application_id,
                    form_responses=form_responses
                )
                email_sent = True
            except Exception as ee:
                logger.error(f"Failed to send application confirmation email: {ee}")
                email_error = str(ee)
            
        return application_id, email_sent, email_error
    except Exception as e:
        logger.error(f"Error in handle_candidate_application: {e}")
        return None, False, str(e)



