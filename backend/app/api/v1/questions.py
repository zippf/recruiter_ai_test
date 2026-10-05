from fastapi import APIRouter, Depends, HTTPException, Header, Request, Body, BackgroundTasks, Query, UploadFile, File
from typing import *
from supabase import Client
import json
import time
from datetime import datetime, timezone, timedelta

from app.api.dependencies import get_supabase, get_current_user_id, get_admin_supabase_client, get_user_org_id, get_safe_supabase_client
from app.core.logging import logger
from app.schemas.common import *
from app.security.tenant_access import get_recruiter_owner_ids
from app.security.authorization import deobfuscate_id
from app.services.notification_service import create_system_notification, log_activity_event
from app.services.query_service import in_memory_queries

router = APIRouter()


@router.delete("/api/v1/questions/{q_id}")
async def delete_question(q_id: str, request: Request, db: Client = Depends(get_supabase)):
    # Find the application row containing this question ID in its screening_questions JSONB array
    res = db.table("applications").select("*").filter("screening_questions", "cs", f'[{{"id": "{q_id}"}}]').execute()
    if not res.data:
        res = db.table("applications").select("*").execute()
        
    target_app = None
    target_question = None
    for row in res.data:
        qs = row.get("screening_questions") or []
        for q in qs:
            if q.get("id") == q_id:
                target_app = row
                target_question = q
                break
        if target_app:
            break
            
    if not target_app or not target_question:
        raise HTTPException(status_code=404, detail="Question not found")
        
    # Remove the question from the array
    updated_questions = [q for q in target_app["screening_questions"] if q.get("id") != q_id]
    
    db.table("applications").update({
        "screening_questions": updated_questions
    }).eq("id", target_app["id"]).execute()
    
    # Log activity
    auth_header = request.headers.get("Authorization", "")
    user_id = get_current_user_id(auth_header)
    
    cand_name = "Candidate"
    try:
        cand_res = db.table("candidates").select("full_name").eq("id", target_app.get("candidate_id")).execute()
        if cand_res.data:
            cand_name = cand_res.data[0].get("full_name") or "Candidate"
    except Exception as e:
        logger.error(f"Failed to fetch candidate details in delete_question: {e}")
        
    log_activity_event(
        db,
        action="screening_question_deleted",
        entity_type="applications",
        entity_id=target_app["id"],
        actor_name="Recruiter",
        actor_id=user_id,
        metadata={"candidate_name": cand_name, "question": target_question["question"][:60] + "..." if len(target_question["question"]) > 60 else target_question["question"]}
    )
    
    return {"status": "success", "message": "Question deleted successfully"}

