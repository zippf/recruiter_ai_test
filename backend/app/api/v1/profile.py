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


@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Client = Depends(get_supabase),
    user_id: Optional[str] = Depends(get_current_user_id),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Use JPEG, PNG, WebP, or GIF.")

    # Read file bytes
    file_bytes = await file.read()

    # Validate file size (max 5MB)
    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 5 MB.")

    file_ext = (file.filename or "avatar.jpg").split(".")[-1].lower()
    if file_ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
        file_ext = "jpg"

    file_path = f"{user_id}/avatar.{file_ext}"

    try:
        # Upload to Supabase Storage
        db.storage.from_("avatars").upload(
            file_path,
            file_bytes,
            file_options={"content-type": file.content_type, "upsert": "true"},
        )

        # Get public URL
        url_data = db.storage.from_("avatars").get_public_url(file_path)
        public_url = f"{url_data}?t={int(time.time())}"

        # Save avatar_url to profiles table
        db.table("profiles").update({"avatar_url": public_url}).eq("id", user_id).execute()

        return {"url": public_url}

    except Exception as e:
        logger.error(f"Avatar upload failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

