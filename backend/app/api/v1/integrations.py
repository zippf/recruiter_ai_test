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


@router.get("/api/v1/integrations/linkedin/authorize")
async def linkedin_authorize(user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # If client ID is not configured, generate a mock redirect callback to help testing locally
    if not LINKEDIN_CLIENT_ID or "your_linkedin" in LINKEDIN_CLIENT_ID.lower() or LINKEDIN_CLIENT_ID == "null":
        # Simulate local flow
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

@router.get("/api/v1/auth/linkedin/callback")
async def linkedin_callback(code: str, state: str):
    # state is the user_id passing from auth
    user_id = state
    
    # In development/demo environments without real LinkedIn API
    # credentials configured, simulate a successful connection instead of
    # calling the real LinkedIn API, so the feature can still be demoed.
    # Check if this is a simulated demo login
    is_mock = (
        code == "mock_oauth_code" or 
        not LINKEDIN_CLIENT_ID or 
        "your_linkedin" in LINKEDIN_CLIENT_ID.lower() or 
        not LINKEDIN_CLIENT_SECRET or 
        "your_linkedin" in LINKEDIN_CLIENT_SECRET.lower()
    )
    
    frontend_redirect_success = f"{FRONTEND_BASE_URL}/profile?tab=integrations&status=success"
    
    try:
        db_admin = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY)
        
        if is_mock:
            # Upsert mock account credentials
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
            
        # Exchange the temporary authorization "code" LinkedIn gave us for a
        # real, longer-lived access token we can use to act on the user's behalf.
        # Real code exchange
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
            expires_in = token_data.get("expires_in", 5184000) # Default 60 days
            
            from datetime import datetime, timedelta
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            # Ask LinkedIn who this access token actually belongs to, so we can
            # store their LinkedIn member id alongside the token.
            # Fetch user info
            userinfo_url = "https://api.linkedin.com/v2/userinfo"
            headers = {"Authorization": f"Bearer {access_token}"}
            user_res = await client.get(userinfo_url, headers=headers)
            
            member_id = "unknown_member"
            if user_res.status_code == 200:
                user_data = user_res.json()
                member_id = user_data.get("sub") or user_data.get("id") or "unknown_member"
            else:
                # Newer "userinfo" endpoint failed — fall back to LinkedIn's older
                # "/v2/me" profile endpoint instead.
                # Fallback to /v2/me if userinfo fails
                me_url = "https://api.linkedin.com/v2/me"
                me_res = await client.get(me_url, headers=headers)
                if me_res.status_code == 200:
                    member_id = me_res.json().get("id") or "unknown_member"
            
            # Save the access token, refresh token, and expiry into the database
            # via a Postgres function (RPC) so future job-posting requests can use it.
            # Save account details
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

