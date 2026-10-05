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


@router.get("/api/v1/queries")
async def get_all_candidate_queries(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    admin_db = get_admin_supabase_client()
    try:
        # 1. Fetch requirements created by this recruiter
        user_req_ids = set()
        try:
            reqs_user_res = admin_db.table("requirements").select("id").eq("created_by", user_id).eq("is_deleted", False).execute()
            if reqs_user_res.data:
                user_req_ids = {r["id"] for r in reqs_user_res.data}
        except Exception as err:
            logger.warning(f"Error fetching recruiter requirements: {err}")

        # If user_req_ids is empty, try user-authenticated db query for RLS scoping
        if not user_req_ids:
            try:
                user_db_reqs = db.table("requirements").select("id").eq("is_deleted", False).execute()
                if user_db_reqs.data:
                    user_req_ids = {r["id"] for r in user_db_reqs.data}
            except Exception as uerr:
                logger.warning(f"Error fetching RLS requirements: {uerr}")

        # 2. Fetch job openings linked to these requirements
        user_job_ids = set()
        jobs_map = {}
        try:
            jobs_res = admin_db.table("job_openings").select("id, title, requirement_id").eq("is_deleted", False).execute()
            filtered_jobs = [j for j in (jobs_res.data or []) if not user_req_ids or j.get("requirement_id") in user_req_ids]
            user_job_ids = {j["id"] for j in filtered_jobs}
            
            req_ids = {j["requirement_id"] for j in filtered_jobs if j.get("requirement_id")}
            reqs_map = {}
            if req_ids:
                reqs_res = admin_db.table("requirements").select("id, title, client_id").in_("id", list(req_ids)).execute()
                client_ids = {r["client_id"] for r in (reqs_res.data or []) if r.get("client_id")}
                
                clients_map = {}
                if client_ids:
                    clients_res = admin_db.table("clients").select("id, name").in_("id", list(client_ids)).execute()
                    clients_map = {c["id"]: c["name"] for c in (clients_res.data or [])}
                    
                for r in (reqs_res.data or []):
                    reqs_map[r["id"]] = {
                        "id": r["id"],
                        "title": r.get("title"),
                        "clients": {"name": clients_map.get(r.get("client_id"), "Generic Client")}
                    }
                    
            for j in filtered_jobs:
                jobs_map[j["id"]] = {
                    "id": j["id"],
                    "title": j.get("title"),
                    "requirements": reqs_map.get(j.get("requirement_id"), {})
                }
        except Exception as enrich_err:
            logger.warning(f"Error enriching query job/client metadata: {enrich_err}")

        # 3. Fetch candidate queries for user's job openings
        if user_job_ids:
            q_res = admin_db.table("candidate_queries").select("*").in_("job_id", list(user_job_ids)).order("created_at", desc=True).execute()
            db_queries = q_res.data or []
        else:
            db_queries = []

        # 4. Enrich queries with nested job structure
        formatted_db = []
        for q in db_queries:
            if q.get("sender") == "recruiter":
                continue
            j_id = q.get("job_id")
            job_obj = jobs_map.get(j_id, {"id": j_id, "title": "Job Opening", "requirements": {"clients": {"name": "Generic Client"}}})
            q_copy = dict(q)
            q_copy["job_openings"] = job_obj
            formatted_db.append(q_copy)
            
        # 5. Merge with in-memory backups for user's jobs
        all_mem = []
        for j_id, q_list in in_memory_queries.items():
            if not user_job_ids or j_id in user_job_ids:
                job_obj = jobs_map.get(j_id, {"id": j_id, "title": "Job Opening", "requirements": {"clients": {"name": "Generic Client"}}})
                for qm in q_list:
                    if qm.get("sender") != "recruiter":
                        qm_copy = dict(qm)
                        qm_copy["job_openings"] = job_obj
                        all_mem.append(qm_copy)
            
        all_queries = {q["id"]: q for q in (formatted_db + all_mem)}
        return sorted(all_queries.values(), key=lambda x: x["created_at"], reverse=True)
    except Exception as e:
        logger.error(f"Error in get_all_candidate_queries: {e}")
        all_mem = []
        for j_id, q_list in in_memory_queries.items():
            all_mem.extend(q_list)
        return sorted(all_mem, key=lambda x: x.get("created_at", ""), reverse=True)

@router.post("/api/v1/queries/{query_id}/resolve")
async def resolve_candidate_query(query_id: str, payload: ResolveQueryModel, db: Client = Depends(get_supabase)):
    # Dual-mode update
    updated_query = None
    try:
        res = db.table("candidate_queries").update({"is_resolved": payload.is_resolved}).eq("id", query_id).execute()
        if res.data:
            updated_query = res.data[0]
    except Exception as e:
        logger.warning(f"Failed to update candidate query in Supabase: {e}. Updating in-memory.")
        
    # Check/update in-memory backup as well to maintain consistency
    for job_id, queries in in_memory_queries.items():
        for q in queries:
            if q["id"] == query_id:
                q["is_resolved"] = payload.is_resolved
                updated_query = q
                break
                
    if not updated_query:
        raise HTTPException(status_code=404, detail="Query not found")
        
    return updated_query

