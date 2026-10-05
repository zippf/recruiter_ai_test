from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, BackgroundTasks, Request
from supabase import Client

from app.core.config import USE_N8N, PUBLIC_BACKEND_URL, CALLBACK_SECRET, N8N_GENERATE_JOBS_URL
from app.core.logging import logger
from app.api.dependencies import get_supabase, get_current_user_id, get_admin_supabase_client
from app.schemas.common import RequirementModel, RequirementUpdateModel, AppendJobsModel
from app.security.tenant_access import get_recruiter_owner_ids
from app.security.authentication import filter_valid_uuids
from app.workers.resume_parser import extract_text_from_file
from app.workers.ai_tasks import handle_generate_jobs_dispatch, generate_job_openings_background, append_jobs_background_fallback
from app.integrations.n8n_client import dispatch_n8n_webhook

router = APIRouter()

@router.post("/api/v1/requirements/parse-file")
async def parse_requirement_file(file: UploadFile = File(...)):
    contents = await file.read()
    text = extract_text_from_file(contents, file.filename)
    return {"text": text}


@router.get("/api/v1/requirements")
async def get_requirements(
    db: Client = Depends(get_supabase),
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    if recruiter_owner_ids or user_org_id:
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        all_reqs = admin_db.table("requirements").select("*").eq("is_deleted", False).execute().data or []
        
        filtered = []
        for r in all_reqs:
            if user_org_id and r.get("organization_id") == user_org_id:
                filtered.append(r)
            elif r.get("created_by") and (r.get("created_by") in recruiter_owner_ids or r.get("created_by") in valid_uuids):
                filtered.append(r)
            elif not r.get("organization_id") and not r.get("created_by"):
                filtered.append(r)
        return filtered
    return []


@router.put("/api/v1/requirements/{req_id}")
async def update_requirement(req_id: str, req: RequirementUpdateModel, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    update_data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    
    # Fetch current requirement details first
    curr_req_res = db.table("requirements").select("*").eq("id", req_id).execute()
    if not curr_req_res.data:
        raise HTTPException(status_code=404, detail="Requirement not found")
    old_req = curr_req_res.data[0]
    
    if not update_data:
        return old_req

    # Check if any structural fields are being updated
    structural_fields = {"title", "description", "skills", "experience_min", "experience_max", "budget_min", "budget_max", "seniority", "num_posts_requested"}
    has_structural_change = any(f in update_data for f in structural_fields)
    
    if has_structural_change:
        # Soft delete existing job openings first so they are replaced by the new generation
        db.table("job_openings").update({"is_deleted": True}).eq("requirement_id", req_id).execute()
        
    # Check status transitions and job existence
    new_status = update_data.get("status") or old_req.get("status")
    new_num_posts = update_data.get("num_posts_requested")
    if new_num_posts is None:
        new_num_posts = old_req.get("num_posts_requested") or 1
        
    # Verify if job openings already exist
    jobs_res = db.table("job_openings").select("id").eq("requirement_id", req_id).eq("is_deleted", False).execute()
    existing_jobs_count = len(jobs_res.data) if jobs_res.data else 0
    
    trigger_generation = False
    if (update_data.get("status") == "generating") or (
        new_status in ["generating", "ready"] and (
            existing_jobs_count == 0 or new_num_posts > existing_jobs_count
        )
    ):
        trigger_generation = True
        update_data["status"] = "generating" # force to generating during process
            
    res = db.table("requirements").update(update_data).eq("id", req_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Requirement not found")
        
    new_req = res.data[0]
        
    from app.services.notification_service import log_activity_event
    log_activity_event(
        db=db,
        action="requirement_updated",
        entity_type="requirements",
        entity_id=req_id,
        actor_name="Recruiter",
        metadata={"req_title": new_req.get("title", "")}
    )
    
    if trigger_generation:
        auth_header = request.headers.get("Authorization", "")
        jwt_token = ""
        if auth_header:
            if auth_header.startswith("Bearer "):
                jwt_token = auth_header.split(" ")[1]
            elif auth_header.startswith("eyJ"):
                jwt_token = auth_header
                
        if USE_N8N:
            background_tasks.add_task(
                handle_generate_jobs_dispatch,
                new_req,
                jwt_token
            )
        else:
            background_tasks.add_task(
                generate_job_openings_background,
                req_id,
                new_req.get("client_id"),
                new_req.get("title"),
                new_req.get("description"),
                new_req.get("skills") or [],
                new_req.get("experience_min") or 0,
                new_req.get("experience_max") or 0,
                new_req.get("seniority"),
                new_req.get("budget_min") or 0.0,
                new_req.get("budget_max") or 0.0,
                new_req.get("num_posts_requested") or 1,
                jwt_token
            )
            
    return new_req


@router.post("/api/v1/requirements/{req_id}/append-jobs")
async def append_jobs_to_requirement(
    req_id: str,
    payload: AppendJobsModel,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Client = Depends(get_supabase),
    user_id: Optional[str] = Depends(get_current_user_id)
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    # Fetch requirement
    req_res = db.table("requirements").select("*").eq("id", req_id).execute()
    if not req_res.data:
        raise HTTPException(status_code=404, detail="Requirement not found")
    requirement = req_res.data[0]
    
    # Update requirement status to generating
    db.table("requirements").update({"status": "generating"}).eq("id", req_id).execute()
    
    # Forward user's JWT token
    auth_header = request.headers.get("Authorization", "")
    jwt_token = ""
    if auth_header:
        if auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]
        elif auth_header.startswith("eyJ"):
            jwt_token = auth_header
            
    # Resolve client name
    client_name = "Generic Client"
    try:
        client_res = db.table("clients").select("name").eq("id", requirement["client_id"]).execute()
        if client_res.data:
            client_name = client_res.data[0]["name"]
    except Exception as e:
        logger.error(f"Failed to fetch client name: {e}")
        
    # Append-mode callback URL passes append_mode=true query parameter
    callback_url = f"{PUBLIC_BACKEND_URL}/api/v1/callbacks/job-openings?append_mode=true&posts_to_add={payload.num_posts_to_add}"
    
    # Trigger n8n webhook with the new sub-requirement description and requested number of posts
    dispatch_payload = {
        "automation_type": "generate_job_openings",
        "request_id": f"reqjob_{req_id}_append",
        "callback_url": callback_url,
        "authorization": f"Bearer {CALLBACK_SECRET}",
        "auth_header": f"Bearer {CALLBACK_SECRET}",
        "requirement": {
            "requirement_id": req_id,
            "client_id": requirement["client_id"],
            "client_name": client_name,
            "title": f"{requirement['title']} (Additional)",
            "description": payload.additional_description, # Use the new sub-requirement description
            "skills": requirement["skills"],
            "experience_min": requirement.get("experience_min") or 0,
            "experience_max": requirement.get("experience_max") or 30,
            "budget_min": requirement.get("budget_min") or 0.0,
            "budget_max": requirement.get("budget_max") or 0.0,
            "currency": "INR",
            "seniority": requirement["seniority"],
            "location": "Bangalore / Remote",
            "employment_type": "full_time",
            "notes": f"Parent notes: {requirement.get('notes') or ''}",
            "num_posts_requested": payload.num_posts_to_add
        },
        "ai_instruction": {
            "instruction": f"Generate {payload.num_posts_to_add} new job openings based on the additional description: {payload.additional_description}",
            "tone": "professional",
            "output_language": "en",
            "must_include": requirement["skills"],
            "avoid": ["casual wording"]
        },
        "metadata": {"append_mode": True}
    }
    
    if USE_N8N:
        background_tasks.add_task(
            dispatch_n8n_webhook,
            N8N_GENERATE_JOBS_URL,
            dispatch_payload,
            "generate_jobs_append"
        )
    else:
        background_tasks.add_task(
            append_jobs_background_fallback,
            req_id,
            payload.num_posts_to_add,
            payload.additional_description,
            jwt_token
        )
        
    return {"status": "generating"}


@router.delete("/api/v1/requirements/{req_id}")
async def delete_requirement(req_id: str, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Soft delete requirement
    res = db.table("requirements").update({"is_deleted": True}).eq("id", req_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Requirement not found")
        
    # Soft delete linked job openings
    db.table("job_openings").update({"is_deleted": True}).eq("requirement_id", req_id).execute()
    
    # Log activity
    from app.services.notification_service import log_activity_event
    log_activity_event(
        db=db,
        action="requirement_deleted",
        entity_type="requirements",
        entity_id=req_id,
        actor_name="Recruiter",
        metadata={"req_title": res.data[0].get("title", "")}
    )
    
    return {"status": "success"}


@router.post("/api/v1/requirements")
async def create_requirement(req: RequirementModel, background_tasks: BackgroundTasks, request: Request, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    payload = {
        "client_id": req.client_id,
        "title": req.title,
        "description": req.description,
        "skills": req.skills,
        "experience_min": req.experience_min,
        "experience_max": req.experience_max,
        "budget_min": req.budget_min,
        "budget_max": req.budget_max,
        "seniority": req.seniority,
        "notes": req.notes,
        "num_posts_requested": req.num_posts_requested,
        "status": "generating"
    }
    if user_id:
        payload["created_by"] = user_id
    res = db.table("requirements").insert(payload).execute()
    
    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create requirement")
    
    new_req = res.data[0]
    
    # Forward the user's JWT token
    auth_header = request.headers.get("Authorization", "")
    jwt_token = ""
    if auth_header:
        if auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]
        elif auth_header.startswith("eyJ"):
            jwt_token = auth_header
    
    # Trigger background job openings generation task
    if USE_N8N:
        background_tasks.add_task(
            handle_generate_jobs_dispatch,
            new_req,
            jwt_token
        )
    else:
        background_tasks.add_task(
            generate_job_openings_background,
            new_req["id"],
            req.client_id,
            req.title,
            req.description,
            req.skills,
            req.experience_min,
            req.experience_max,
            req.seniority,
            req.budget_min,
            req.budget_max,
            req.num_posts_requested,
            jwt_token
        )
    
    # Log activity
    from app.services.notification_service import log_activity_event
    log_activity_event(
        db=db,
        action="requirement_created",
        entity_type="requirements",
        entity_id=new_req["id"],
        actor_name="Recruiter",
        metadata={"req_title": req.title}
    )
    
    return new_req
