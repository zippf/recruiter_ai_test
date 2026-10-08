import time
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, BackgroundTasks, Request
from supabase import Client

from app.core.config import USE_N8N
from app.core.logging import logger
from app.api.dependencies import get_supabase, get_current_user_id, get_admin_supabase_client
from app.schemas.common import JobRegenerateModel, JobOpeningUpdateModel, CandidateQueryCreateModel, SkillsApprovalModel, SharePostModel
from app.security.tenant_access import get_recruiter_owner_ids
from app.security.authentication import filter_valid_uuids
from app.security.authorization import deobfuscate_id
from app.services.job_service import enrich_job_with_form_config
from app.services.notification_service import create_system_notification, log_activity_event
from app.workers.ai_tasks import handle_regenerate_job_dispatch, regenerate_job_background_local, handle_scan_publish_dispatch, run_local_scan_publish
from app.services.query_service import generate_candidate_query_response, in_memory_queries
from app.services.matching_service import evaluate_candidate_matching_with_history

router = APIRouter()

@router.get("/api/v1/jobs")
async def get_jobs(
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    if recruiter_owner_ids or user_org_id:
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        all_reqs = admin_db.table("requirements").select("id, title, client_id, num_posts_requested, created_by, organization_id").eq("is_deleted", False).execute().data or []
        
        user_reqs = []
        for r in all_reqs:
            if user_org_id and r.get("organization_id") == user_org_id:
                user_reqs.append(r)
            elif r.get("created_by") and (r.get("created_by") in recruiter_owner_ids or r.get("created_by") in valid_uuids):
                user_reqs.append(r)
            elif not r.get("organization_id") and not r.get("created_by"):
                user_reqs.append(r)

        req_map = {r["id"]: r for r in user_reqs}
        req_ids = list(req_map.keys())
        
        if req_ids:
            client_ids = [r["client_id"] for r in user_reqs if r.get("client_id")]
            client_map = {}
            if client_ids:
                cli_data = admin_db.table("clients").select("id, name").in_("id", list(set(client_ids))).execute().data or []
                client_map = {c["id"]: c.get("name") for c in cli_data}
                
            jobs_data = admin_db.table("job_openings").select("*").in_("requirement_id", req_ids).eq("is_deleted", False).execute().data or []
            formatted = []
            for row in jobs_data:
                req = req_map.get(row.get("requirement_id")) or {}
                cli_name = client_map.get(req.get("client_id")) or "Generic Client"
                formatted.append(enrich_job_with_form_config({
                    **row,
                    "requirement_title": req.get("title") or "General Requirement",
                    "client_name": cli_name,
                    "client_id": row.get("client_id") or req.get("client_id"),
                    "num_posts_requested": req.get("num_posts_requested") or 1
                }))
            return formatted
    return []


@router.get("/api/v1/jobs/{job_id}")
async def get_job(
    job_id: str, 
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None)
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, _ = get_recruiter_owner_ids(authorization)
    
    clean_job_id = deobfuscate_id(job_id)
    res = admin_db.table("job_openings").select("*, requirements(id, title, created_by, clients(name))").eq("id", clean_job_id).eq("is_deleted", False).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    row = res.data[0]
    req = row.get("requirements") or {}
    if recruiter_owner_ids and req.get("created_by") and req.get("created_by") not in recruiter_owner_ids:
        raise HTTPException(status_code=404, detail="Job opening not found")
    cli = req.get("clients") or {}
    return enrich_job_with_form_config({
        **{k: v for k, v in row.items() if k != "requirements"},
        "client_name": cli.get("name") or "Generic Client"
    })


@router.delete("/api/v1/jobs/{job_id}")
async def delete_job(job_id: str, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Soft delete job opening
    res = db.table("job_openings").update({"is_deleted": True}).eq("id", job_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
        
    # Log activity
    db.table("activity_log").insert({
        "action": "job_deleted",
        "entity_type": "job_openings",
        "entity_id": job_id,
        "actor_name": "Recruiter",
        "metadata": {"job_title": res.data[0].get("title", "")}
    }).execute()
    
    return {"status": "success"}


@router.post("/api/v1/jobs/{job_id}/regenerate")
async def regenerate_job(job_id: str, payload: JobRegenerateModel, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    job = job_res.data[0]
    
    db.table("job_openings").update({"processing_status": "generating"}).eq("id", job_id).execute()
    
    auth_header = request.headers.get("Authorization", "")
    jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
    
    if USE_N8N:
        background_tasks.add_task(
            handle_regenerate_job_dispatch,
            job,
            payload.instruction,
            jwt_token
        )
    else:
        background_tasks.add_task(
            regenerate_job_background_local,
            job_id,
            payload.instruction,
            jwt_token
        )
        
    return {"status": "generating"}


@router.patch("/api/v1/jobs/{job_id}")
async def patch_job(job_id: str, job_update: JobOpeningUpdateModel, db: Client = Depends(get_supabase)):
    logger.info(f"===> patch_job CALLED for job_id: {job_id}, keys: {job_update.dict(exclude_unset=True)}")
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
        
    update_data = {}
    if job_update.title is not None:
        update_data["title"] = job_update.title
    if job_update.description is not None:
        update_data["description"] = job_update.description
    if job_update.responsibilities is not None:
        update_data["responsibilities"] = job_update.responsibilities
    if job_update.qualifications is not None:
        update_data["qualifications"] = job_update.qualifications
    if job_update.keywords is not None:
        update_data["keywords"] = job_update.keywords
    if job_update.salary_range is not None:
        update_data["salary_range"] = job_update.salary_range
    if job_update.status is not None:
        if job_update.status not in ['draft', 'confirmed', 'published', 'closed']:
            raise HTTPException(status_code=400, detail="Invalid status value")
        update_data["status"] = job_update.status
    if job_update.processing_status is not None:
        update_data["processing_status"] = job_update.processing_status
    if job_update.error_message is not None:
        update_data["error_message"] = job_update.error_message
    if job_update.custom_stages is not None:
        update_data["custom_stages"] = job_update.custom_stages
        
        if job_update.candidate_view_settings is None:
            current_res = db.table("job_openings").select("custom_stages", "candidate_view_settings", "stage_notifications").eq("id", job_id).execute()
            if current_res.data:
                current_job = current_res.data[0]
                old_stages = current_job.get("custom_stages") or []
                old_view = current_job.get("candidate_view_settings") or {}
                old_notif = current_job.get("stage_notifications") or {}
                
                new_view = {"screening": old_view.get("screening", False)}
                new_notif = {"screening": old_notif.get("screening", False)}
                
                for idx, next_stage in enumerate(job_update.custom_stages):
                    new_key = next_stage.lower().replace(" ", "_")
                    if idx < len(old_stages):
                        old_key = old_stages[idx].lower().replace(" ", "_")
                        new_view[new_key] = old_view.get(old_key, False)
                        new_notif[new_key] = old_notif.get(old_key, False)
                    else:
                        new_view[new_key] = False
                        new_notif[new_key] = False
                
                update_data["candidate_view_settings"] = new_view
                update_data["stage_notifications"] = new_notif
    if job_update.category is not None:
        update_data["category"] = job_update.category
    if job_update.sub_category is not None:
        update_data["sub_category"] = job_update.sub_category
    form_config_bundle = {}
    if job_update.form_fields is not None:
        form_config_bundle["form_fields"] = job_update.form_fields
    if job_update.form_theme is not None:
        form_config_bundle["form_theme"] = job_update.form_theme
    if job_update.form_bg_mode is not None:
        form_config_bundle["form_bg_mode"] = job_update.form_bg_mode
    if job_update.form_timer is not None:
        form_config_bundle["form_timer"] = job_update.form_timer
    if job_update.form_threshold is not None:
        form_config_bundle["form_threshold"] = job_update.form_threshold
    if job_update.form_start_date is not None:
        form_config_bundle["form_start_date"] = job_update.form_start_date
    if job_update.form_end_date is not None:
        form_config_bundle["form_end_date"] = job_update.form_end_date

    if form_config_bundle:
        current_cv = update_data.get("candidate_view_settings")
        if current_cv is None:
            current_cv = dict(job_res.data[0].get("candidate_view_settings") or {})
        else:
            current_cv = dict(current_cv)
        
        existing_cfg = dict(current_cv.get("_form_config") or {})
        existing_cfg.update(form_config_bundle)
        current_cv["_form_config"] = existing_cfg
        update_data["candidate_view_settings"] = current_cv

    if update_data:
        updated_job = None
        attempt_data = dict(update_data)
        while attempt_data:
            try:
                res = db.table("job_openings").update(attempt_data).eq("id", job_id).execute()
                if res.data:
                    updated_job = res.data[0]
                break
            except Exception as e:
                err_msg = f"{getattr(e, 'message', '')} {str(e)} {repr(e)}"
                logger.error(f"Error updating job_openings: {err_msg}")
                import re
                match = re.search(r"Could not find the '([^']+)' column", err_msg, re.IGNORECASE)
                if match:
                    missing_col = match.group(1)
                    if missing_col in attempt_data:
                        logger.warning(f"Removing missing column '{missing_col}' from update_data and retrying.")
                        del attempt_data[missing_col]
                        continue
                break

        if not updated_job:
            res = db.table("job_openings").select("*").eq("id", job_id).execute()
            if res.data:
                updated_job = res.data[0]
            else:
                raise HTTPException(status_code=500, detail="Failed to update job opening")
        
        try:
            db.table("activity_log").insert({
                "action": "job_updated",
                "entity_type": "job_openings",
                "entity_id": job_id,
                "actor_name": "Recruiter",
                "metadata": {"job_title": updated_job.get("title", ""), "updated_fields": list(update_data.keys())}
            }).execute()
        except Exception as e:
            logger.error(f"Failed to log job update activity: {e}")
        return enrich_job_with_form_config(updated_job)
    return enrich_job_with_form_config(job_res.data[0])


@router.post("/api/v1/jobs/{job_id}/confirm")
async def confirm_job(job_id: str, db: Client = Depends(get_supabase)):
    res = db.table("job_openings").update({"status": "confirmed"}).eq("id", job_id).execute()
    return res.data[0] if res.data else {}


@router.post("/api/v1/jobs/{job_id}/scan-and-publish")
async def scan_and_publish_job(job_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    # Fetch job details
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    
    job = job_res.data[0]
    db.table("job_openings").update({"processing_status": "skill_approval"}).eq("id", job_id).execute()
    
    auth_header = request.headers.get("Authorization", "")
    jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
    
    if USE_N8N:
        background_tasks.add_task(handle_scan_publish_dispatch, job, jwt_token)
    else:
        background_tasks.add_task(run_local_scan_publish, job_id, jwt_token)
        
    return {"status": "skill_approval"}


@router.post("/api/v1/jobs/{job_id}/queries")
async def post_candidate_query(job_id: str, payload: CandidateQueryCreateModel, db: Client = Depends(get_supabase)):
    job_id = deobfuscate_id(job_id)
    import uuid
    from datetime import datetime
    
    admin_db = get_admin_supabase_client()
    
    job = {}
    try:
        job_res = admin_db.table("job_openings").select("*, requirements(id, title, created_by, clients(name))").eq("id", job_id).eq("is_deleted", False).execute()
        if job_res.data:
            row = job_res.data[0]
            req = row.get("requirements") or {}
            cli = req.get("clients") or {}
            job = {
                **{k: v for k, v in row.items() if k != "requirements"},
                "client_name": cli.get("name") or "Generic Client",
                "created_by": req.get("created_by") or "usr-1"
            }
    except Exception as e:
        logger.error(f"Failed to fetch job details for query answer generator: {e}")
        
    ai_response = generate_candidate_query_response(job, payload.query_text)
    
    query_id = str(uuid.uuid4())
    new_query = {
        "id": query_id,
        "job_id": job_id,
        "candidate_email": payload.candidate_email,
        "query_text": payload.query_text,
        "ai_response": ai_response,
        "is_resolved": False,
        "source": "apply_form",
        "sender": "candidate",
        "is_ended": False,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    
    saved_to_db = False
    try:
        admin_db.table("candidate_queries").insert(new_query).execute()
        saved_to_db = True
    except Exception as e:
        err_msg = str(getattr(e, 'message', str(e)))
        logger.warning(f"Failed full insert into candidate_queries: {err_msg}. Retrying with core fields.")
        try:
            core_query = {
                "id": query_id,
                "job_id": job_id,
                "candidate_email": payload.candidate_email,
                "query_text": payload.query_text,
                "ai_response": ai_response,
                "is_resolved": False,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            admin_db.table("candidate_queries").insert(core_query).execute()
            saved_to_db = True
        except Exception as e2:
            logger.error(f"Failed core insert into candidate_queries: {e2}. Saving to in-memory dictionary.")
            
    if job_id not in in_memory_queries:
        in_memory_queries[job_id] = []
    in_memory_queries[job_id].append(new_query)
        
    recruiter_id = job.get("created_by") or "usr-1"
    notif_msg = f"Candidate ({payload.candidate_email}) submitted a query for role '{job.get('title', 'Active Opening')}': '{payload.query_text}'"
    try:
        admin_db.table("notifications").insert({
            "recruiter_id": recruiter_id,
            "title": "New Candidate Query",
            "message": notif_msg,
            "type": "upload",
            "is_read": False,
            "metadata": {"job_id": job_id, "query_id": query_id}
        }).execute()
    except Exception as ne:
        logger.warning(f"Failed to insert database notification for candidate query: {ne}")
        
    return new_query


@router.get("/api/v1/jobs/{job_id}/queries")
async def get_candidate_queries(job_id: str, email: Optional[str] = None, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    job_id = deobfuscate_id(job_id)
    if not email and not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized: Recruiter auth or candidate email filter required")
        
    admin_db = get_admin_supabase_client()
    try:
        query_builder = admin_db.table("candidate_queries").select("*").eq("job_id", job_id)
        if email:
            query_builder = query_builder.eq("candidate_email", email.strip())
        res = query_builder.order("created_at", desc=True).execute()
        
        db_queries = res.data or []
        mem_queries = in_memory_queries.get(job_id, [])
        if email:
            mem_queries = [mq for mq in mem_queries if mq.get("candidate_email", "").strip().lower() == email.strip().lower()]
            
        all_queries = {q["id"]: q for q in (db_queries + mem_queries)}
        return sorted(all_queries.values(), key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.warning(f"Failed to fetch candidate queries from Supabase: {e}. Falling back to in-memory dictionary.")
        mem_queries = in_memory_queries.get(job_id, [])
        if email:
            mem_queries = [mq for mq in mem_queries if mq.get("candidate_email", "").strip().lower() == email.strip().lower()]
        return sorted(mem_queries, key=lambda x: x["created_at"], reverse=True)


@router.get("/api/v1/jobs/{job_id}/queries/public")
async def get_public_resolved_queries(job_id: str, db: Client = Depends(get_supabase)):
    job_id = deobfuscate_id(job_id)
    db = get_admin_supabase_client()
    try:
        res = db.table("candidate_queries").select("query_text, ai_response, created_at").eq("job_id", job_id).eq("is_resolved", True).execute()
        db_queries = res.data or []
        
        mem_queries = in_memory_queries.get(job_id, [])
        mem_resolved = [
            {
                "query_text": mq.get("query_text"),
                "ai_response": mq.get("ai_response"),
                "created_at": mq.get("created_at")
            }
            for mq in mem_queries
            if mq.get("is_resolved") and mq.get("ai_response")
        ]
        
        all_resolved = []
        seen_queries = set()
        for q in (db_queries + mem_resolved):
            txt = q.get("query_text", "").strip()
            if txt and txt not in seen_queries:
                seen_queries.add(txt)
                all_resolved.append({
                    "query_text": q.get("query_text"),
                    "ai_response": q.get("ai_response"),
                    "created_at": q.get("created_at")
                })
        return sorted(all_resolved, key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Error in get_public_resolved_queries: {e}")
        mem_queries = in_memory_queries.get(job_id, [])
        mem_resolved = [
            {
                "query_text": mq.get("query_text"),
                "ai_response": mq.get("ai_response"),
                "created_at": mq.get("created_at")
            }
            for mq in mem_queries
            if mq.get("is_resolved") and mq.get("ai_response")
        ]
        return sorted(mem_resolved, key=lambda x: x["created_at"], reverse=True)


@router.get("/api/v1/jobs/{job_id}/skills")
async def get_job_skills(job_id: str, db: Client = Depends(get_supabase)):
    res = db.table("job_opening_skills").select("skills").eq("job_opening_id", job_id).execute()
    if res.data:
        return res.data[0].get("skills", [])
    return []

async def handle_approve_skills_logic(job_id: str, skills_data: SkillsApprovalModel, background_tasks: BackgroundTasks, request: Request, db: Client):
    # Format skills into a consolidated list
    skills_list = []
    import time
    for idx, skill in enumerate(skills_data.skills):
        skills_list.append({
            "id": skill.get("id") or f"sk-{idx + 1}-{int(time.time())}",
            "job_opening_id": job_id,
            "skill_name": skill["skill_name"],
            "weight": float(skill.get("weight") or 0.0),
            "skill_order": idx + 1,
            "approved": True
        })
        
    # Normalize weights so they sum to exactly 1.0 (to satisfy database trigger)
    total_w = sum(s["weight"] for s in skills_list)
    if total_w > 0:
        running_w = 0.0
        for idx, s in enumerate(skills_list):
            if idx == len(skills_list) - 1:
                s["weight"] = round(1.0 - running_w, 4)
            else:
                norm_w = round(s["weight"] / total_w, 4)
                s["weight"] = norm_w
                running_w += norm_w
    else:
        # If all weights are 0, distribute them equally
        n = len(skills_list)
        if n > 0:
            running_w = 0.0
            for idx, s in enumerate(skills_list):
                if idx == n - 1:
                    s["weight"] = round(1.0 - running_w, 4)
                else:
                    w = round(1.0 / n, 4)
                    s["weight"] = w
                    running_w += w

    db.table("job_opening_skills").upsert({
        "job_opening_id": job_id,
        "skills": skills_list
    }, on_conflict="job_opening_id").execute()
        
    # Mark job status as published
    db.table("job_openings").update({
        "status": "published",
        "processing_status": "matching"
    }).eq("id", job_id).execute()
    
    auth_header = request.headers.get("Authorization", "")
    user_id = get_current_user_id(auth_header)
    
    # Send activity logs
    job_title = "Job opening"
    try:
        job_res = db.table("job_openings").select("title").eq("id", job_id).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "")
    except Exception as e:
        logger.error(f"Failed to fetch job title in handle_approve_skills_logic: {e}")
        
    log_activity_event(
        db,
        action="skills_approved",
        entity_type="job_openings",
        entity_id=job_id,
        actor_name="Recruiter",
        actor_id=user_id,
        metadata={"job_title": job_title, "skills_count": len(skills_list)}
    )
    
    log_activity_event(
        db,
        action="job_published",
        entity_type="job_openings",
        entity_id=job_id,
        actor_name="Recruiter",
        actor_id=user_id,
        metadata={"job_title": job_title}
    )
    
    return {"status": "success"}

@router.put("/api/v1/jobs/{job_id}/skills")
async def save_skills_put(job_id: str, skills_data: SkillsApprovalModel, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    return await handle_approve_skills_logic(job_id, skills_data, background_tasks, request, db)


@router.post("/api/v1/jobs/{job_id}/approve-skills")
async def save_skills_post(job_id: str, skills_data: SkillsApprovalModel, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    return await handle_approve_skills_logic(job_id, skills_data, background_tasks, request, db)


@router.get("/api/v1/jobs/{job_id}/candidates")
async def get_ranked_candidates(
    job_id: str, 
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None)
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, _ = get_recruiter_owner_ids(authorization)
    clean_job_id = deobfuscate_id(job_id)
    
    # Verify job ownership
    job_res = admin_db.table("job_openings").select("requirement_id").eq("id", clean_job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    req_id = job_res.data[0].get("requirement_id")
    if req_id and recruiter_owner_ids:
        req_res = admin_db.table("requirements").select("created_by").eq("id", req_id).execute()
        if req_res.data and req_res.data[0].get("created_by") not in recruiter_owner_ids:
            return []

    res = db.table("job_candidates").select("*, candidates(*), applications(*)").eq("job_opening_id", clean_job_id).order("created_at", desc=True).execute()
    formatted = []
    seen_candidate_ids = set()
    for row in res.data:
        cand_id = row.get("candidate_id")
        if cand_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(cand_id)
        
        cand = row.get("candidates")
        if not cand:
            continue
            
        full_name = cand.get("full_name") or ""
        if not full_name or full_name.lower().strip() in ("unknown", "curriculum", "curriculum vitae"):
            continue
            
        app_rec = row.get("applications") or {}
        application_id = row.get("application_id")
        
        if not application_id:
            app_check = db.table("applications").select("*").eq("candidate_id", cand_id).eq("job_opening_id", job_id).execute()
            if app_check.data:
                app_rec = app_check.data[0]
                application_id = app_rec["id"]
                db.table("job_candidates").update({"application_id": application_id}).eq("id", row["id"]).execute()
            else:
                fuzzy_score = row.get("fuzzy_score") or 0.0
                try:
                    match_score = int(fuzzy_score)
                except (ValueError, TypeError):
                    match_score = 0
                strengths = row.get("strengths") or []
                skill_gaps = row.get("skill_gaps") or []
                match_reason = f"Automatically matched candidate with score {fuzzy_score}"
                
                app_res = db.table("applications").upsert({
                    "candidate_id": cand_id,
                    "job_opening_id": job_id,
                    "fuzzy_score": fuzzy_score,
                    "match_score": match_score,
                    "match_reason": match_reason,
                    "strengths": strengths[:3] if isinstance(strengths, list) else [],
                    "skill_gaps": skill_gaps[:3] if isinstance(skill_gaps, list) else [],
                    "screening_status": "pending",
                    "stage": "screening",
                    "stage_status": "pending"
                }, on_conflict="candidate_id,job_opening_id").execute()
                
                if app_res.data:
                    app_rec = app_res.data[0]
                    application_id = app_rec["id"]
                    db.table("job_candidates").update({"application_id": application_id}).eq("id", row["id"]).execute()
                    
        fuzzy_score = app_rec.get("fuzzy_score") if (app_rec and app_rec.get("fuzzy_score") is not None) else (row.get("fuzzy_score") or 0.0)

        formatted.append({
            "id": row["id"],
            "job_opening_id": row["job_opening_id"],
            "application_id": application_id,
            "fuzzy_score": fuzzy_score,
            "rank_order": row["rank_order"],
            "candidate_id": row["candidate_id"],
            "candidate_name": cand.get("full_name", "Unknown"),
            "experience_years": cand.get("experience_years", 0),
            "skills": cand.get("skills") or [],
            "strengths": row.get("strengths") or [],
            "skill_gaps": row.get("skill_gaps") or [],
            "stage": app_rec.get("stage") or "screening",
            "stage_status": app_rec.get("stage_status") or "pending",
            "parsed_resume": row.get("parsed_resume")
        })
        
    formatted.sort(key=lambda x: x["fuzzy_score"], reverse=True)
    for idx, item in enumerate(formatted, 1):
        item["rank_order"] = idx
        
    return formatted


@router.post("/api/v1/jobs/{job_id}/candidates/{cand_id}")
async def link_candidate_to_job(job_id: str, cand_id: str, db: Client = Depends(get_supabase)):
    cand_res = db.table("candidates").select("*").eq("id", cand_id).execute()
    skills_res = db.table("job_opening_skills").select("skills").eq("job_opening_id", job_id).execute()
    
    if not cand_res.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    cand = cand_res.data[0]
    if "parsed_resume_json" in cand and cand["parsed_resume_json"]:
        if isinstance(cand["parsed_resume_json"], dict) and "raw_text" in cand["parsed_resume_json"]:
            cand["raw_text"] = cand["parsed_resume_json"]["raw_text"]
    approved_skills = skills_res.data[0].get("skills", []) if skills_res.data else []
    
    cand_skills = [s.lower() for s in (cand.get("skills") or [])]
    cand_raw_text = cand.get("raw_text") or ""
    
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
    
    if not app_res.data:
        raise HTTPException(status_code=400, detail="Failed to link candidate")
        
    new_app = app_res.data[0]
    
    existing_jc_cand = db.table("job_candidates").select("rank_order").eq("job_opening_id", job_id).eq("candidate_id", cand_id).execute()
    if existing_jc_cand.data:
        rank = existing_jc_cand.data[0]["rank_order"]
    else:
        existing_jc = db.table("job_candidates").select("*").eq("job_opening_id", job_id).execute()
        rank = len(existing_jc.data) + 1
    
    db.table("job_candidates").upsert({
        "job_opening_id": job_id,
        "candidate_id": cand_id,
        "application_id": new_app["id"],
        "fuzzy_score": matched_score,
        "rank_order": rank,
        "strengths": strengths[:3],
        "skill_gaps": skill_gaps[:3],
        "parsed_resume": cand.get("parsed_resume_json")
    }, on_conflict="job_opening_id,candidate_id").execute()
    
    log_activity_event(
        db,
        action="candidate_linked",
        entity_type="applications",
        entity_id=new_app["id"],
        actor_name="Recruiter",
        metadata={"candidate_name": cand.get("full_name")}
    )
    
    return {"success": True, "application": new_app}


@router.post("/api/v1/jobs/{job_id}/share-linkedin")
async def share_job_linkedin(job_id: str, payload: SharePostModel, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    connection_res = db.table("linkedin_accounts").select("*").eq("user_id", user_id).execute()
    if not connection_res.data:
        raise HTTPException(status_code=400, detail="LinkedIn account is not connected. Please connect it under Settings.")
        
    account = connection_res.data[0]
    company_page_id = account.get("company_page_id")
    access_token = account.get("linkedin_access_token")
    linkedin_member_id = account.get("linkedin_member_id")
    
    job_title = "Job Opening"
    try:
        job_res = db.table("job_openings").select("title").eq("id", job_id).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "Job Opening")
    except Exception:
        pass
        
    is_mock = access_token.startswith("mock_")
    
    try:
        if is_mock:
            import asyncio
            await asyncio.sleep(1)
            
            target_desc = f"LinkedIn Company Page '{company_page_id}'" if company_page_id else "your LinkedIn Personal Feed"
            
            create_system_notification(
                db,
                user_id,
                "Job Shared on LinkedIn (Simulated)",
                f"Job opening '{job_title}' was successfully shared to {target_desc} (Simulated).",
                "job_generation",
                {"job_id": job_id}
            )
            log_activity_event(
                db,
                action="job_shared_linkedin",
                entity_type="jobs",
                entity_id=job_id,
                actor_name="Recruiter",
                actor_id=user_id,
                metadata={
                    "job_title": job_title, 
                    "company_page_id": company_page_id,
                    "shared_to": "company" if company_page_id else "personal",
                    "simulated": True
                }
            )
            return {
                "success": True, 
                "post_id": "urn:li:share:mock_share_998877", 
                "simulated": True,
                "shared_to": "company" if company_page_id else "personal",
                "message": f"Successfully published to {target_desc} (Simulated)."
            }
            
        author_urn = None
        is_personal = True
        
        if company_page_id and company_page_id.strip():
            author_urn = company_page_id.strip()
            if not author_urn.startswith("urn:li:"):
                author_urn = f"urn:li:organization:{author_urn}"
            is_personal = False
        else:
            if not linkedin_member_id:
                raise Exception("LinkedIn Member ID is missing from your connection details. Please reconnect your account.")
            author_urn = f"urn:li:person:{linkedin_member_id}"
            
        ugc_post_payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": payload.text
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        async with httpx.AsyncClient() as client:
            ugc_url = "https://api.linkedin.com/v2/ugcPosts"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json"
            }
            
            res = await client.post(ugc_url, json=ugc_post_payload, headers=headers)
            
            if res.status_code == 403 and not is_personal and linkedin_member_id:
                logger.warning("Failed to post to LinkedIn Company Page (Status 403). Retrying to post to Personal Profile...")
                author_urn = f"urn:li:person:{linkedin_member_id}"
                ugc_post_payload["author"] = author_urn
                res = await client.post(ugc_url, json=ugc_post_payload, headers=headers)
                is_personal = True
                
            if res.status_code not in (200, 201):
                raise Exception(f"LinkedIn API error (Status {res.status_code}): {res.text}")
                
            res_data = res.json()
            post_id = res_data.get("id") or "urn:li:share:unknown"
            
            target_description = "your LinkedIn Personal Feed" if is_personal else f"LinkedIn Company Page '{company_page_id}'"
            
            create_system_notification(
                db,
                user_id,
                "Job Shared on LinkedIn",
                f"Job opening '{job_title}' was successfully shared to {target_description}.",
                "job_generation",
                {"job_id": job_id}
            )
            log_activity_event(
                db,
                action="job_shared_linkedin",
                entity_type="jobs",
                entity_id=job_id,
                actor_name="Recruiter",
                actor_id=user_id,
                metadata={
                    "job_title": job_title, 
                    "company_page_id": company_page_id if not is_personal else None, 
                    "shared_to": "personal" if is_personal else "company",
                    "post_id": post_id
                }
            )
            return {
                "success": True, 
                "post_id": post_id,
                "shared_to": "personal" if is_personal else "company",
                "message": f"Successfully published to {target_description}."
            }
            
    except Exception as e:
        logger.error(f"Error sharing job on LinkedIn: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to post to LinkedIn: {str(e)}")


@router.post("/api/v1/jobs/{job_id}/scan-publish")
@router.post("/api/v1/jobs/{job_id}/scan-and-publish")
@router.post("/api/v1/jobs/{job_id}/scan-and-publish")
async def scan_and_publish_job(job_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    # Fetch job details
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    
    job = job_res.data[0]
    db.table("job_openings").update({"processing_status": "skill_approval"}).eq("id", job_id).execute()
    
    auth_header = request.headers.get("Authorization", "")
    jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
    
    if USE_N8N:
        background_tasks.add_task(handle_scan_publish_dispatch, job, jwt_token)
    else:
        background_tasks.add_task(run_local_scan_publish, job_id, jwt_token)
        
    return {"status": "skill_approval"}


@router.post("/api/v1/jobs/{job_id}/scan-publish")
@router.post("/api/v1/jobs/{job_id}/scan-and-publish")
@router.post("/api/v1/jobs/{job_id}/scan-and-publish")
async def scan_and_publish_job(job_id: str, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase)):
    # Fetch job details
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
    
    job = job_res.data[0]
    db.table("job_openings").update({"processing_status": "skill_approval"}).eq("id", job_id).execute()
    
    auth_header = request.headers.get("Authorization", "")
    jwt_token = auth_header.split(" ")[1] if auth_header.startswith("Bearer ") else ""
    
    if USE_N8N:
        background_tasks.add_task(handle_scan_publish_dispatch, job, jwt_token)
    else:
        background_tasks.add_task(run_local_scan_publish, job_id, jwt_token)
        
    return {"status": "skill_approval"}


@router.get("/api/v1/jobs/{job_id}/queries")
async def get_candidate_queries(job_id: str, email: Optional[str] = None, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    job_id = deobfuscate_id(job_id)
    if not email and not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized: Recruiter auth or candidate email filter required")
        
    admin_db = get_admin_supabase_client()
    try:
        query_builder = admin_db.table("candidate_queries").select("*").eq("job_id", job_id)
        if email:
            query_builder = query_builder.eq("candidate_email", email.strip())
        res = query_builder.order("created_at", desc=True).execute()
        
        db_queries = res.data or []
        mem_queries = in_memory_queries.get(job_id, [])
        if email:
            mem_queries = [mq for mq in mem_queries if mq.get("candidate_email", "").strip().lower() == email.strip().lower()]
            
        all_queries = {q["id"]: q for q in (db_queries + mem_queries)}
        return sorted(all_queries.values(), key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.warning(f"Failed to fetch candidate queries from Supabase: {e}. Falling back to in-memory dictionary.")
        mem_queries = in_memory_queries.get(job_id, [])
        if email:
            mem_queries = [mq for mq in mem_queries if mq.get("candidate_email", "").strip().lower() == email.strip().lower()]
        return sorted(mem_queries, key=lambda x: x["created_at"], reverse=True)


@router.get("/api/v1/jobs/{job_id}/queries/public")
async def get_public_resolved_queries(job_id: str, db: Client = Depends(get_supabase)):
    job_id = deobfuscate_id(job_id)
    db = get_admin_supabase_client()
    try:
        # Fetch resolved candidate queries for this job (omitting email/ID for privacy)
        res = db.table("candidate_queries").select("query_text, ai_response, created_at").eq("job_id", job_id).eq("is_resolved", True).execute()
        db_queries = res.data or []
        
        # Merge with in-memory resolved queries for this job
        mem_queries = in_memory_queries.get(job_id, [])
        mem_resolved = [
            {
                "query_text": mq.get("query_text"),
                "ai_response": mq.get("ai_response"),
                "created_at": mq.get("created_at")
            }
            for mq in mem_queries
            if mq.get("is_resolved") and mq.get("ai_response")
        ]
        
        # Merge and deduplicate by query_text
        all_resolved = []
        seen_queries = set()
        for q in (db_queries + mem_resolved):
            txt = q.get("query_text", "").strip()
            if txt and txt not in seen_queries:
                seen_queries.add(txt)
                all_resolved.append({
                    "query_text": q.get("query_text"),
                    "ai_response": q.get("ai_response"),
                    "created_at": q.get("created_at")
                })
        return sorted(all_resolved, key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Error in get_public_resolved_queries: {e}")
        mem_queries = in_memory_queries.get(job_id, [])
        mem_resolved = [
            {
                "query_text": mq.get("query_text"),
                "ai_response": mq.get("ai_response"),
                "created_at": mq.get("created_at")
            }
            for mq in mem_queries
            if mq.get("is_resolved") and mq.get("ai_response")
        ]
        return sorted(mem_resolved, key=lambda x: x["created_at"], reverse=True)
