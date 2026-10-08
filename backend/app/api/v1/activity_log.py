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


@router.delete("/api/v1/activity_log")
async def delete_all_activity_logs(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.table("activity_log").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    return {"status": "success"}

@router.post("/api/v1/activity_log/prune")
async def prune_activity_logs_endpoint(
    payload: PruneLogsRequestModel,
    db: Client = Depends(get_supabase)
):
    admin_db = get_admin_supabase_client()
    
    # Compute cutoff timestamp
    if payload.before_date:
        cutoff_iso = payload.before_date
    elif payload.days_older_than is not None:
        if payload.days_older_than <= 0:
            cutoff_iso = datetime.now(timezone.utc).isoformat()
        else:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=payload.days_older_than)
            cutoff_iso = cutoff_time.isoformat()
    else:
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_iso = cutoff_time.isoformat()

    target_org_id = payload.organization_id if payload.organization_id and payload.organization_id != "all" else None

    deleted_count = 0
    try:
        # Execute RPC stored procedure prune_activity_logs
        rpc_res = admin_db.rpc("prune_activity_logs", {
            "p_before_timestamp": cutoff_iso,
            "p_organization_id": target_org_id
        }).execute()
        if rpc_res.data is not None:
            deleted_count = rpc_res.data
    except Exception as rpc_err:
        logger.warning(f"prune_activity_logs RPC failed, falling back to direct table delete: {rpc_err}")
        try:
            query = admin_db.table("activity_log").delete().lt("created_at", cutoff_iso)
            if target_org_id:
                query = query.eq("organization_id", target_org_id)
            res = query.execute()
            deleted_count = len(res.data) if res.data else 0
        except Exception as del_err:
            logger.error(f"Fallback delete failed: {del_err}")
            raise HTTPException(status_code=500, detail=f"Failed to prune logs: {del_err}")

    # Log audit entry for log pruning operation itself
    try:
        log_activity_event(
            db=admin_db,
            action="prune_activity_logs",
            entity_type="system",
            entity_id=target_org_id or "global",
            actor_name="Dev/Admin",
            actor_id="00000000-0000-0000-0000-000000000000",
            organization_id=target_org_id,
            metadata={
                "deleted_count": deleted_count,
                "cutoff_timestamp": cutoff_iso,
                "days_older_than": payload.days_older_than,
                "target_organization": target_org_id or "all"
            }
        )
    except Exception:
        pass

    return {
        "status": "success",
        "deleted_count": deleted_count,
        "cutoff_timestamp": cutoff_iso,
        "organization_id": target_org_id or "all"
    }

@router.delete("/api/v1/activity_log/{id}")
async def delete_activity_log(id: str, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    res = db.table("activity_log").delete().eq("id", id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Activity log not found")
    return {"status": "success"}

@router.post("/api/v1/auth/log-event")
async def log_auth_event(
    payload: AuthLogEventModel,
    db: Client = Depends(get_supabase),
    current_user_id: Optional[str] = Depends(get_current_user_id),
    user_org_id: Optional[str] = Depends(get_user_org_id)
):
    admin_db = get_admin_supabase_client()
    actor_id = payload.actor_id or current_user_id or "00000000-0000-0000-0000-000000000000"
    actor_name = payload.actor_name or payload.email or "User"
    org_id = payload.organization_id or user_org_id

    meta = payload.metadata or {}
    if payload.email:
        meta["email"] = payload.email

    log_activity_event(
        db=admin_db,
        action=payload.action,
        entity_type="user",
        entity_id=actor_id,
        actor_name=actor_name,
        actor_id=actor_id,
        organization_id=org_id,
        metadata=meta
    )
    return {"status": "success"}

