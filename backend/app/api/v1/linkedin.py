from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from supabase import Client

from app.api.dependencies import get_current_user_id
from app.core.config import FRONTEND_BASE_URL, BACKEND_BASE_URL, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI
from app.core.logging import logger
from app.integrations.supabase_client import get_admin_supabase_client, get_supabase, get_safe_supabase_client
from app.schemas.linkedin import CompanyPageModel, SharePostModel
from app.services.activity_service import log_activity_event
from app.services.notification_service import create_system_notification

router = APIRouter()

@router.get("/authorize")
async def linkedin_authorize(user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not LINKEDIN_CLIENT_ID or "your_linkedin" in LINKEDIN_CLIENT_ID.lower() or LINKEDIN_CLIENT_ID == "null":
        mock_auth_url = f"{BACKEND_BASE_URL}/api/v1/auth/linkedin/callback?code=mock_oauth_code&state={user_id}"
        return {"url": mock_auth_url}
        
    scopes = "openid profile w_member_social"
    import urllib.parse
    encoded_redirect = urllib.parse.quote(LINKEDIN_REDIRECT_URI)
    encoded_scopes = urllib.parse.quote(scopes)
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={encoded_redirect}"
        f"&state={user_id}"
        f"&scope={encoded_scopes}"
    )
    return {"url": auth_url}

@router.get("/callback")
async def linkedin_callback(code: str, state: str):
    user_id = state
    
    is_mock = (
        code == "mock_oauth_code" or 
        not LINKEDIN_CLIENT_ID or 
        "your_linkedin" in LINKEDIN_CLIENT_ID.lower() or 
        not LINKEDIN_CLIENT_SECRET or 
        "your_linkedin" in LINKEDIN_CLIENT_SECRET.lower()
    )
    
    frontend_redirect_success = f"{FRONTEND_BASE_URL}/profile?tab=integrations&status=success"
    
    try:
        db_admin = get_admin_supabase_client()
        
        if is_mock:
            from datetime import datetime, timedelta
            expires_at = datetime.utcnow() + timedelta(days=60)
            
            rpc_payload = {
                "p_user_id": user_id,
                "p_linkedin_member_id": "mock_member_12345",
                "p_linkedin_access_token": "mock_access_token_abcde12345",
                "p_linkedin_refresh_token": "mock_refresh_token_xyz987",
                "p_expires_at": expires_at.isoformat()
            }
            db_admin.rpc("upsert_linkedin_account", rpc_payload).execute()
            return RedirectResponse(url=frontend_redirect_success)
            
        async with httpx.AsyncClient() as client:
            token_url = "https://www.linkedin.com/oauth/v2/accessToken"
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": LINKEDIN_REDIRECT_URI,
                "client_id": LINKEDIN_CLIENT_ID,
                "client_secret": LINKEDIN_CLIENT_SECRET
            }
            token_res = await client.post(token_url, data=data)
            if token_res.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Token exchange failed: {token_res.text}")
                
            token_data = token_res.json()
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 5184000)
            
            from datetime import datetime, timedelta
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            userinfo_url = "https://api.linkedin.com/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            user_res = await client.get(userinfo_url, headers=headers)
            
            member_id = "unknown_member"
            if user_res.status_code == 200:
                user_data = user_res.json()
                member_id = user_data.get("sub") or user_data.get("id") or "unknown_member"
            else:
                me_url = "https://api.linkedin.com/v2/me"
                me_res = await client.get(me_url, headers=headers)
                if me_res.status_code == 200:
                    member_id = me_res.json().get("id") or "unknown_member"
            
            rpc_payload = {
                "p_user_id": user_id,
                "p_linkedin_member_id": member_id,
                "p_linkedin_access_token": access_token,
                "p_linkedin_refresh_token": refresh_token,
                "p_expires_at": expires_at.isoformat()
            }
            db_admin.rpc("upsert_linkedin_account", rpc_payload).execute()
            
            return RedirectResponse(url=frontend_redirect_success)
            
    except Exception as e:
        logger.error(f"Error handling LinkedIn callback: {e}")
        import urllib.parse
        err_msg = urllib.parse.quote(str(e))
        return RedirectResponse(
            url=f"{FRONTEND_BASE_URL}/profile?tab=integrations&status=error&message={err_msg}"
        )

@router.get("/status")
async def get_linkedin_status(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    try:
        res = db.table("linkedin_accounts").select("*").eq("user_id", user_id).execute()
        if res.data:
            account = res.data[0]
            return {
                "connected": True,
                "linkedin_member_id": account.get("linkedin_member_id"),
                "company_page_id": account.get("company_page_id"),
                "expires_at": account.get("expires_at")
            }
    except Exception as e:
        logger.error(f"Error checking LinkedIn status: {e}")
        
    return {"connected": False}

@router.post("/company-page")
async def save_linkedin_company_page(payload: CompanyPageModel, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    try:
        db.table("linkedin_accounts").update({"company_page_id": payload.company_page_id}).eq("user_id", user_id).execute()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error saving LinkedIn company page: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save page ID: {str(e)}")

@router.post("/disconnect")
async def disconnect_linkedin(db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    try:
        db.table("linkedin_accounts").delete().eq("user_id", user_id).execute()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error disconnecting LinkedIn: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to disconnect LinkedIn account: {str(e)}")

@router.post("/jobs/{job_id}/share-linkedin")
async def share_job_linkedin(job_id: str, payload: SharePostModel, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    connection_res = db.table("linkedin_accounts").select("*").eq("user_id", user_id).execute()
    if not connection_res.data:
        raise HTTPException(status_code=400, detail="LinkedIn account is not connected. Please connect it under Settings.")
        
    account = connection_res.data[0]
    company_page_id = account.get("company_page_id")
    access_token = account.get("linkedin_access_token")
    
    job_title = "Job Opening"
    try:
        job_res = db.table("job_openings").select("title").eq("id", job_id).execute()
        if job_res.data:
            job_title = job_res.data[0].get("title", "Job Opening")
    except Exception:
        pass
        
    is_mock = access_token.startswith("mock_")
    
    try:
        if is_mock:
            import asyncio
            await asyncio.sleep(1)
            target_desc = f"LinkedIn Company Page '{company_page_id}'" if company_page_id else "your LinkedIn Personal Feed"
            
            create_system_notification(
                db,
                user_id,
                "Job Shared on LinkedIn (Simulated)",
                f"Job opening '{job_title}' was successfully shared to {target_desc} (Simulated).",
                "job_generation",
                {"job_id": job_id}
            )
            log_activity_event(
                db,
                action="job_shared_linkedin",
                entity_type="jobs",
                entity_id=job_id,
                actor_name="Recruiter",
                actor_id=user_id,
                metadata={
                    "job_title": job_title, 
                    "company_page_id": company_page_id,
                    "shared_to": "company" if company_page_id else "personal",
                    "simulated": True
                }
            )
            return {"status": "success", "message": "Successfully shared (simulated)", "post_url": "https://linkedin.com/mock-post"}
        else:
            # Here real LinkedIn API would be called. For this migration we mock it or fail safely
            raise HTTPException(status_code=501, detail="Real LinkedIn sharing not fully implemented in migration mock")
    except Exception as e:
        logger.error(f"Error sharing to LinkedIn: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to share job on LinkedIn: {str(e)}")
