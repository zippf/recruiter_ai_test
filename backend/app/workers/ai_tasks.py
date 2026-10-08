"""
AI Tasks worker.

Contains background task functions for AI-driven workflows:
- Job generation (n8n dispatch + local fallback)
- Job regeneration (n8n dispatch + local fallback)
- Skill scanning/publishing (n8n dispatch + local fallback)
- Candidate matching (n8n dispatch + local fallback)
- Screening question generation (n8n dispatch + local fallback)

Extracted from main_commented (1).py lines 1915–2563.

All functions preserve the exact same argument signatures, payload field
names, callback URLs, and fallback behavior as the monolith.
"""
import asyncio
from typing import List

from app.core.config import (
    CALLBACK_SECRET,
    N8N_EXTRACT_SKILLS_URL,
    N8N_GENERATE_JOBS_URL,
    N8N_GENERATE_QUESTIONS_URL,
    N8N_MATCH_CANDIDATES_URL,
    N8N_REGENERATE_JOBS_URL,
    PUBLIC_BACKEND_URL,
    SUPABASE_KEY,
    SUPABASE_URL,
)
from app.core.logging import logger
from app.integrations.n8n_client import dispatch_n8n_webhook
from app.integrations.supabase_client import get_admin_supabase_client, get_safe_supabase_client
from app.services.notification_service import create_system_notification, log_activity_event


# ---------------------------------------------------------------------------
# Job generation dispatch
# ---------------------------------------------------------------------------

async def handle_generate_jobs_dispatch(new_req: dict, jwt_token: str) -> None:
    """Dispatch job-generation request to n8n; mark requirement failed on n8n error."""
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)

    client_name = "Generic Client"
    try:
        client_res = db.table("clients").select("name").eq("id", new_req["client_id"]).execute()
        if client_res.data:
            client_name = client_res.data[0]["name"]
    except Exception as exc:
        logger.error(f"Failed to fetch client name for n8n payload: {exc}")

    callback_url = f"{PUBLIC_BACKEND_URL}/api/v1/callbacks/job-openings"
    payload = {
        "automation_type": "generate_job_openings",
        "request_id": f"reqjob_{new_req['id']}",
        "callback_url": callback_url,
        "authorization": f"Bearer {CALLBACK_SECRET}",
        "auth_header": f"Bearer {CALLBACK_SECRET}",
        "requirement": {
            "requirement_id": new_req["id"],
            "client_id": new_req["client_id"],
            "client_name": client_name,
            "title": new_req["title"],
            "description": new_req["description"],
            "skills": new_req["skills"],
            "experience_min": new_req.get("experience_min") or 0,
            "experience_max": new_req.get("experience_max") or 0,
            "budget_min": new_req.get("budget_min") or 0.0,
            "budget_max": new_req.get("budget_max") or 0.0,
            "currency": "INR",
            "seniority": new_req["seniority"],
            "location": "Bangalore / Remote",
            "employment_type": "full_time",
            "notes": new_req["notes"],
            "num_posts_requested": new_req["num_posts_requested"],
        },
        "ai_instruction": {
            "instruction": f"Generate {new_req['num_posts_requested']} job openings: technical, leadership, or concise as specified.",
            "tone": "professional",
            "output_language": "en",
            "must_include": new_req["skills"],
            "avoid": ["casual wording"],
        },
        "metadata": {},
    }

    success = await dispatch_n8n_webhook(N8N_GENERATE_JOBS_URL, payload, "generate_jobs")
    if not success:
        logger.warning("n8n dispatch failed for generate_jobs.")
        try:
            db.table("requirements").update({"status": "failed"}).eq("id", new_req["id"]).execute()
            create_system_notification(
                db,
                new_req.get("created_by"),
                "Job Generation Failed",
                f"N8N workflow failed to generate jobs for requirement '{new_req.get('title')}'",
                "error",
                {"requirement_id": new_req["id"], "error_type": "n8n_dispatch_failed"},
            )
            log_activity_event(
                db,
                action="n8n_dispatch_failed",
                entity_type="requirements",
                entity_id=new_req["id"],
                actor_name="System",
                actor_id=new_req.get("created_by"),
                metadata={"error_context": "generate_jobs", "req_title": new_req.get("title")},
            )
        except Exception as exc:
            logger.error(f"Failed to update requirement status to failed: {exc}")


# ---------------------------------------------------------------------------
# Job regeneration dispatch + local fallback
# ---------------------------------------------------------------------------

async def handle_regenerate_job_dispatch(job: dict, instruction: str, jwt_token: str) -> None:
    """Dispatch job-regen request to n8n; fall back to local if n8n unavailable."""
    callback_url = f"{PUBLIC_BACKEND_URL}/api/v1/callbacks/job-openings/regenerate"
    payload = {
        "automation_type": "regenerate_job_opening",
        "job_opening_id": job["id"],
        "requirement_id": job.get("requirement_id"),
        "instruction": instruction,
        "callback_url": callback_url,
        "auth_header": f"Bearer {CALLBACK_SECRET}",
        "job_details": {
            "title": job.get("title"),
            "description": job.get("description"),
            "responsibilities": job.get("responsibilities") or [],
            "qualifications": job.get("qualifications") or [],
            "salary_range": job.get("salary_range"),
            "keywords": job.get("keywords") or [],
            "status": job.get("status"),
            "category": job.get("category"),
            "sub_category": job.get("sub_category"),
        },
    }
    success = await dispatch_n8n_webhook(N8N_REGENERATE_JOBS_URL, payload, "regenerate_job")
    if not success:
        logger.warning("n8n dispatch failed for regenerate_job, falling back to local fallback")
        regenerate_job_background_local(job["id"], instruction, jwt_token)


def regenerate_job_background_local(job_id: str, instruction: str, jwt_token: str) -> None:
    """Local fallback: rewrite job text using simple template logic."""
    logger.info(f"Running local fallback regeneration for job {job_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        return
    job = job_res.data[0]

    new_title = (
        f"{job['title']} (Regenerated)"
        if "Regenerated" not in job.get("title", "")
        else job["title"]
    )
    new_desc = f"{job['description']}\n\n[Regenerated with instruction: \"{instruction}\"]"

    db.table("job_openings").update(
        {"title": new_title, "description": new_desc, "processing_status": "ready"}
    ).eq("id", job_id).execute()

    recruiter_id = None
    try:
        req_res = db.table("requirements").select("created_by").eq("id", job.get("requirement_id")).execute()
        if req_res.data:
            recruiter_id = req_res.data[0].get("created_by")
    except Exception as exc:
        logger.error(f"Failed to resolve recruiter_id in regenerate_job_background_local: {exc}")

    if recruiter_id:
        create_system_notification(
            db, recruiter_id, "Job Regenerated Successfully",
            f"Job opening '{new_title}' has been successfully regenerated using instruction '{instruction}'.",
            "job_generation", {"job_opening_id": job_id, "job_title": new_title},
        )
        log_activity_event(
            db, action="job_regenerated", entity_type="job_openings", entity_id=job_id,
            actor_name="System", actor_id=recruiter_id,
            metadata={"job_title": new_title, "instruction": instruction},
        )


# ---------------------------------------------------------------------------
# Skill scan / publish dispatch + local fallback
# ---------------------------------------------------------------------------

async def handle_scan_publish_dispatch(job: dict, jwt_token: str) -> None:
    """Dispatch skill-extraction request to n8n; fall back to local if unavailable."""
    callback_url = f"{PUBLIC_BACKEND_URL}/api/v1/callbacks/job-skills"
    payload = {
        "job_opening_id": job["id"],
        "title": job["title"],
        "description": job["description"],
        "responsibilities": job["responsibilities"],
        "qualifications": job["qualifications"],
        "keywords": job["keywords"],
        "salary_range": job["salary_range"],
        "category": job.get("category"),
        "sub_category": job.get("sub_category"),
        "callback_url": callback_url,
        "authorization": f"Bearer {CALLBACK_SECRET}",
        "auth_header": f"Bearer {CALLBACK_SECRET}",
    }
    success = await dispatch_n8n_webhook(N8N_EXTRACT_SKILLS_URL, payload, "extract_skills")
    if not success:
        logger.warning("n8n dispatch failed for extract_skills, falling back to local execution")
        run_local_scan_publish(job["id"], jwt_token)


def run_local_scan_publish(job_id: str, jwt_token: str) -> None:
    """Local fallback: extract keyword-based skills from the job and save them."""
    import time
    logger.info(f"Running local skill scan/publish for job {job_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        return
    job = job_res.data[0]

    default_skills = [k for k in (job.get("keywords") or []) if k][:10]
    weights = [10.0 / max(len(default_skills), 1)] * len(default_skills)

    skills_list = []
    for idx, skill_name in enumerate(default_skills):
        skills_list.append({
            "id": f"sk-{idx + 1}-{int(time.time())}",
            "job_opening_id": job_id,
            "skill_name": skill_name,
            "weight": weights[idx],
            "skill_order": idx + 1,
            "approved": False,
        })

    db.table("job_opening_skills").upsert(
        {"job_opening_id": job_id, "skills": skills_list}, on_conflict="job_opening_id"
    ).execute()
    db.table("job_openings").update({"processing_status": "skill_approval"}).eq("id", job_id).execute()

    recruiter_id = None
    try:
        req_res = db.table("requirements").select("created_by").eq("id", job.get("requirement_id")).execute()
        if req_res.data:
            recruiter_id = req_res.data[0].get("created_by")
    except Exception as exc:
        logger.error(f"Failed to resolve recruiter_id in run_local_scan_publish: {exc}")

    if recruiter_id:
        create_system_notification(
            db, recruiter_id, "Skills Ready for Approval",
            f"Skills for job '{job.get('title', '')}' are ready for your review.",
            "job_generation", {"job_opening_id": job_id},
        )


# ---------------------------------------------------------------------------
# Screening question generation dispatch + local fallback
# ---------------------------------------------------------------------------

async def handle_generate_questions_dispatch(
    app_record: dict, cand: dict, job: dict, req: dict, jwt_token: str
) -> None:
    """Dispatch question-generation request to n8n; fall back to local if unavailable."""
    callback_url = f"{PUBLIC_BACKEND_URL}/api/v1/callbacks/screening-questions"
    payload = {
        "application_id": app_record["id"],
        "callback_url": callback_url,
        "authorization": f"Bearer {CALLBACK_SECRET}",
        "auth_header": f"Bearer {CALLBACK_SECRET}",
        "candidate": {
            "id": cand["id"],
            "full_name": cand["full_name"],
            "email": cand["email"],
            "skills": cand.get("skills") or [],
            "experience_years": cand.get("experience_years") or 0,
            "raw_text": cand.get("raw_text") or "",
        },
        "job_details": {
            "id": job.get("id"),
            "title": job.get("title"),
            "description": job.get("description"),
            "responsibilities": job.get("responsibilities"),
            "qualifications": job.get("qualifications"),
            "keywords": job.get("keywords"),
            "category": job.get("category"),
            "sub_category": job.get("sub_category"),
        },
        "requirement_details": {
            "id": req.get("id"),
            "title": req.get("title"),
            "description": req.get("description"),
            "skills": req.get("skills"),
            "experience_min": req.get("experience_min"),
            "experience_max": req.get("experience_max"),
            "seniority": req.get("seniority"),
        },
    }
    success = await dispatch_n8n_webhook(N8N_GENERATE_QUESTIONS_URL, payload, "generate_questions")
    if not success:
        logger.warning("n8n dispatch failed for generate_questions, falling back to local execution")
        from app.workers.resume_tasks import generate_questions_background
        generate_questions_background(
            app_record["id"],
            cand["full_name"],
            cand.get("skills") or [],
            cand.get("experience_years") or 0,
            cand.get("raw_text") or "",
            jwt_token,
        )


# ---------------------------------------------------------------------------
# Append jobs fallback (for adding more job openings to a requirement)
# ---------------------------------------------------------------------------

def append_jobs_background_fallback(req_id: str, count: int, additional_desc: str, jwt_token: str) -> None:
    """Local fallback: generate additional job drafts for an existing requirement."""
    logger.info(f"Generating {count} additional job drafts for requirement {req_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    try:
        req_res = db.table("requirements").select("*").eq("id", req_id).execute()
        if not req_res.data:
            return
        req = req_res.data[0]
        import uuid
        for i in range(count):
            db.table("job_openings").insert({
                "id": str(uuid.uuid4()),
                "requirement_id": req_id,
                "title": f"{req.get('title', 'Job')} — Option {i + 1}",
                "description": additional_desc or req.get("description", ""),
                "responsibilities": [],
                "qualifications": [],
                "keywords": req.get("skills") or [],
                "salary_range": f"{req.get('budget_min', 0)}–{req.get('budget_max', 0)} INR",
                "status": "draft",
                "processing_status": "ready",
            }).execute()
    except Exception as exc:
        logger.error(f"append_jobs_background_fallback failed for req {req_id}: {exc}")

def generate_job_openings_background(
    req_id: str, client_id: str, req_title: str, req_desc: str, req_skills: List[str], 
    req_exp_min: int, req_exp_max: int, req_seniority: str, req_budget_min: float, req_budget_max: float, 
    num_posts: int, jwt_token: str
) -> None:
    """Local fallback: fabricate job-opening drafts for a new Requirement."""
    logger.info(f"Starting background job generation for requirement {req_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    db.table("requirements").update({"status": "generating"}).eq("id", req_id).execute()
    for i in range(1, num_posts + 1):
        try:
            job_title = f"{req_title} (Option {i})"
            job_desc = f"We are seeking a talented {job_title} for our client. The ideal candidate will leverage modern patterns, lead key initiatives, and deliver high-impact features. This is a fast-paced environment requiring strong problem-solving skills."
            responsibilities = [
                "Lead development of core features and platform widgets.",
                "Collaborate with product and UX designers to craft high-fidelity interfaces.",
                "Ensure responsive designs and optimize rendering code for target metrics.",
                "Implement thorough unit testing across critical flows."
            ]
            qualifications = [
                f"At least {req_exp_min} years of professional engineering experience.",
                f"Strong competency in: {', '.join(req_skills[:4]) if req_skills else 'relevant tech'}.",
                "Excellent analytical thinking and clear articulation of design decisions."
            ]
            salary_range = f"₹{int(req_budget_min)} - ₹{int(req_budget_max)} LPA"
            db.table("job_openings").insert({
                "requirement_id": req_id, "post_index": i, "title": job_title, "description": job_desc,
                "responsibilities": responsibilities, "qualifications": qualifications, "keywords": req_skills,
                "salary_range": salary_range, "status": "draft", "processing_status": "ready"
            }).execute()
        except Exception as e:
            logger.error(f"Error generating job opening option {i}: {e}")
            db.table("requirements").update({"status": "ready"}).eq("id", req_id).execute()
            return
            
    db.table("requirements").update({"status": "ready"}).eq("id", req_id).execute()
    
    recruiter_id = None
    try:
        req_res = db.table("requirements").select("created_by, title").eq("id", req_id).execute()
        if req_res.data:
            recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve requirement details for notification in local generate: {e}")

    if recruiter_id:
        create_system_notification(
            db, recruiter_id, "Job Generation Completed",
            f"Successfully generated {num_posts} job openings (local fallback) for mandate '{req_title}'.",
            "job_generation", {"requirement_id": req_id, "requirement_title": req_title, "job_openings_count": num_posts}
        )
        log_activity_event(
            db, action="job_generation_completed", entity_type="requirements", entity_id=req_id,
            actor_name="System", actor_id=recruiter_id,
            metadata={"req_title": req_title, "job_openings_count": num_posts}
        )

def run_local_scan_publish(job_id: str, jwt_token: str):
    logger.info(f"Running local scan and publish for job {job_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        return
    job = job_res.data[0]
    
    keywords = job.get("keywords") or []
    default_skills = keywords[:5]
    while len(default_skills) < 5:
        default_skills.append(f"Required Skill {len(default_skills) + 1}")
        
    weights = [0.30, 0.25, 0.15, 0.15, 0.15]
    
    import time
    skills_list = []
    for idx, skill_name in enumerate(default_skills):
        skills_list.append({
            "id": f"sk-{idx + 1}-{int(time.time())}",
            "job_opening_id": job_id,
            "skill_name": skill_name,
            "weight": weights[idx],
            "skill_order": idx + 1,
            "approved": False
        })
        
    db.table("job_opening_skills").upsert({
        "job_opening_id": job_id,
        "skills": skills_list
    }, on_conflict="job_opening_id").execute()
        
    db.table("job_openings").update({"processing_status": "skill_approval"}).eq("id", job_id).execute()
    
    recruiter_id = None
    job_title = job.get("title", "Unknown Job")
    try:
        req_res = db.table("requirements").select("created_by").eq("id", job.get("requirement_id")).execute()
        if req_res.data:
            recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve recruiter_id in run_local_scan_publish: {e}")
        
    if recruiter_id:
        create_system_notification(
            db, recruiter_id, "Skills Extraction Completed",
            f"Mandate skills successfully extracted (local fallback) for job '{job_title}'. Core requirement weights are ready for review.",
            "job_generation", {"job_opening_id": job_id, "job_title": job_title}
        )
        log_activity_event(
            db, action="skills_extracted", entity_type="job_openings", entity_id=job_id,
            actor_name="System", actor_id=recruiter_id, metadata={"job_title": job_title}
        )

def regenerate_job_background_local(job_id: str, instruction: str, jwt_token: str):
    logger.info(f"Running local fallback regeneration for job {job_id}")
    db = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
    job_res = db.table("job_openings").select("*").eq("id", job_id).execute()
    if not job_res.data:
        return
    job = job_res.data[0]
    
    new_title = f"{job['title']} (Regenerated)" if "Regenerated" not in job.get('title', '') else job['title']
    new_desc = f"{job['description']}\n\n[Regenerated with instruction: \"{instruction}\"]"
    
    db.table("job_openings").update({
        "title": new_title, "description": new_desc, "processing_status": "ready"
    }).eq("id", job_id).execute()
    
    recruiter_id = None
    try:
        req_res = db.table("requirements").select("created_by").eq("id", job.get("requirement_id")).execute()
        if req_res.data:
            recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve recruiter_id in regenerate_job_background_local: {e}")
        
    if recruiter_id:
        create_system_notification(
            db, recruiter_id, "Job Regenerated Successfully",
            f"Job opening '{new_title}' has been successfully regenerated using instruction '{instruction}'.",
            "job_generation", {"job_opening_id": job_id, "job_title": new_title}
        )
        log_activity_event(
            db, action="job_regenerated", entity_type="job_openings", entity_id=job_id,
            actor_name="System", actor_id=recruiter_id, metadata={"job_title": new_title, "instruction": instruction}
        )
