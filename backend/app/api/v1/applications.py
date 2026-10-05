import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Body, BackgroundTasks, Query
from supabase import Client

from app.core.config import USE_N8N, FRONTEND_BASE_URL
from app.core.logging import logger
from app.api.dependencies import get_supabase, get_admin_supabase_client, get_current_user_id
from app.schemas.common import VerifyStatusModel, CandidateMessageCreateModel
from app.security.authentication import filter_valid_uuids
from app.security.tenant_access import get_recruiter_owner_ids
from app.services.question_service import ensure_questions_have_ids
from app.services.notification_service import log_activity_event
from app.integrations.email_client import send_email
from app.workers.resume_tasks import generate_questions_background
from app.workers.ai_tasks import handle_generate_questions_dispatch
from app.workers.notification_tasks import trigger_whatsapp_notification_background

router = APIRouter()

async def handle_accept_application_logic(app_id: str, background_tasks: BackgroundTasks, request: Request, db: Client):
    res = db.table("applications").update({"screening_status": "accepted"}).eq("id", app_id).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to accept application")
        
    app_record = res.data[0]
    
    cand_res = db.table("candidates").select("*").eq("id", app_record["candidate_id"]).execute()
    if cand_res.data:
        cand = cand_res.data[0]
        if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
            if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
                cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
        auth_header = request.headers.get("Authorization", "")
        jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
        user_id = get_current_user_id(auth_header)
        
        job_res = db.table("job_openings").select("*").eq("id", app_record["job_opening_id"]).execute()
        job = job_res.data[0] if job_res.data else {}
        
        log_activity_event(
            db,
            action="application_accepted",
            entity_type="applications",
            entity_id=app_id,
            actor_name="Recruiter",
            actor_id=user_id,
            metadata={"candidate_name": cand.get("full_name", ""), "job_title": job.get("title", "")}
        )
        
        try:
            existing_jc_cand = db.table("job_candidates").select("rank_order").eq("job_opening_id", app_record["job_opening_id"]).eq("candidate_id", app_record["candidate_id"]).execute()
            if not existing_jc_cand.data:
                existing_jc = db.table("job_candidates").select("*").eq("job_opening_id", app_record["job_opening_id"]).execute()
                rank = len(existing_jc.data) + 1
                db.table("job_candidates").upsert({
                    "job_opening_id": app_record["job_opening_id"],
                    "candidate_id": app_record["candidate_id"],
                    "application_id": app_record["id"],
                    "fuzzy_score": app_record.get("fuzzy_score") or 0,
                    "rank_order": rank,
                    "strengths": app_record.get("strengths") or [],
                    "skill_gaps": app_record.get("skill_gaps") or [],
                    "parsed_resume": cand.get("parsed_resume_json")
                }, on_conflict="job_opening_id,candidate_id").execute()
        except Exception as jc_err:
            logger.error(f"Failed to upsert to job_candidates in handle_accept_application_logic: {jc_err}")
            
        req_res = db.table("requirements").select("*").eq("id", job.get("requirement_id", "")).execute()
        req = req_res.data[0] if req_res.data else {}
        
        if USE_N8N:
            background_tasks.add_task(
                handle_generate_questions_dispatch,
                app_record,
                cand,
                job,
                req,
                jwt_token
            )
        else:
            background_tasks.add_task(
                generate_questions_background,
                app_id,
                cand["full_name"],
                cand.get("skills") or [],
                cand.get("experience_years") or 0,
                cand.get("raw_text") or "",
                jwt_token
            )
        
        background_tasks.add_task(
            trigger_whatsapp_notification_background,
            jwt_token,
            app_record["candidate_id"],
            app_record["job_opening_id"],
            "application_accepted"
        )
            
    return app_record


@router.post("/api/v1/applications/verify-status")
async def verify_application_status(payload: VerifyStatusModel, db: Client = Depends(get_supabase)):
    db = get_admin_supabase_client()
    try:
        app_data = None
        if not payload.application_id or not payload.application_id.strip():
            cand_res = db.table("candidates").select("*").eq("email", payload.email.strip()).execute()
            if not cand_res.data:
                raise HTTPException(status_code=404, detail="No application found matching this email address.")
            cand_ids = [c["id"] for c in cand_res.data]
            
            app_res = db.table("applications").select("*, candidates(*), job_openings(*, requirements(*, clients(name)))").in_("candidate_id", cand_ids).execute()
            if not app_res.data:
                raise HTTPException(status_code=404, detail="No application found matching this email address.")
                
            cleared_apps = []
            for app in app_res.data:
                is_rej = app.get("screening_status") == "rejected" or app.get("stage") == "rejected" or app.get("stage_status") == "failed"
                is_hir = app.get("stage") == "hired"
                if is_rej or is_hir:
                    cleared_apps.append(app)
            
            if not cleared_apps:
                raise HTTPException(status_code=400, detail="Application ID is required for active applications.")
            
            cleared_apps.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            app_data = cleared_apps[0]
        else:
            app_res = db.table("applications").select("*, candidates(*), job_openings(*, requirements(*, clients(name)))").eq("id", payload.application_id.strip()).execute()
            if not app_res.data:
                raise HTTPException(status_code=404, detail="Application not found with the provided ID")
            app_data = app_res.data[0]
            
        cand_data = app_data.get("candidates") or {}
        
        if cand_data.get("email", "").strip().lower() != payload.email.strip().lower():
            raise HTTPException(status_code=401, detail="Invalid combination of Email and Application ID")
            
        if cand_data and "parsed_resume_json" in cand_data and cand_data["parsed_resume_json"]:
            if isinstance(cand_data["parsed_resume_json"], dict) and "raw_text" in cand_data["parsed_resume_json"]:
                cand_data["raw_text"] = cand_data["parsed_resume_json"]["raw_text"]
                
        job_data = app_data.get("job_openings") or {}
        if job_data:
            req = job_data.get("requirements") or {}
            cli = req.get("clients") or {}
            job_data["client_name"] = cli.get("name") or "Generic Client"
            
        msg_res = db.table("candidate_queries").select("*").eq("job_id", job_data.get("id")).eq("candidate_email", cand_data.get("email")).order("created_at", desc=False).execute()
        messages = msg_res.data or []
        
        return {
            "application": {
                "id": app_data.get("id"),
                "stage": app_data.get("stage") or "screening",
                "stage_status": app_data.get("stage_status") or "pending",
                "screening_status": app_data.get("screening_status") or "pending",
                "created_at": app_data.get("created_at")
            },
            "candidate": {
                "full_name": cand_data.get("full_name"),
                "email": cand_data.get("email")
            },
            "job": {
                "id": job_data.get("id"),
                "title": job_data.get("title"),
                "department": job_data.get("department") or "Engineering",
                "client_name": job_data.get("client_name"),
                "custom_stages": job_data.get("custom_stages") or [],
                "candidate_view_settings": job_data.get("candidate_view_settings") or {},
                "stage_notifications": job_data.get("stage_notifications") or {}
            },
            "messages": messages
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error in verify_application_status: {e}")
        raise HTTPException(status_code=500, detail=f"Database verification failed: {e}")

@router.post("/api/v1/applications/{application_id}/messages")
async def send_candidate_status_message(application_id: str, payload: CandidateMessageCreateModel, db: Client = Depends(get_supabase)):
    db = get_admin_supabase_client()
    try:
        app_res = db.table("applications").select("*, candidates(*), job_openings(id, title, requirements(created_by))").eq("id", application_id).execute()
        if not app_res.data:
            raise HTTPException(status_code=404, detail="Application not found")
            
        app_data = app_res.data[0]
        cand_data = app_data.get("candidates") or {}
        job_data = app_data.get("job_openings") or {}
        
        import uuid
        from datetime import datetime
        query_id = str(uuid.uuid4())
        
        new_query = {
            "id": query_id,
            "job_id": job_data.get("id"),
            "candidate_email": cand_data.get("email"),
            "query_text": payload.message_text,
            "ai_response": None,
            "is_resolved": False,
            "source": "tracking_portal",
            "sender": "candidate",
            "is_ended": False,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        db.table("candidate_queries").insert(new_query).execute()
        
        req_data = job_data.get("requirements") or {}
        recruiter_id = req_data.get("created_by") or "usr-1"
        notif_msg = f"Candidate ({cand_data.get('email')}) sent a message from tracking portal: '{payload.message_text}'"
        try:
            db.table("notifications").insert({
                "recruiter_id": recruiter_id,
                "title": "New Status Portal Query",
                "message": notif_msg,
                "type": "upload",
                "is_read": False,
                "metadata": {"job_id": job_data.get("id"), "query_id": query_id}
            }).execute()
        except Exception as ne:
            logger.warning(f"Failed to insert database notification for tracking portal query: {ne}")
            
        return new_query
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error in send_candidate_status_message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit message: {e}")

@router.get("/api/v1/applications")
async def get_all_applications(
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    if not recruiter_owner_ids:
        return []
        
    user_job_ids = set()
    user_cand_ids = set()
    
    valid_uuids = filter_valid_uuids(recruiter_owner_ids)
    if valid_uuids:
        user_reqs = admin_db.table("requirements").select("id").in_("created_by", valid_uuids).eq("is_deleted", False).execute().data or []
        req_ids = [r["id"] for r in user_reqs]
        
        if req_ids:
            user_jobs_by_req = admin_db.table("job_openings").select("id").in_("requirement_id", req_ids).eq("is_deleted", False).execute().data or []
            for j in user_jobs_by_req:
                user_job_ids.add(j["id"])
                
        user_cands = admin_db.table("candidates").select("id").in_("uploaded_by", valid_uuids).eq("is_deleted", False).execute().data or []
        for c in user_cands:
            user_cand_ids.add(c["id"])
            
    if not user_job_ids and not user_cand_ids:
        return []

    query = admin_db.table("applications").select("*, candidates(*), job_openings(*, requirements(*, clients(id, name)))")
    if user_job_ids and user_cand_ids:
        res = query.or_(f"job_opening_id.in.({','.join(user_job_ids)}),candidate_id.in.({','.join(user_cand_ids)})").execute()
    elif user_job_ids:
        res = query.in_("job_opening_id", list(user_job_ids)).execute()
    else:
        res = query.in_("candidate_id", list(user_cand_ids)).execute()
        
    raw_data = res.data or []
    
    formatted = []
    for app_rec in raw_data:
        job = app_rec.get("job_openings")
        cand = app_rec.get("candidates")
        
        if not job or job.get("is_deleted") or not cand or cand.get("is_deleted"):
            continue
            
        if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
            if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
                cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
        
        req = job.get("requirements") or {}
        cli = req.get("clients") or {}
        job["clients"] = cli
        job["client_name"] = cli.get("name", "Generic Client")
        job["client_id"] = req.get("client_id")
        
        formatted.append(app_rec)
        
    return formatted

@router.get("/api/v1/applications/{app_id}")
async def get_application(
    app_id: str, 
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None)
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, _ = get_recruiter_owner_ids(authorization)
    
    res = admin_db.table("applications").select("*, candidates(*), job_openings(requirement_id)").eq("id", app_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Application not found")
    
    app_record = res.data[0]
    cand = app_record.get("candidates") or {}
    job = app_record.get("job_openings") or {}
    
    if recruiter_owner_ids:
        req_id = job.get("requirement_id")
        req_created_by = None
        if req_id:
            req_res = admin_db.table("requirements").select("created_by").eq("id", req_id).execute()
            if req_res.data:
                req_created_by = req_res.data[0].get("created_by")
                
        is_owned = (
            (cand.get("uploaded_by") in recruiter_owner_ids) or
            (req_created_by in recruiter_owner_ids)
        )
        if not is_owned:
            raise HTTPException(status_code=404, detail="Application not found")

    if cand and "parsed_resume_json" in cand and cand["parsed_resume_json"]:
        if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
            cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
    
    healed_qs = ensure_questions_have_ids(app_record.get("screening_questions") or [], app_id, db)
    
    return {
        "id": app_record["id"],
        "candidate_id": app_record["candidate_id"],
        "job_opening_id": app_record["job_opening_id"],
        "candidate_name": cand.get("full_name", "Unknown"),
        "candidate_email": cand.get("email", ""),
        "candidate_experience": cand.get("experience_years", 0),
        "candidate_skills": cand.get("skills") or [],
        "candidate_cv": cand.get("raw_text") or "",
        "fuzzy_score": app_record.get("fuzzy_score") or 0,
        "match_score": app_record.get("match_score") or 0,
        "match_reason": app_record.get("match_reason") or "",
        "strengths": app_record.get("strengths") or [],
        "skill_gaps": app_record.get("skill_gaps") or [],
        "screening_status": app_record.get("screening_status") or "pending",
        "stage": app_record.get("stage") or "screening",
        "stage_status": app_record.get("stage_status") or "pending",
        "stage_notes": app_record.get("stage_notes") or "",
        "priority": app_record.get("priority") or 0,
        "created_at": app_record.get("created_at"),
        "screening_questions": healed_qs
    }

@router.patch("/api/v1/applications/{app_id}/accept")
@router.post("/api/v1/applications/{app_id}/accept")
async def accept_application_post(app_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    return await handle_accept_application_logic(app_id, background_tasks, request, db)

@router.patch("/api/v1/applications/{app_id}/reject")
async def reject_application(app_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    res = db.table("applications").update({"screening_status": "rejected"}).eq("id", app_id).execute()
    if res.data:
        app_record = res.data[0]
        auth_header = request.headers.get("Authorization", "")
        user_id = get_current_user_id(auth_header)
        jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
        
        cand_name = "Candidate"
        job_title = "Job opening"
        try:
            cand_res = db.table("candidates").select("full_name").eq("id", app_record["candidate_id"]).execute()
            if cand_res.data:
                cand_name = cand_res.data[0].get("full_name") or "Candidate"
            job_res = db.table("job_openings").select("title").eq("id", app_record["job_opening_id"]).execute()
            if job_res.data:
                job_title = job_res.data[0].get("title") or "Job opening"
        except Exception as e:
            logger.error(f"Failed to fetch candidate/job details in reject_application: {e}")
            
        log_activity_event(
            db,
            action="application_rejected",
            entity_type="applications",
            entity_id=app_id,
            actor_name="Recruiter",
            actor_id=user_id,
            metadata={"candidate_name": cand_name, "job_title": job_title}
        )
        
        background_tasks.add_task(
            trigger_whatsapp_notification_background,
            jwt_token,
            app_record["candidate_id"],
            app_record["job_opening_id"],
            "application_rejected"
        )
    return res.data[0] if res.data else {}

@router.get("/api/v1/applications/{app_id}/stages")
async def get_application_stages(app_id: str, db: Client = Depends(get_supabase)):
    res = db.table("interview_stages").select("*").eq("application_id", app_id).order("created_at", desc=False).execute()
    return res.data or []

@router.patch("/api/v1/applications/{app_id}/stage")
async def update_application_stage(app_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    data = await request.json()
    stage = data.get("stage")
    stage_status = data.get("stage_status")
    notes = data.get("notes") or ""
    
    res = db.table("applications").update({
        "stage": stage,
        "stage_status": stage_status,
        "stage_notes": notes
    }).eq("id", app_id).execute()
    
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to update application stage")
        
    app_record = res.data[0]
    
    valid_stages = ['screening']
    job_id = app_record.get("job_opening_id")
    if job_id:
        job_res = db.table("job_openings").select("custom_stages").eq("id", job_id).execute()
        if job_res.data:
            custom = job_res.data[0].get("custom_stages") or []
            valid_stages.extend(custom)
    else:
        valid_stages.extend(['technical', 'hr', 'final'])

    valid_stages_lower = [s.lower().strip() for s in valid_stages]
    if stage and stage.lower().strip() in valid_stages_lower:
        existing = db.table("interview_stages").select("id").eq("application_id", app_id).execute()
        order = len(existing.data or []) + 1
        
        outcome = "pending"
        if stage_status == "passed":
            outcome = "passed"
        elif stage_status == "failed":
            outcome = "failed"
        elif stage_status == "on_hold":
            outcome = "on_hold"
            
        if outcome == "failed" and not notes.strip():
            notes = "Stage failed."
            
        try:
            db.table("interview_stages").insert({
                "application_id": app_id,
                "stage_name": stage,
                "stage_order": order,
                "status": "completed",
                "outcome": outcome,
                "notes": notes
            }).execute()
        except Exception as stage_err:
            logger.warning(f"Could not log to interview_stages (continuing application update): {stage_err}")
        
    db.table("activity_log").insert({
        "action": "stage_updated",
        "entity_type": "applications",
        "entity_id": app_id,
        "actor_name": "Recruiter",
        "metadata": {"stage": stage, "status": stage_status}
    }).execute()

    job_id = app_record.get("job_opening_id")
    candidate_id = app_record.get("candidate_id")
    if job_id and candidate_id:
        try:
            job_res = db.table("job_openings").select("title", "client_name", "stage_notifications", "custom_stages").eq("id", job_id).execute()
            if job_res.data:
                job_info = job_res.data[0]
                stage_notifs = job_info.get("stage_notifications") or {}
                
                stage_key = stage.lower().replace(" ", "_")
                
                if stage_notifs.get(stage_key) is True or stage_notifs.get(stage) is True:
                    cand_res = db.table("candidates").select("full_name", "email", "phone").eq("id", candidate_id).execute()
                    if cand_res.data:
                        cand_info = cand_res.data[0]
                        cand_email = cand_info.get("email")
                        cand_phone = cand_info.get("phone") or "N/A"
                        cand_name = cand_info.get("full_name") or "Candidate"
                        job_title = job_info.get("title") or "Position"
                        client_name = job_info.get("client_name") or "Kozker"
                        
                        stage_label = stage.replace("_", " ").title()
                        if stage == "screening":
                            stage_label = "Screening"
                        elif stage == "technical":
                            stage_label = "Technical Test"
                        elif stage == "hr":
                            stage_label = "HR Interview"
                        elif stage == "final":
                            stage_label = "Final Decision"
                        
                        custom_stages = job_info.get("custom_stages") or []
                        if stage == "technical" and len(custom_stages) > 0:
                            stage_label = custom_stages[0]
                        elif stage == "hr" and len(custom_stages) > 1:
                            stage_label = custom_stages[1]
                        elif stage == "final" and len(custom_stages) > 2:
                            stage_label = custom_stages[2]
                            
                        subject = f"Application Status Update - {job_title} at {client_name}"
                        tracking_url = f"{FRONTEND_BASE_URL}/apply/status?email={cand_email}&appId={app_id}"
                        
                        html_body = f"""
                        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e5e5e5; border-radius: 4px;">
                            <h2 style="color: #0d9488; text-transform: uppercase; font-size: 16px; letter-spacing: 0.05em; border-bottom: 2px solid #0d9488; padding-bottom: 10px;">Kozker Recruitment Portal</h2>
                            <p style="font-size: 14px; color: #374151; line-height: 1.5;">Dear {cand_name},</p>
                            <p style="font-size: 14px; color: #374151; line-height: 1.5;">We are writing to update you on the progress of your application for the <strong>{job_title}</strong> role at <strong>{client_name}</strong>.</p>
                            <p style="font-size: 14px; color: #374151; line-height: 1.5;">Your application has successfully transitioned to the next phase: <span style="background-color: #f0fdfa; color: #0f766e; font-weight: bold; padding: 4px 8px; border-radius: 2px; border: 1px solid #ccfbf1; font-size: 12px; text-transform: uppercase;">{stage_label}</span>.</p>
                            <p style="font-size: 14px; color: #374151; line-height: 1.5;">To track your application status live and view next steps, please visit your personalized candidate dashboard:</p>
                            <div style="text-align: center; margin: 25px 0;">
                                <a href="{tracking_url}" style="background-color: #0d9488; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px; text-transform: uppercase; display: inline-block;">View Application Dashboard</a>
                            </div>
                            <hr style="border: 0; border-top: 1px solid #e5e5e5; margin: 20px 0;" />
                            <p style="font-size: 11px; color: #6b7280; line-height: 1.4;">If you did not submit this application, please disregard this email or contact support.</p>
                        </div>
                        """
                        
                        if cand_email:
                            send_email(cand_email, subject, html_body, sender_name="Kozker Recruitment")
                            
                        wa_log = f"\n========================================\n[WHATSAPP DISPATCH SIMULATED]\nTo: {cand_phone}\nMessage:\nHi {cand_name}, your application for {job_title} at {client_name} has moved to the {stage_label} stage! Track your status here: {tracking_url}\n========================================\n"
                        logger.info(wa_log)
                        
                        try:
                            from datetime import datetime
                            with open("requests.log", "a") as f:
                                f.write(f"[{datetime.utcnow().isoformat()}] WHATSAPP To: {cand_phone} | Message: {wa_log}\n")
                        except Exception as le:
                            logger.error(f"Failed to write WhatsApp log to requests.log: {le}")
                            
                        db.table("activity_log").insert({
                            "action": "candidate_notified",
                            "entity_type": "applications",
                            "entity_id": app_id,
                            "actor_name": "System",
                            "metadata": {
                                "stage": stage,
                                "email_sent": True,
                                "whatsapp_sent": True,
                                "candidate_phone": cand_phone,
                                "candidate_email": cand_email
                            }
                        }).execute()
                        
                        auth_header = request.headers.get("Authorization", "")
                        jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
                        background_tasks.add_task(
                            trigger_whatsapp_notification_background,
                            jwt_token,
                            candidate_id,
                            job_id,
                            "stage_updated",
                            {"stage": stage, "status": stage_status}
                        )
        except Exception as e:
            logger.error(f"Error sending stage update notification: {e}")
            
    return app_record

@router.get("/api/v1/applications/{app_id}/questions")
async def get_questions(app_id: str, db: Client = Depends(get_supabase)):
    res = db.table("applications").select("screening_questions").eq("id", app_id).execute()
    if not res.data:
        return []
    questions_list = res.data[0].get("screening_questions") or []
    healed_qs = ensure_questions_have_ids(questions_list, app_id, db)
    healed_qs.sort(key=lambda x: x.get("question_order", 1) or x.get("order", 1) or 1)
    return healed_qs


@router.patch("/api/v1/applications/{app_id}/accept")
@router.post("/api/v1/applications/{app_id}/accept")
async def accept_application_post(app_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    return await handle_accept_application_logic(app_id, background_tasks, request, db)
