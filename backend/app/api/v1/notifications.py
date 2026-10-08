from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from supabase import Client
from app.api.dependencies import get_supabase, get_current_user_id

router = APIRouter()

@router.get("/api/v1/notifications")
async def get_notifications(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    res = db.table("notifications").select("*").eq("recruiter_id", user_id).order("created_at", desc=True).execute()
    return res.data



@router.post("/api/v1/notifications/{id}/read")
async def mark_notification_read(id: str, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    res = db.table("notifications").update({"is_read": True}).eq("id", id).eq("recruiter_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "success"}



@router.post("/api/v1/notifications/read-all")
async def mark_all_notifications_read(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.table("notifications").update({"is_read": True}).eq("recruiter_id", user_id).execute()
    return {"status": "success"}



@router.delete("/api/v1/notifications/{id}")
async def delete_notification(id: str, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    res = db.table("notifications").delete().eq("id", id).eq("recruiter_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "success"}



@router.delete("/api/v1/notifications")
async def delete_all_notifications(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.table("notifications").delete().eq("recruiter_id", user_id).execute()
    return {"status": "success"}


