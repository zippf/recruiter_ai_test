from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from supabase import Client

from app.core.logging import logger
from app.api.dependencies import get_supabase, get_current_user_id, get_user_org_id, get_admin_supabase_client
from app.schemas.common import ClientModel
from app.security.tenant_access import get_recruiter_owner_ids
from postgrest.exceptions import APIError

router = APIRouter()

@router.get("/api/v1/clients")
async def get_clients(
    db: Client = Depends(get_supabase), 
    authorization: Optional[str] = Header(None),
    x_user_email: Optional[str] = Header(None, alias="x-user-email")
):
    admin_db = get_admin_supabase_client()
    recruiter_owner_ids, user_org_id = get_recruiter_owner_ids(authorization, x_user_email)
    
    client_ids = set()
    if recruiter_owner_ids or user_org_id:
        from app.security.authentication import filter_valid_uuids
        valid_uuids = filter_valid_uuids(recruiter_owner_ids)
        all_reqs = admin_db.table("requirements").select("client_id, organization_id, created_by").eq("is_deleted", False).execute().data or []
        
        for r in all_reqs:
            if user_org_id and r.get("organization_id") == user_org_id:
                if r.get("client_id"): client_ids.add(r["client_id"])
            elif r.get("created_by") and (r.get("created_by") in recruiter_owner_ids or r.get("created_by") in valid_uuids):
                if r.get("client_id"): client_ids.add(r["client_id"])
            elif not r.get("organization_id") and not r.get("created_by"):
                if r.get("client_id"): client_ids.add(r["client_id"])

    all_clients = db.table("clients").select("*").eq("is_deleted", False).order("created_at", desc=True).execute().data or []
    
    if not (recruiter_owner_ids or user_org_id):
        return all_clients
        
    user_clients = []
    for c in all_clients:
        if c.get("id") in client_ids:
            user_clients.append(c)
        elif user_org_id and c.get("organization_id") == user_org_id:
            user_clients.append(c)
        elif c.get("created_by") in recruiter_owner_ids:
            user_clients.append(c)
            
    return user_clients


@router.post("/api/v1/clients")
async def create_client_endpoint(client: ClientModel, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id), org_id: Optional[str] = Depends(get_user_org_id)):
    payload = {"name": client.name}
    if user_id:
        payload["created_by"] = user_id
    try:
        res = db.table("clients").insert(payload).execute()
    except Exception as e:
        logger.error(f"Error creating client: {e}")
        err_msg = str(e)
        if "23505" in err_msg:
            raise HTTPException(status_code=409, detail="A client with this name already exists for your account.")
        if "column" in err_msg and "does not exist" in err_msg:
            raise HTTPException(
                status_code=500, 
                detail="Database audit trigger error: Please run the updated Supabase SQL migration script to add missing audit columns."
            )
        raise HTTPException(status_code=500, detail=err_msg)

    if not res.data:
        raise HTTPException(status_code=400, detail="Failed to create client")
    
    # Log activity
    from app.services.notification_service import log_activity_event
    log_activity_event(
        db=db,
        action="client_created",
        entity_type="clients",
        entity_id=res.data[0]["id"],
        actor_name="Recruiter",
        metadata={"client_name": client.name}
    )
    
    return res.data[0]


@router.put("/api/v1/clients/{client_id}")
async def update_client(client_id: str, client: ClientModel, db: Client = Depends(get_supabase)):
    try:
        res = db.table("clients").update({"name": client.name}).eq("id", client_id).execute()
    except APIError as e:
        logger.error(f"Error updating client {client_id}: {e}")
        if e.code == "23505":
            raise HTTPException(status_code=409, detail="A client with this name already exists for your account.")
        raise HTTPException(status_code=500, detail=str(e))

    if not res.data:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Log activity
    from app.services.notification_service import log_activity_event
    log_activity_event(
        db=db,
        action="client_updated",
        entity_type="clients",
        entity_id=client_id,
        actor_name="Recruiter",
        metadata={"client_name": client.name}
    )
    
    return res.data[0]


@router.delete("/api/v1/clients/{client_id}")
async def delete_client(client_id: str, db: Client = Depends(get_supabase)):
    res = db.table("clients").update({"is_deleted": True}).eq("id", client_id).execute()
    return {"success": True}
