from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks
from typing import Optional, List, Dict, Any
from supabase import Client

from app.core.logging import logger
from app.api.dependencies import get_supabase, get_admin_supabase_client, get_current_user_id, get_user_org_id
from app.schemas.common import CandidateModel, CandidateUpdateModel, CSVUploadModel
from app.security.authentication import filter_valid_uuids
from app.security.tenant_access import get_recruiter_owner_ids
from app.security.authorization import deobfuscate_id
from app.services.application_service import handle_candidate_application, auto_link_candidate_to_job
from app.workers.resume_tasks import download_resumes_background
from app.workers.notification_tasks import trigger_whatsapp_notification_background
from app.services.notification_service import create_system_notification, log_activity_event

def is_google_drive_url(url: str) -> bool:
    if not url: return False
    return 'drive.google.com' in url

router = APIRouter()

@router.get("/api/v1/candidates")
async def get_candidates(
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    if recruiter_owner_ids:
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        user_reqs = []
        if valid_uuids:
            user_reqs = admin_db.table("requirements").select("id").in_("created_by", valid_uuids).eq("is_deleted", False).execute().data or []
        req_ids = [r["id"] for r in user_reqs]
        
        user_job_ids = set()
        if req_ids:
            user_jobs_by_req = admin_db.table("job_openings").select("id").in_("requirement_id", req_ids).eq("is_deleted", False).execute().data or []
            for j in user_jobs_by_req:
                user_job_ids.add(j["id"])
                
        user_app_cands = set()
        if user_job_ids:
            user_apps = admin_db.table("applications").select("candidate_id").in_("job_opening_id", list(user_job_ids)).execute().data or []
            for a in user_apps:
                if a.get("candidate_id"):
                    user_app_cands.add(a["candidate_id"])
                    
        all_cands = admin_db.table("candidates").select("*").eq("is_deleted", False).execute().data or []
        data = [
            c for c in all_cands 
            if c.get("uploaded_by") in recruiter_owner_ids
            or (not c.get("uploaded_by") and c.get("id") in user_app_cands)
            or (c.get("job_id") and c.get("job_id") in user_job_ids)
        ]
        logger.info(f"[get_candidates] recruiter_owner_ids={len(recruiter_owner_ids)} total_cands={len(all_cands)} recruiter_cands={len(data)}")
    else:
        data = []
    for cand in data:
        if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
            if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
                cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
    return data

# ENDPOINT: GET /api/v1/candidates/{candidate_id} — fetch one candidate's
# full profile.


@router.get("/api/v1/candidates")
async def get_candidates(
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    if recruiter_owner_ids:
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        user_reqs = []
        if valid_uuids:
            user_reqs = admin_db.table("requirements").select("id").in_("created_by", valid_uuids).eq("is_deleted", False).execute().data or []
        req_ids = [r["id"] for r in user_reqs]
        
        user_job_ids = set()
        if req_ids:
            user_jobs_by_req = admin_db.table("job_openings").select("id").in_("requirement_id", req_ids).eq("is_deleted", False).execute().data or []
            for j in user_jobs_by_req:
                user_job_ids.add(j["id"])
                
        user_app_cands = set()
        if user_job_ids:
            user_apps = admin_db.table("applications").select("candidate_id").in_("job_opening_id", list(user_job_ids)).execute().data or []
            for a in user_apps:
                if a.get("candidate_id"):
                    user_app_cands.add(a["candidate_id"])
                    
        all_cands = admin_db.table("candidates").select("*").eq("is_deleted", False).execute().data or []
        data = [
            c for c in all_cands 
            if c.get("uploaded_by") in recruiter_owner_ids
            or (not c.get("uploaded_by") and c.get("id") in user_app_cands)
            or (c.get("job_id") and c.get("job_id") in user_job_ids)
        ]
        logger.info(f"[get_candidates] recruiter_owner_ids={len(recruiter_owner_ids)} total_cands={len(all_cands)} recruiter_cands={len(data)}")
    else:
        data = []
    for cand in data:
        if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
            if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
                cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
    return data

# ENDPOINT: GET /api/v1/candidates/{candidate_id} — fetch one candidate's
# full profile.

@router.get("/api/v1/candidates/{candidate_id}")
async def get_candidate_details(
    candidate_id: str, 
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, _ = get_recruiter_owner_ids(authorization, x_user_email)
    
    res = admin_db.table("candidates").select("*").eq("id", candidate_id).eq("is_deleted", False).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    cand = res.data[0]
    
    if recruiter_owner_ids:
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        user_reqs = []
        if valid_uuids:
            user_reqs = admin_db.table("requirements").select("id").in_("created_by", valid_uuids).eq("is_deleted", False).execute().data or []
        req_ids = [r["id"] for r in user_reqs]
        user_job_ids = set()
        if req_ids:
            user_jobs = admin_db.table("job_openings").select("id").in_("requirement_id", req_ids).eq("is_deleted", False).execute().data or []
            for j in user_jobs:
                user_job_ids.add(j["id"])
                
        user_app_cands = set()
        if user_job_ids:
            user_apps = admin_db.table("applications").select("candidate_id").in_("job_opening_id", list(user_job_ids)).execute().data or []
            for a in user_apps:
                if a.get("candidate_id"):
                    user_app_cands.add(a["candidate_id"])
                    
        is_owned = (
            cand.get("uploaded_by") in recruiter_owner_ids or
            (not cand.get("uploaded_by") and cand.get("id") in user_app_cands) or
            (cand.get("job_id") and cand.get("job_id") in user_job_ids)
        )
        if not is_owned:
            raise HTTPException(status_code=404, detail="Candidate not found")

    if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
        if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
            cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
    return cand

# ENDPOINT: PUT /api/v1/candidates/{candidate_id} — update a candidate's
# profile fields.


@router.put("/api/v1/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, cand: CandidateUpdateModel, db: Client = Depends(get_supabase)):
    current_res = db.table("candidates").select("*").eq("id", candidate_id).execute()
    if not current_res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    current_cand = current_res.data[0]

    if cand.email is not None and cand.email.strip().lower() != (current_cand.get("email") or "").strip().lower():
        dup_check = db.table("candidates").select("id").eq("email", cand.email.strip()).execute()
        if dup_check.data:
            other_ids = [r["id"] for r in dup_check.data if r["id"] != candidate_id]
            if other_ids:
                raise HTTPException(
                    status_code=409, 
                    detail=f"A candidate with the email address '{cand.email}' already exists in the database."
                )

    update_data = {}
    if cand.full_name is not None:
        update_data["full_name"] = cand.full_name
    if cand.email is not None:
        update_data["email"] = cand.email
    if cand.phone is not None:
        update_data["phone"] = cand.phone
    if cand.skills is not None:
        update_data["skills"] = cand.skills
    if cand.experience_years is not None:
        update_data["experience_years"] = cand.experience_years
    if cand.resume_url is not None:
        update_data["resume_url"] = cand.resume_url
    if cand.education is not None:
        update_data["education"] = cand.education
    if cand.working_or_not is not None:
        update_data["working_or_not"] = cand.working_or_not
    if cand.academic_details is not None:
        update_data["academic_details"] = cand.academic_details
    if cand.achievements is not None:
        update_data["achievements"] = cand.achievements
    if cand.job_id is not None:
        update_data["job_id"] = cand.job_id

    parsed_json = current_cand.get("parsed_resume_json") or {}
    if not isinstance(parsed_json, dict):
        parsed_json = {}

    modified_json = False
    if cand.summary is not None:
        parsed_json["summary"] = cand.summary
        modified_json = True
    if cand.raw_text is not None:
        parsed_json["raw_text"] = cand.raw_text
        modified_json = True
    if cand.parsed_resume_json is not None:
        parsed_json = {**parsed_json, **cand.parsed_resume_json}
        modified_json = True

    if modified_json:
        update_data["parsed_resume_json"] = parsed_json

    if update_data:
        try:
            res = db.table("candidates").update(update_data).eq("id", candidate_id).execute()
        except Exception as e:
            logger.error(f"Database error during candidate update of ID '{candidate_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")
            
        if not res.data:
            logger.warning(f"No candidate rows returned after update for ID '{candidate_id}'. Permisson denied or not found.")
            raise HTTPException(status_code=500, detail="Update failed: candidate row not updated. Check permission policies.")
        updated_cand = res.data[0]
    else:
        updated_cand = current_cand

    if "parsed_resume_json" in updated_cand and updated_cand["parsed_resume_json"]:
        if isinstance(updated_cand["parsed_resume_json"], dict) and "raw_text" in updated_cand["parsed_resume_json"]:
            updated_cand["raw_text"] = updated_cand["parsed_resume_json"]["raw_text"]

    try:
        db.table("activity_log").insert({
            "action": "candidate_updated",
            "entity_type": "candidates",
            "entity_id": candidate_id,
            "actor_name": "Recruiter",
            "metadata": {"candidate_name": updated_cand.get("full_name", "")}
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log candidate update activity: {e}")

    return updated_cand




@router.delete("/api/v1/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, db: Client = Depends(get_supabase)):
    res = db.table("candidates").update({"is_deleted": True}).eq("id", candidate_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    try:
        db.table("activity_log").insert({
            "action": "candidate_deleted",
            "entity_type": "candidates",
            "entity_id": candidate_id,
            "actor_name": "Recruiter",
            "metadata": {"candidate_name": res.data[0].get("full_name", "")}
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log candidate deletion activity: {e}")
        
    return {"success": True}




@router.get("/api/v1/candidates/{candidate_id}/applications")
async def get_candidate_applications(candidate_id: str, db: Client = Depends(get_supabase)):
    res = db.table("applications").select("*, job_openings(*, requirements(*, clients(name)))").eq("candidate_id", candidate_id).execute()
    formatted = []
    for row in res.data:
        job = row.get("job_openings") or {}
        req = job.get("requirements") or {}
        cli = req.get("clients") or {}
        formatted.append({
            **{k: v for k, v in row.items() if k != "job_openings"},
            "job_title": job.get("title", "Unknown Job"),
            "client_name": cli.get("name", "Generic Client")
        })
    return formatted



@router.get("/api/v1/candidates/{candidate_id}/history")
async def get_candidate_history(candidate_id: str, db: Client = Depends(get_supabase)):
    apps_res = db.table("applications").select("*, job_openings(*, requirements(*, clients(name)))").eq("candidate_id", candidate_id).execute()
    apps = apps_res.data or []
    
    app_ids = [a["id"] for a in apps]
    stages = []
    if app_ids:
        stages_res = db.table("interview_stages").select("*").in_("application_id", app_ids).execute()
        stages = stages_res.data or []
        
    formatted = []
    for app_row in apps:
        job = app_row.get("job_openings") or {}
        req = job.get("requirements") or {}
        cli = req.get("clients") or {}
        app_stages = [stg for stg in stages if stg["application_id"] == app_row["id"]]
        
        # Sort stages by created_at or order
        app_stages.sort(key=lambda x: x.get("stage_order") or 1)
        
        formatted.append({
            "application_id": app_row["id"],
            "job_id": job.get("id"),
            "job_title": job.get("title", "Unknown Job"),
            "client_name": cli.get("name", "Generic Client"),
            "fuzzy_score": app_row.get("fuzzy_score"),
            "match_score": app_row.get("match_score"),
            "match_reason": app_row.get("match_reason"),
            "screening_status": app_row.get("screening_status"),
            "stage": app_row.get("stage"),
            "stage_status": app_row.get("stage_status"),
            "stage_notes": app_row.get("stage_notes"),
            "stages": app_stages,
            "created_at": app_row.get("created_at")
        })
    return formatted




@router.post("/api/v1/candidates")
async def create_candidate(
    cand: CandidateModel,
    background_tasks: BackgroundTasks,
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    db = get_admin_supabase_client()
    if cand.job_id:
        cand.job_id = deobfuscate_id(cand.job_id)
    # Limit source value to allowed constraints: 'csv', 'pdf', 'docx', 'manual'
    db_source = cand.source
    if db_source not in ["csv", "pdf", "docx", "manual"]:
        db_source = "manual"

    # Search if candidate already exists with same email AND job_id (globally, including soft-deleted ones)
    query = db.table("candidates").select("*").eq("email", cand.email)
    if cand.job_id:
        query = query.eq("job_id", cand.job_id)
    else:
        query = query.is_("job_id", "null")
    exists = query.execute()

    # Resolve recruiter_id from job_id if not logged in
    recruiter_id = None
    if cand.job_id:
        job_res = db.table("job_openings").select("requirements(created_by)").eq("id", cand.job_id).execute()
        if job_res.data:
            req_data = job_res.data[0].get("requirements") or {}
            recruiter_id = req_data.get("created_by")

    # uploaded_by must be a Supabase auth user UUID (profiles.id) to satisfy candidates_uploaded_by_fkey
    auth_user_id = user_id or get_current_user_id(authorization)
    db_uploaded_by = cand.uploaded_by if cand.uploaded_by else (auth_user_id or recruiter_id)
    
    user_org_id = get_user_org_id(authorization)
    if not user_org_id and cand.job_id:
        job_org_res = db.table("job_openings").select("organization_id").eq("id", cand.job_id).execute()
        if job_org_res.data:
            user_org_id = job_org_res.data[0].get("organization_id")

    # -------------------------------------------------------------------
    # CASE A: a candidate with this exact email (+ job, if given) already
    # exists in the database (even if it was previously soft-deleted).
    # Rather than overwrite them, we MERGE the new data into the old
    # record so nothing useful is lost.
    # -------------------------------------------------------------------
    if exists.data:
        existing_cand = exists.data[0]
        is_deleted = existing_cand.get("is_deleted", False)
        
        # Skills: take the UNION of old + new skills (no duplicates), so
        # re-uploading a resume never makes someone's skill list shrink.
        # Merge skills (take union)
        existing_skills = existing_cand.get("skills") or []
        merged_skills = list(set(existing_skills + cand.skills))
        
        # Experience/working-status: always trust the LATEST upload for these.
        # Update experience and working status to the latest upload
        merged_exp = cand.experience_years
        
        # Text fields: keep the new value if one was given, otherwise keep
        # whatever was already on file.
        # Merge other text fields
        merged_education = cand.education if cand.education else existing_cand.get("education")
        merged_phone = cand.phone if cand.phone else existing_cand.get("phone")
        merged_academic = cand.academic_details if cand.academic_details else existing_cand.get("academic_details")
        merged_achievements = cand.achievements if cand.achievements else existing_cand.get("achievements")
        
        # Resume/raw text: don't throw away old resume text — instead APPEND
        # the new text underneath a clear marker, so the full history of what
        # this candidate has ever submitted is preserved.
        # Merge raw text
        existing_raw = ""
        existing_summary = ""
        existing_parsed = {}
        if "parsed_resume_json" in existing_cand and isinstance(existing_cand["parsed_resume_json"], dict):
            existing_parsed = existing_cand["parsed_resume_json"]
            existing_raw = existing_parsed.get("raw_text") or ""
            existing_summary = existing_parsed.get("summary") or ""
        
        merged_raw = existing_raw
        if cand.raw_text and cand.raw_text not in existing_raw:
            prefix = "[Re-uploaded Profile]" if is_deleted else "[Updated Profile]"
            merged_raw = f"{existing_raw}\n\n{prefix}:\n{cand.raw_text}" if existing_raw else cand.raw_text
        merged_summary = cand.summary if cand.summary else existing_summary
        
        incoming_parsed = cand.parsed_resume_json or {}
        merged_parsed = {**existing_parsed, **incoming_parsed}
        merged_parsed["raw_text"] = merged_raw
        merged_parsed["summary"] = merged_summary
            
        # Now actually write the merged fields back to the existing row.
        res = db.table("candidates").update({
            "full_name": cand.full_name,
            "phone": merged_phone,
            "skills": merged_skills,
            "experience_years": merged_exp,
            "education": merged_education,
            "working_or_not": cand.working_or_not,
            "academic_details": merged_academic,
            "achievements": merged_achievements,
            "parsed_resume_json": merged_parsed,
            "source": db_source,
            "job_id": cand.job_id if cand.job_id else existing_cand.get("job_id"),
            "uploaded_by": db_uploaded_by if db_uploaded_by else existing_cand.get("uploaded_by"),
            "organization_id": user_org_id if user_org_id else existing_cand.get("organization_id"),
            "is_deleted": False  # Reactivate candidate if it was soft-deleted
        }).eq("id", existing_cand["id"]).execute()
        
        # Some Supabase configurations return an empty result even on a
        # successful update (e.g. certain trigger setups) — if that happens,
        # just re-fetch the row directly so we still have fresh data to return.
        if not res.data:
            # Fallback query if update returned empty list (e.g. trigger or client settings)
            fetch_res = db.table("candidates").select("*").eq("id", existing_cand["id"]).execute()
            res_data_list = fetch_res.data if fetch_res.data else [existing_cand]
        else:
            res_data_list = res.data
            
        data = res_data_list[0]
        data["raw_text"] = merged_raw
        # If this candidate is tied to a specific job, make sure an
        # "applications" row exists for them and send the confirmation email.
        # Auto-handle application linking and email
        target_job_id = cand.job_id if cand.job_id else existing_cand.get("job_id")
        if target_job_id:
            form_responses = merged_parsed.get("custom_form_responses") or {}
            app_id, email_sent, email_error = await handle_candidate_application(
                candidate_id=existing_cand["id"],
                email=cand.email,
                full_name=cand.full_name,
                job_id=target_job_id,
                form_responses=form_responses,
                db=get_admin_supabase_client()
            )
            await auto_link_candidate_to_job(db, target_job_id, data["id"], data)
            if app_id:
                data["application_id"] = app_id
                data["email_sent"] = email_sent
                data["email_error"] = email_error
                background_tasks.add_task(
                    trigger_whatsapp_notification_background,
                    "",
                    existing_cand["id"],
                    target_job_id,
                    "application_submitted"
                )
        return data

    # -------------------------------------------------------------------
    # CASE B: brand-new candidate — nothing to merge, just insert.
    # -------------------------------------------------------------------
 
    incoming_parsed = cand.parsed_resume_json or {}
    parsed_resume_payload = {**incoming_parsed}
    parsed_resume_payload["raw_text"] = cand.raw_text
    parsed_resume_payload["summary"] = cand.summary or ""

    payload = {
        "full_name": cand.full_name,
        "email": cand.email,
        "phone": cand.phone if cand.phone else None,
        "skills": cand.skills,
        "experience_years": cand.experience_years,
        "resume_url": cand.resume_url,
        "parsed_resume_json": parsed_resume_payload,
        "education": cand.education,
        "working_or_not": cand.working_or_not,
        "academic_details": cand.academic_details,
        "achievements": cand.achievements,
        "source": db_source,
        "job_id": cand.job_id,
        "uploaded_by": db_uploaded_by,
        "organization_id": user_org_id
    }
    res = db.table("candidates").insert(payload).execute()
    
        # Same empty-result safety net as in the update path above.
    if not res.data:
        # Fallback query if insert returned empty list (e.g. database deduplication trigger returned NULL)
        fetch_res = db.table("candidates").select("*").eq("email", cand.email).execute()
        res_data_list = fetch_res.data if fetch_res.data else []
    else:
        res_data_list = res.data
        
    if res_data_list:
        data = res_data_list[0]
        data["raw_text"] = cand.raw_text
        # Same auto-link-and-email step as in the update path above.
        # Auto-handle application linking and email
        if cand.job_id:
            form_responses = parsed_resume_payload.get("custom_form_responses") or {}
            app_id, email_sent, email_error = await handle_candidate_application(
                candidate_id=data["id"],
                email=cand.email,
                full_name=cand.full_name,
                job_id=cand.job_id,
                form_responses=form_responses,
                db=get_admin_supabase_client()
            )
            await auto_link_candidate_to_job(db, cand.job_id, data["id"], data)
            if app_id:
                data["application_id"] = app_id
                data["email_sent"] = email_sent
                data["email_error"] = email_error
                background_tasks.add_task(
                    trigger_whatsapp_notification_background,
                    "",
                    data["id"],
                    cand.job_id,
                    "application_submitted"
                )
        return data
    return {}

# -----------------------------------------------------------------------
# ENDPOINT: POST /api/v1/candidates/upload/csv — bulk-import candidates
# -----------------------------------------------------------------------
# Accepts a list of raw candidate rows (as if from a spreadsheet/CSV file)
# and, for EACH row: cleans up messy input data (skills provided as a
# comma-separated string OR already as a list; phone numbers that might
# literally be the text "null"; a working-status flag that might be a
# string like "yes"/"employed" or a real boolean), then creates a new
# candidate or merges into an existing one (same merge logic as the single
# POST /candidates endpoint above), optionally links them straight to a
# target job, and queues up a background download for anyone whose resume
# was supplied as a Google Drive link. Finally reports back how many rows
# were newly inserted vs. how many were merged into existing candidates.

@router.post("/api/v1/candidates")
async def create_candidate(
    cand: CandidateModel,
    background_tasks: BackgroundTasks,
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    db = get_admin_supabase_client()
    if cand.job_id:
        cand.job_id = deobfuscate_id(cand.job_id)
    # Limit source value to allowed constraints: 'csv', 'pdf', 'docx', 'manual'
    db_source = cand.source
    if db_source not in ["csv", "pdf", "docx", "manual"]:
        db_source = "manual"

    # Search if candidate already exists with same email AND job_id (globally, including soft-deleted ones)
    query = db.table("candidates").select("*").eq("email", cand.email)
    if cand.job_id:
        query = query.eq("job_id", cand.job_id)
    else:
        query = query.is_("job_id", "null")
    exists = query.execute()

    # Resolve recruiter_id from job_id if not logged in
    recruiter_id = None
    if cand.job_id:
        job_res = db.table("job_openings").select("requirements(created_by)").eq("id", cand.job_id).execute()
        if job_res.data:
            req_data = job_res.data[0].get("requirements") or {}
            recruiter_id = req_data.get("created_by")

    # uploaded_by must be a Supabase auth user UUID (profiles.id) to satisfy candidates_uploaded_by_fkey
    auth_user_id = user_id or get_current_user_id(authorization)
    db_uploaded_by = cand.uploaded_by if cand.uploaded_by else (auth_user_id or recruiter_id)
    
    user_org_id = get_user_org_id(authorization)
    if not user_org_id and cand.job_id:
        job_org_res = db.table("job_openings").select("organization_id").eq("id", cand.job_id).execute()
        if job_org_res.data:
            user_org_id = job_org_res.data[0].get("organization_id")

    # -------------------------------------------------------------------
    # CASE A: a candidate with this exact email (+ job, if given) already
    # exists in the database (even if it was previously soft-deleted).
    # Rather than overwrite them, we MERGE the new data into the old
    # record so nothing useful is lost.
    # -------------------------------------------------------------------
    if exists.data:
        existing_cand = exists.data[0]
        is_deleted = existing_cand.get("is_deleted", False)
        
        # Skills: take the UNION of old + new skills (no duplicates), so
        # re-uploading a resume never makes someone's skill list shrink.
        # Merge skills (take union)
        existing_skills = existing_cand.get("skills") or []
        merged_skills = list(set(existing_skills + cand.skills))
        
        # Experience/working-status: always trust the LATEST upload for these.
        # Update experience and working status to the latest upload
        merged_exp = cand.experience_years
        
        # Text fields: keep the new value if one was given, otherwise keep
        # whatever was already on file.
        # Merge other text fields
        merged_education = cand.education if cand.education else existing_cand.get("education")
        merged_phone = cand.phone if cand.phone else existing_cand.get("phone")
        merged_academic = cand.academic_details if cand.academic_details else existing_cand.get("academic_details")
        merged_achievements = cand.achievements if cand.achievements else existing_cand.get("achievements")
        
        # Resume/raw text: don't throw away old resume text — instead APPEND
        # the new text underneath a clear marker, so the full history of what
        # this candidate has ever submitted is preserved.
        # Merge raw text
        existing_raw = ""
        existing_summary = ""
        existing_parsed = {}
        if "parsed_resume_json" in existing_cand and isinstance(existing_cand["parsed_resume_json"], dict):
            existing_parsed = existing_cand["parsed_resume_json"]
            existing_raw = existing_parsed.get("raw_text") or ""
            existing_summary = existing_parsed.get("summary") or ""
        
        merged_raw = existing_raw
        if cand.raw_text and cand.raw_text not in existing_raw:
            prefix = "[Re-uploaded Profile]" if is_deleted else "[Updated Profile]"
            merged_raw = f"{existing_raw}\n\n{prefix}:\n{cand.raw_text}" if existing_raw else cand.raw_text
        merged_summary = cand.summary if cand.summary else existing_summary
        
        incoming_parsed = cand.parsed_resume_json or {}
        merged_parsed = {**existing_parsed, **incoming_parsed}
        merged_parsed["raw_text"] = merged_raw
        merged_parsed["summary"] = merged_summary
            
        # Now actually write the merged fields back to the existing row.
        res = db.table("candidates").update({
            "full_name": cand.full_name,
            "phone": merged_phone,
            "skills": merged_skills,
            "experience_years": merged_exp,
            "education": merged_education,
            "working_or_not": cand.working_or_not,
            "academic_details": merged_academic,
            "achievements": merged_achievements,
            "parsed_resume_json": merged_parsed,
            "source": db_source,
            "job_id": cand.job_id if cand.job_id else existing_cand.get("job_id"),
            "uploaded_by": db_uploaded_by if db_uploaded_by else existing_cand.get("uploaded_by"),
            "organization_id": user_org_id if user_org_id else existing_cand.get("organization_id"),
            "is_deleted": False  # Reactivate candidate if it was soft-deleted
        }).eq("id", existing_cand["id"]).execute()
        
        # Some Supabase configurations return an empty result even on a
        # successful update (e.g. certain trigger setups) — if that happens,
        # just re-fetch the row directly so we still have fresh data to return.
        if not res.data:
            # Fallback query if update returned empty list (e.g. trigger or client settings)
            fetch_res = db.table("candidates").select("*").eq("id", existing_cand["id"]).execute()
            res_data_list = fetch_res.data if fetch_res.data else [existing_cand]
        else:
            res_data_list = res.data
            
        data = res_data_list[0]
        data["raw_text"] = merged_raw
        # If this candidate is tied to a specific job, make sure an
        # "applications" row exists for them and send the confirmation email.
        # Auto-handle application linking and email
        target_job_id = cand.job_id if cand.job_id else existing_cand.get("job_id")
        if target_job_id:
            form_responses = merged_parsed.get("custom_form_responses") or {}
            app_id, email_sent, email_error = await handle_candidate_application(
                candidate_id=existing_cand["id"],
                email=cand.email,
                full_name=cand.full_name,
                job_id=target_job_id,
                form_responses=form_responses,
                db=get_admin_supabase_client()
            )
            await auto_link_candidate_to_job(db, target_job_id, data["id"], data)
            if app_id:
                data["application_id"] = app_id
                data["email_sent"] = email_sent
                data["email_error"] = email_error
                background_tasks.add_task(
                    trigger_whatsapp_notification_background,
                    "",
                    existing_cand["id"],
                    target_job_id,
                    "application_submitted"
                )
        return data

    # -------------------------------------------------------------------
    # CASE B: brand-new candidate — nothing to merge, just insert.
    # -------------------------------------------------------------------
 
    incoming_parsed = cand.parsed_resume_json or {}
    parsed_resume_payload = {**incoming_parsed}
    parsed_resume_payload["raw_text"] = cand.raw_text
    parsed_resume_payload["summary"] = cand.summary or ""

    payload = {
        "full_name": cand.full_name,
        "email": cand.email,
        "phone": cand.phone if cand.phone else None,
        "skills": cand.skills,
        "experience_years": cand.experience_years,
        "resume_url": cand.resume_url,
        "parsed_resume_json": parsed_resume_payload,
        "education": cand.education,
        "working_or_not": cand.working_or_not,
        "academic_details": cand.academic_details,
        "achievements": cand.achievements,
        "source": db_source,
        "job_id": cand.job_id,
        "uploaded_by": db_uploaded_by,
        "organization_id": user_org_id
    }
    res = db.table("candidates").insert(payload).execute()
    
        # Same empty-result safety net as in the update path above.
    if not res.data:
        # Fallback query if insert returned empty list (e.g. database deduplication trigger returned NULL)
        fetch_res = db.table("candidates").select("*").eq("email", cand.email).execute()
        res_data_list = fetch_res.data if fetch_res.data else []
    else:
        res_data_list = res.data
        
    if res_data_list:
        data = res_data_list[0]
        data["raw_text"] = cand.raw_text
        # Same auto-link-and-email step as in the update path above.
        # Auto-handle application linking and email
        if cand.job_id:
            form_responses = parsed_resume_payload.get("custom_form_responses") or {}
            app_id, email_sent, email_error = await handle_candidate_application(
                candidate_id=data["id"],
                email=cand.email,
                full_name=cand.full_name,
                job_id=cand.job_id,
                form_responses=form_responses,
                db=get_admin_supabase_client()
            )
            await auto_link_candidate_to_job(db, cand.job_id, data["id"], data)
            if app_id:
                data["application_id"] = app_id
                data["email_sent"] = email_sent
                data["email_error"] = email_error
                background_tasks.add_task(
                    trigger_whatsapp_notification_background,
                    "",
                    data["id"],
                    cand.job_id,
                    "application_submitted"
                )
        return data
    return {}

# -----------------------------------------------------------------------
# ENDPOINT: POST /api/v1/candidates/upload/csv — bulk-import candidates
# -----------------------------------------------------------------------
# Accepts a list of raw candidate rows (as if from a spreadsheet/CSV file)
# and, for EACH row: cleans up messy input data (skills provided as a
# comma-separated string OR already as a list; phone numbers that might
# literally be the text "null"; a working-status flag that might be a
# string like "yes"/"employed" or a real boolean), then creates a new
# candidate or merges into an existing one (same merge logic as the single
# POST /candidates endpoint above), optionally links them straight to a
# target job, and queues up a background download for anyone whose resume
# was supplied as a Google Drive link. Finally reports back how many rows
# were newly inserted vs. how many were merged into existing candidates.
@router.post("/api/v1/candidates/upload/csv")
async def upload_csv_candidates(
    payload: CSVUploadModel, 
    background_tasks: BackgroundTasks, 
    db: Client = Depends(get_supabase), 
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    # Candidates.uploaded_by references profiles.id (Supabase auth UUID)
    auth_user_id = user_id or get_current_user_id(authorization)
    resolved_uploader_id = auth_user_id
    csv_user_org_id = get_user_org_id(authorization)
    admin_db = get_admin_supabase_client()
    inserted = 0
    skipped = 0
    candidates_with_gd_resumes = []
    
    jwt_token = None
    if authorization:
        if authorization.startswith("Bearer "):
            jwt_token = authorization.split(" ")[1]
        elif authorization.startswith("eyJ"):
            jwt_token = authorization
            
    for item in payload.items:
        email = item.get("email")
        full_name = item.get("full_name")
        if not email or not full_name:
            continue
            
        email = str(email).strip()
        full_name = str(full_name).strip()
        
        # Enforce allowed constraint for candidates_source_check ('csv', 'pdf', 'docx', 'manual')
        item_source = str(item.get("source") or "").lower().strip()
        if item_source not in ["csv", "pdf", "docx", "manual"]:
            item_source = "csv"
        
        # Check if candidate email already exists (globally, including soft-deleted ones)
        exists_res = admin_db.table("candidates").select("*").eq("email", email).execute()
        
        # Skills list parser
        # "skills" might arrive as a comma-separated string (typical CSV) OR
        # already as a list — handle both shapes.
        skills_input = item.get("skills", "")
        skills_list = []
        if isinstance(skills_input, str):
            skills_list = [s.strip() for s in skills_input.split(",") if s.strip()]
        elif isinstance(skills_input, list):
            skills_list = [str(s).strip() for s in skills_input if str(s).strip()]
            
        # Clean up messy phone values — spreadsheets often contain the
        # literal text "null" or "None" instead of a truly empty cell.
        phone_input = item.get("phone")
        phone_val = str(phone_input).strip() if phone_input else None
        if phone_val == "" or phone_val == "null" or phone_val == "None":
            phone_val = None
            
        exp_years = int(item.get("experience_years") or 0)
        education_val = item.get("education")
        working_val = item.get("working_or_not")
        academic_val = item.get("academic_details")
        achievements_val = item.get("achievements")
        resume_url_val = item.get("resume_url")
        raw_text_val = item.get("raw_text")
        summary_val = item.get("summary")
        target_job_id = item.get("job_id") or payload.job_id
        
        item_org_id = csv_user_org_id
        if not item_org_id and target_job_id:
            job_org_res = admin_db.table("job_openings").select("organization_id").eq("id", target_job_id).execute()
            if job_org_res.data:
                item_org_id = job_org_res.data[0].get("organization_id")
        
        # "working_or_not" might be a real boolean, or a human-typed string
        # like "yes"/"employed" — normalize all of that into one boolean.
        # Resolve working status boolean
        if isinstance(working_val, str):
            working_bool = working_val.lower().strip() in ["true", "yes", "1", "working", "employed"]
        elif isinstance(working_val, bool):
            working_bool = working_val
        else:
            working_bool = True  # default
        
        candidate_id = None
        
        # This email (+ job) already exists as a candidate — merge into it
        # using the same union-skills / keep-latest-value approach as the
        # single-candidate create endpoint above.
        if exists_res.data:
            existing_cand = exists_res.data[0]
            is_deleted = existing_cand.get("is_deleted", False)
            candidate_id = existing_cand["id"]
            
            if is_deleted:
                inserted += 1
            else:
                skipped += 1
                
            existing_skills = existing_cand.get("skills") or []
            merged_skills = list(set(existing_skills + skills_list))
            
            merged_exp = exp_years if exp_years > 0 else existing_cand.get("experience_years", 0)
            merged_education = education_val if education_val else existing_cand.get("education")
            merged_academic = academic_val if academic_val else existing_cand.get("academic_details")
            merged_achievements = achievements_val if achievements_val else existing_cand.get("achievements")
            
            existing_json = existing_cand.get("parsed_resume_json") if isinstance(existing_cand.get("parsed_resume_json"), dict) else {}
            existing_raw = existing_json.get("raw_text") or ""
            existing_summary = existing_json.get("summary") or ""
            
            merged_raw = raw_text_val if raw_text_val else existing_raw
            merged_summary = summary_val if summary_val else existing_summary
            
            if not merged_raw:
                prefix = "[Re-uploaded Deleted Profile from CSV]" if is_deleted else "[CSV Re-upload]"
                merged_raw = f"{prefix}: {full_name}"
                
            parsed_resume_payload = {
                "raw_text": merged_raw,
                "summary": merged_summary
            }
            
            if resume_url_val and is_google_drive_url(resume_url_val):
                parsed_resume_payload["raw_text"] = "Downloading and extracting Google Drive resume..."
            
            # Update existing candidate details using admin_db to bypass RLS restrictions for all users
            admin_db.table("candidates").update({
                "full_name": full_name,
                "phone": phone_val if phone_val else existing_cand.get("phone"),
                "skills": merged_skills,
                "experience_years": merged_exp,
                "education": merged_education,
                "working_or_not": working_bool,
                "academic_details": merged_academic,
                "achievements": merged_achievements,
                "resume_url": resume_url_val if resume_url_val else existing_cand.get("resume_url"),
                "parsed_resume_json": parsed_resume_payload,
                "source": item_source,
                "uploaded_by": resolved_uploader_id or existing_cand.get("uploaded_by"),
                "organization_id": item_org_id if item_org_id else existing_cand.get("organization_id"),
                "is_deleted": False  # Reactivate candidate if it was soft-deleted
            }).eq("email", email).execute()
        # Brand-new candidate for this CSV row — just insert it fresh.
        else:
            inserted += 1
            final_raw = raw_text_val if raw_text_val else f"Parsed from CSV: {full_name}"
            parsed_resume_payload = {
                "raw_text": final_raw,
                "summary": summary_val or ""
            }
            if resume_url_val and is_google_drive_url(resume_url_val):
                parsed_resume_payload["raw_text"] = "Downloading and extracting Google Drive resume..."
                
            # Insert new candidate using admin_db to bypass RLS restrictions for all users
            res = admin_db.table("candidates").insert({
                "full_name": full_name,
                "email": email,
                "phone": phone_val,
                "skills": skills_list,
                "experience_years": exp_years,
                "parsed_resume_json": parsed_resume_payload,
                "resume_url": resume_url_val,
                "education": education_val,
                "working_or_not": working_bool,
                "academic_details": academic_val,
                "achievements": achievements_val,
                "source": item_source,
                "uploaded_by": resolved_uploader_id,
                "organization_id": item_org_id,
                "job_id": target_job_id
            }).execute()
            
            if res.data:
                candidate_id = res.data[0]["id"]
                
        # If this row specifies a target job, create/reuse their application
        # record for it right away.
        # Link candidate to job if target_job_id is provided
        if candidate_id and target_job_id:
            try:
                await handle_candidate_application(
                    candidate_id=candidate_id,
                    email=email,
                    job_id=target_job_id,
                    source="bulk_import"
                )
            except Exception as app_err:
                logger.error(f"Failed to handle application for candidate {candidate_id} on job {target_job_id}: {app_err}")
                
        # If their resume was supplied as a Google Drive link, queue it up to
        # be downloaded and parsed AFTER this request finishes (see the
        # background task added below, once every row has been processed).
        # If candidate has Google Drive resume URL, add to background processing list
        if candidate_id and resume_url_val and is_google_drive_url(resume_url_val):
            candidates_with_gd_resumes.append({
                "id": candidate_id,
                "email": email,
                "resume_url": resume_url_val
            })


            
    if candidates_with_gd_resumes:
        background_tasks.add_task(download_resumes_background, candidates_with_gd_resumes, jwt_token)
        
    if user_id:
        create_system_notification(
            db,
            user_id,
            "Candidate Upload Completed",
            f"Successfully parsed candidate CSV. Imported {inserted} new candidates and updated {skipped} existing ones.",
            "upload",
            {"inserted": inserted, "skipped": skipped}
        )
        log_activity_event(
            db,
            action="candidate_csv_imported",
            entity_type="candidates",
            entity_id=None,
            actor_name="Recruiter",
            actor_id=user_id,
            metadata={"inserted": inserted, "skipped": skipped}
        )
        
    return {"inserted": inserted, "skipped": skipped}

# BACKGROUND TASK: generate_questions_background — local fallback that
# invents a small set of template screening questions for an accepted
# application, used when n8n isn't generating them via AI.
# accept application -> triggers background personalized question generation
def generate_questions_background(app_id: str, candidate_name: str, skills: List[str], exp_years: int, raw_text: str, jwt_token: str):
    logger.info(f"Starting background question generation for application {app_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    
    try:
        # Fallback if no questions generated or no client
        questions = [
            {"question": f"Can you detail your experience working with {skills[0] if skills else 'modern tech'} and how you applied it in your previous role?", "difficulty": "easy"},
            {"question": "How do you handle client-side rendering bottlenecks when managing large datagrid lists?", "difficulty": "medium"},
            {"question": "Describe a time you solved a challenging concurrency/state synchronization issue.", "difficulty": "hard"}
        ]
            
        import uuid
        questions_array = []
        for idx, q in enumerate(questions):
            questions_array.append({
                "id": str(uuid.uuid4()),
                "question": q["question"],
                "difficulty": q["difficulty"],
                "question_order": idx + 1,
                "ai_generated": True,
                "modified": False
            })
            
        # Update applications table screening_questions column
        db.table("applications").update({
            "screening_questions": questions_array
        }).eq("id", app_id).execute()
        
    except Exception as e:
        logger.error(f"Error generating screening questions: {e}")
# HELPER: ensure_questions_have_ids — makes sure every screening question
# in a list has a unique id (assigning new ones where missing), since
# older data or AI-generated batches might not include ids by default.

def ensure_questions_have_ids(questions_list: list, app_id: str, db: Client) -> list:
    import uuid
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
            db.table("applications").update({
                "screening_questions": healed_list
            }).eq("id", app_id).execute()
        except Exception as e:
            logger.error(f"Failed to save auto-healed screening question IDs: {e}")
    return healed_list

# ENDPOINT: GET /api/v1/applications/{app_id} — fetch one full application
# record, including candidate, job, and screening question details.

