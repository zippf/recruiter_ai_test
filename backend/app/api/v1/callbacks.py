from fastapi import APIRouter, Depends, HTTPException, Query
import time

from app.api.dependencies import verify_callback_secret, get_admin_supabase_client
from app.core.logging import logger
from app.schemas.common import (
    JobOpeningsCallback, JobSkillsCallback, JobRegenerateCallback, 
    CandidateMatchesCallback, ScreeningQuestionsCallback, QuestionRefineCallback
)
from app.services.notification_service import create_system_notification, log_activity_event
from app.core.config import MATCH_THRESHOLD

router = APIRouter()

@router.post("/api/v1/callbacks/job-openings", dependencies=[Depends(verify_callback_secret)])
async def callback_job_openings(payload: JobOpeningsCallback, append_mode: bool = Query(False), posts_to_add: int = Query(0)):
    logger.info(f"Received job openings callback for requirement {payload.requirement_id} (append_mode: {append_mode})")
    db = get_admin_supabase_client()
    
    # Check if requirement exists
    req_res = db.table("requirements").select("*").eq("id", payload.requirement_id).execute()
    if not req_res.data:
        raise HTTPException(status_code=404, detail="Requirement not found")
        
    if not append_mode:
        # Clear existing drafts for this requirement
        db.table("job_openings").delete().eq("requirement_id", payload.requirement_id).eq("status", "draft").execute()
        
    start_index = 0
    if append_mode:
        jobs_res = db.table("job_openings").select("id").eq("requirement_id", payload.requirement_id).eq("is_deleted", False).execute()
        start_index = len(jobs_res.data) if jobs_res.data else 0
    
    # Save job opening drafts
    for idx, jo in enumerate(payload.job_openings, 1):
        db.table("job_openings").insert({
            "requirement_id": payload.requirement_id,
            "post_index": start_index + idx,
            "title": jo.title,
            "description": jo.overview,
            "responsibilities": jo.responsibilities,
            "qualifications": jo.qualifications,
            "keywords": jo.keywords,
            "salary_range": jo.budget,
            "status": "draft",
            "processing_status": "ready",
            "category": jo.category,
            "sub_category": jo.sub_category
        }).execute()
        
    # Set requirement status to ready and increment count if in append_mode
    req_data = req_res.data[0]
    update_data = {"status": "ready"}
    if append_mode and posts_to_add > 0:
        new_total = (req_data.get("num_posts_requested") or 0) + posts_to_add
        update_data["num_posts_requested"] = new_total
        
    db.table("requirements").update(update_data).eq("id", payload.requirement_id).execute()
    
    # Send notification and log activity
    recruiter_id = req_data.get("created_by")
    req_title = req_data.get("title", "Unknown Requirement")
    
    action_verb = "appended" if append_mode else "generated"
    
    create_system_notification(
        db,
        recruiter_id,
        "Job Generation Completed",
        f"Successfully {action_verb} {len(payload.job_openings)} job openings for mandate '{req_title}'.",
        "job_generation",
        {"requirement_id": payload.requirement_id, "requirement_title": req_title, "job_openings_count": len(payload.job_openings)}
    )
    log_activity_event(
        db,
        action="job_generation_completed",
        entity_type="requirements",
        entity_id=payload.requirement_id,
        actor_name="System",
        actor_id=recruiter_id,
        metadata={"req_title": req_title, "job_openings_count": len(payload.job_openings)}
    )
    return {"status": "success"}


@router.post("/api/v1/callbacks/job-skills", dependencies=[Depends(verify_callback_secret)])
async def callback_job_skills(payload: JobSkillsCallback):
    logger.info(f"Received job skills callback for job {payload.job_opening_id}")
    db = get_admin_supabase_client()
    
    skills_list = []
    for idx, sk in enumerate(payload.skills, 1):
        skills_list.append({
            "id": f"sk-{idx}-{int(time.time())}",
            "job_opening_id": payload.job_opening_id,
            "skill_name": sk.name,
            "weight": sk.weight,
            "skill_order": idx,
            "approved": False
        })
        
    db.table("job_opening_skills").upsert({
        "job_opening_id": payload.job_opening_id,
        "skills": skills_list
    }, on_conflict="job_opening_id").execute()
        
    # Set job processing_status to ready
    db.table("job_openings").update({"processing_status": "ready"}).eq("id", payload.job_opening_id).execute()
    
    # Resolve recruiter_id and send notification/log
    recruiter_id = None
    job_title = "Unknown Job"
    try:
        job_res = db.table("job_openings").select("title, requirement_id").eq("id", payload.job_opening_id).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "")
            req_res = db.table("requirements").select("created_by").eq("id", job_res.data[0].get("requirement_id")).execute()
            if req_res.data:
                recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve recruiter_id in callback_job_skills: {e}")
        
    if recruiter_id:
        create_system_notification(
            db,
            recruiter_id,
            "Skills Extraction Completed",
            f"Mandate skills successfully extracted for job '{job_title}'. Core requirement weights are ready for review.",
            "job_generation",
            {"job_opening_id": payload.job_opening_id, "job_title": job_title}
        )
        log_activity_event(
            db,
            action="skills_extracted",
            entity_type="job_openings",
            entity_id=payload.job_opening_id,
            actor_name="System",
            actor_id=recruiter_id,
            metadata={"job_title": job_title}
        )
        
    return {"status": "success"}



@router.post("/api/v1/callbacks/job-openings/regenerate", dependencies=[Depends(verify_callback_secret)])
async def callback_regenerate_job(payload: JobRegenerateCallback):
    logger.info(f"Received job openings callback for requirement {payload.job_opening_id}")
    db = get_admin_supabase_client()
    
    job_res = db.table("job_openings").select("*").eq("id", payload.job_opening_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Job opening not found")
        
    db.table("job_openings").update({
        "title": payload.title,
        "description": payload.overview,
        "responsibilities": payload.responsibilities,
        "qualifications": payload.qualifications,
        "salary_range": payload.budget,
        "keywords": payload.keywords,
        "processing_status": "ready",
        "category": payload.category,
        "sub_category": payload.sub_category
    }).eq("id", payload.job_opening_id).execute()
    
    job_data = job_res.data[0]
    req_res = db.table("requirements").select("created_by").eq("id", job_data.get("requirement_id")).execute()
    recruiter_id = req_res.data[0].get("created_by") if req_res.data else None
    
    if recruiter_id:
        create_system_notification(
            db,
            recruiter_id,
            "Job Regenerated Successfully",
            f"Job opening '{payload.title}' has been successfully regenerated by n8n workflow.",
            "job_generation",
            {"job_opening_id": payload.job_opening_id, "job_title": payload.title}
        )
        log_activity_event(
            db,
            action="job_regenerated",
            entity_type="job_openings",
            entity_id=payload.job_opening_id,
            actor_name="System",
            actor_id=recruiter_id,
            metadata={"job_title": payload.title}
        )
    return {"status": "success"}


@router.post("/api/v1/callbacks/candidate-matches", dependencies=[Depends(verify_callback_secret)])
async def callback_candidate_matches(payload: CandidateMatchesCallback):
    logger.info(f"Received candidate matches callback for job {payload.job_opening_id}")
    db = get_admin_supabase_client()
    
    # Clear existing job candidates
    db.table("job_candidates").delete().eq("job_opening_id", payload.job_opening_id).execute()
    
    # Fetch candidates' parsed_resume_json and filter by job_id or linked applications
    cand_ids = [match.candidate_id for match in payload.matches]
    valid_cand_ids = set()
    cand_resumes = {}
    if cand_ids:
        # Get candidate IDs that are already linked to this job via applications
        linked_apps_res = db.table("applications").select("candidate_id").eq("job_opening_id", payload.job_opening_id).execute()
        linked_cand_ids = set(a["candidate_id"] for a in linked_apps_res.data or [])
        
        cands_res = db.table("candidates").select("id, job_id, parsed_resume_json").in_("id", cand_ids).eq("is_deleted", False).execute()
        if cands_res.data:
            for c in cands_res.data:
                if c.get("job_id") == payload.job_opening_id or c["id"] in linked_cand_ids:
                    valid_cand_ids.add(c["id"])
                    cand_resumes[c["id"]] = c.get("parsed_resume_json")
            
    seen_candidate_ids = set()
    scored_candidates = []
    for idx, match in enumerate(payload.matches):
        if match.candidate_id not in valid_cand_ids:
            continue
        if match.candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(match.candidate_id)
        
        # Query existing application
        app_res = (
            db.table("applications")
              .select("id")
              .eq("candidate_id", match.candidate_id)
              .eq("job_opening_id", payload.job_opening_id)
              .limit(1)
              .execute()
        )
        
        if app_res.data and match.fuzzy_score >= MATCH_THRESHOLD:
            scored_candidates.append({
                "job_opening_id": payload.job_opening_id,
                "candidate_id": match.candidate_id,
                "application_id": app_res.data[0]["id"],
                "fuzzy_score": match.fuzzy_score,
                "rank_order": 1, # updated later
                "strengths": match.strengths[:3],
                "skill_gaps": match.skill_gaps[:3],
                "parsed_resume": cand_resumes.get(match.candidate_id)
            })
            
    # Sort and rank
    scored_candidates.sort(key=lambda x: x["fuzzy_score"], reverse=True)
    for rank, item in enumerate(scored_candidates, 1):
        item["rank_order"] = rank
        db.table("job_candidates").insert(item).execute()
        
    # Set job status/processing_status
    db.table("job_openings").update({"processing_status": "ready"}).eq("id", payload.job_opening_id).execute()
    
    # Send notification and log activity
    recruiter_id = None
    job_title = "Unknown Job"
    try:
        job_res = db.table("job_openings").select("title, requirement_id").eq("id", payload.job_opening_id).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "")
            req_id = job_res.data[0].get("requirement_id")
            req_res = db.table("requirements").select("created_by").eq("id", req_id).execute()
            if req_res.data:
                recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve recruiter_id/job_title in callback_candidate_matches: {e}")
        
    if recruiter_id:
        create_system_notification(
            db,
            recruiter_id,
            "Candidate Matching Completed",
            f"Candidate matching completed for job '{job_title}'. Found {len(payload.matches)} matches.",
            "candidate_matching",
            {"job_opening_id": payload.job_opening_id, "job_title": job_title, "matches_count": len(payload.matches)}
        )
        log_activity_event(
            db,
            action="candidate_matching_completed",
            entity_type="job_openings",
            entity_id=payload.job_opening_id,
            actor_name="System",
            actor_id=recruiter_id,
            metadata={"job_title": job_title, "matches_count": len(payload.matches)}
        )
    return {"status": "success"}


@router.post("/api/v1/callbacks/screening-questions", dependencies=[Depends(verify_callback_secret)])
async def callback_screening_questions(payload: ScreeningQuestionsCallback):
    logger.info(f"Received screening questions callback for application {payload.application_id}")
    db = get_admin_supabase_client()
    
    # Verify application exists
    app_res = db.table("applications").select("id, job_opening_id, candidate_id").eq("id", payload.application_id).execute()
    if not app_res.data:
        raise HTTPException(status_code=404, detail="Application not found")
        
    app_data = app_res.data[0]
    recruiter_id = None
    job_title = "Unknown Job"
    candidate_name = "Unknown Candidate"
    
    try:
        cand_res = db.table("candidates").select("full_name").eq("id", app_data["candidate_id"]).execute()
        if cand_res.data:
            candidate_name = cand_res.data[0].get("full_name") or "Unknown Candidate"
            
        job_res = db.table("job_openings").select("title, requirement_id").eq("id", app_data["job_opening_id"]).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "")
            req_res = db.table("requirements").select("created_by").eq("id", job_res.data[0].get("requirement_id")).execute()
            if req_res.data:
                recruiter_id = req_res.data[0].get("created_by")
    except Exception as e:
        logger.error(f"Failed to resolve details in callback_screening_questions: {e}")
        
    import uuid
    questions_list = []
    for idx, q in enumerate(payload.questions, 1):
        questions_list.append({
            "id": str(uuid.uuid4()),
            "question": q.question,
            "difficulty": q.difficulty,
            "question_order": q.order if q.order is not None else idx,
            "reason": q.reason,
            "ai_generated": True,
            "modified": False
        })
        
    db.table("applications").update({
        "screening_questions": questions_list
    }).eq("id", payload.application_id).execute()
    
    if recruiter_id:
        create_system_notification(
            db,
            recruiter_id,
            "Screening Questions Generated",
            f"Screening questions generated for candidate '{candidate_name}' applying for '{job_title}'.",
            "screening_questions",
            {"application_id": payload.application_id, "candidate_name": candidate_name, "job_title": job_title}
        )
        log_activity_event(
            db,
            action="screening_questions_generated",
            entity_type="applications",
            entity_id=payload.application_id,
            actor_name="System",
            actor_id=recruiter_id,
            metadata={"candidate_name": candidate_name, "job_title": job_title}
        )
    return {"status": "success"}


@router.post("/api/v1/callbacks/questions/refine", dependencies=[Depends(verify_callback_secret)])
async def callback_refine_question(payload: QuestionRefineCallback):
    logger.info(f"Received question refinement callback for application {payload.application_id}, question {payload.question_id}")
    db = get_admin_supabase_client()
    
    # Fetch application and screening_questions
    app_res = db.table("applications").select("id, screening_questions, candidate_id, reviewed_by").eq("id", payload.application_id).execute()
    if not app_res.data:
        raise HTTPException(status_code=404, detail="Application not found")
        
    app_record = app_res.data[0]
    questions = app_record.get("screening_questions") or []
    
    found = False
    for q in questions:
        if q.get("id") == payload.question_id:
            q["question"] = payload.refined_question
            if payload.difficulty:
                q["difficulty"] = payload.difficulty
            if payload.reason:
                q["reason"] = payload.reason
            q["modified"] = True
            q["refining"] = False
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Question not found in application")
        
    db.table("applications").update({
        "screening_questions": questions
    }).eq("id", payload.application_id).execute()
    
    # Resolve candidate details for activity log and notification
    cand_name = "Candidate"
    recruiter_id = app_record.get("reviewed_by")
    try:
        cand_res = db.table("candidates").select("full_name").eq("id", app_record["candidate_id"]).execute()
        if cand_res.data:
            cand_name = cand_res.data[0].get("full_name") or "Candidate"
    except Exception as e:
        logger.error(f"Failed to fetch candidate details in callback_refine_question: {e}")
        
    if recruiter_id:
        create_system_notification(
            db,
            recruiter_id,
            "Question Refined Successfully",
            f"Screening question for candidate '{cand_name}' has been successfully refined by AI.",
            "job_generation",
            {"application_id": payload.application_id, "question_id": payload.question_id}
        )
        log_activity_event(
            db,
            action="screening_question_refined",
            entity_type="applications",
            entity_id=payload.application_id,
            actor_name="System",
            actor_id=recruiter_id,
            metadata={"candidate_name": cand_name, "question_id": payload.question_id}
        )
        
    return {"status": "success"}


