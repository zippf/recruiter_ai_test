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


@router.get("/api/v1/members")
async def get_organization_members(
    org_id: Optional[str] = Depends(get_user_org_id)
):
    if not org_id:
        return []
    db = get_admin_supabase_client()
    res = db.table("members").select("*, member_roles(*, roles(id, name)), roles(id, name)").eq("organization_id", org_id).execute()
    data = res.data or []
    formatted = []
    for m in data:
        assigned_role = None
        mr_list = m.get("member_roles") or []
        if mr_list and isinstance(mr_list, list) and len(mr_list) > 0 and isinstance(mr_list[0], dict) and mr_list[0].get("roles"):
            assigned_role = mr_list[0].get("roles")
        elif m.get("roles"):
            assigned_role = m.get("roles")
            
        formatted.append({
            **m,
            "role_name": assigned_role.get("name") if isinstance(assigned_role, dict) and assigned_role.get("name") else ("Primary Admin" if m.get("is_primary_admin") else "Member"),
            "role": assigned_role
        })
    return formatted

