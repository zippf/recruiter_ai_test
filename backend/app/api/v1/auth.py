from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from typing import Optional
from supabase import Client
import httpx
import time

from app.core.logging import logger
from app.api.dependencies import (
    get_admin_supabase_client, get_supabase, get_current_user_id, 
    get_user_org_id, get_safe_supabase_client
)
from app.schemas.common import (
    SignupRequestModel, AuthLogEventModel, 
    PasswordOtpRequestModel, PasswordOtpConfirmModel
)
from app.services.notification_service import log_activity_event, send_email
from app.core.config import (
    FRONTEND_BASE_URL, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, 
    LINKEDIN_REDIRECT_URI, SUPABASE_URL, SUPABASE_KEY
)

router = APIRouter()
password_otps = {}

@router.post("/api/v1/auth/signup")
async def signup_recruiter(payload: SignupRequestModel):
    db = get_admin_supabase_client()
    try:
        res = db.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": payload.full_name
            }
        })
        if not res.user:
            raise HTTPException(status_code=400, detail="Failed to create user account.")

        # Log user_signup event into activity_log
        log_activity_event(
            db=db,
            action="user_signup",
            entity_type="user",
            entity_id=res.user.id,
            actor_name=payload.full_name or payload.email,
            actor_id=res.user.id,
            metadata={"email": payload.email, "source": "signup_recruiter"}
        )
        return {"status": "success", "user_id": res.user.id, "auto_confirmed": True}
    except Exception as e:
        err_str = str(getattr(e, 'message', str(e)))
        logger.error(f"Error creating user in signup_recruiter: {err_str}")
        if "already registered" in err_str.lower() or "already exists" in err_str.lower():
            try:
                p_res = db.table("profiles").select("id").eq("email", payload.email).execute()
                if p_res.data:
                    u_id = p_res.data[0]["id"]
                    db.auth.admin.update_user_by_id(u_id, {
                        "email_confirm": True,
                        "password": payload.password,
                        "user_metadata": {"full_name": payload.full_name}
                    })
                    return {"status": "success", "user_id": u_id, "auto_confirmed": True}
            except Exception as update_err:
                logger.error(f"Failed to auto-confirm existing user: {update_err}")
            raise HTTPException(status_code=409, detail="This email is already registered.")
        raise HTTPException(status_code=400, detail=err_str)


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


@router.post("/api/v1/auth/request-password-otp")
async def request_password_otp(payload: PasswordOtpRequestModel, db: Client = Depends(get_supabase), user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Get user email and full name from the profiles table
    try:
        prof_res = db.table("profiles").select("email, full_name").eq("id", user_id).execute()
        if not prof_res.data:
            raise HTTPException(status_code=404, detail="Recruiter profile not found")
        
        user_email = prof_res.data[0].get("email")
        user_name = prof_res.data[0].get("full_name") or "Recruiter"
    except Exception as e:
        logger.error(f"Failed to fetch profile details for password OTP: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user profile details")

    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found in profile")

    # Generate 6-digit numeric OTP
    import random
    otp_code = f"{random.randint(100000, 999999)}"
    
    # Store OTP in cache (expires in 5 minutes)
    password_otps[user_id] = {
        "otp": otp_code,
        "new_password": payload.new_password,
        "expires_at": time.time() + 300
    }
    
    # Send email
    subject = "Confirm Your Password Change Request - Kozker AI"
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 4px;">
            <div style="background-color: #ff7e5f; padding: 15px; border-radius: 4px 4px 0 0; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 18px; text-transform: uppercase; letter-spacing: 1px;">Kozker Security</h2>
            </div>
            <div style="padding: 20px 10px; text-align: center;">
                <p style="font-size: 14px; color: #4a5568;">Hi {user_name},</p>
                <p style="font-size: 14px; color: #4a5568;">You requested a password change. Please use the following One-Time Password (OTP) to confirm your identity:</p>
                <div style="background-color: #f7fafc; border: 1px dashed #cbd5e0; padding: 15px; margin: 20px auto; font-size: 28px; font-weight: bold; letter-spacing: 4px; color: #ff7e5f; display: inline-block; border-radius: 4px;">
                    {otp_code}
                </div>
                <p style="font-size: 12px; color: #718096; margin-top: 10px;">This OTP is valid for 5 minutes. If you did not request this change, please ignore this email and secure your account immediately.</p>
            </div>
            <div style="border-top: 1px solid #e2e8f0; padding-top: 15px; text-align: center; font-size: 11px; color: #718096;">
                This is a secure automated notification from Kozker Recruiter AI.
            </div>
        </body>
    </html>
    """
    try:
        send_email(user_email, subject, html_body, sender_name="Kozker Security")
    except Exception as e:
        logger.error(f"Failed to dispatch password change OTP email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email")

    return {"status": "success", "message": "OTP has been sent to your registered email."}



@router.post("/api/v1/auth/confirm-password-otp")
async def confirm_password_otp(payload: PasswordOtpConfirmModel, request: Request, user_id: Optional[str] = Depends(get_current_user_id)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    otp_data = password_otps.get(user_id)
    if not otp_data:
        raise HTTPException(status_code=400, detail="No pending password change request found or OTP expired.")
    
    if time.time() > otp_data["expires_at"]:
        password_otps.pop(user_id, None)
        raise HTTPException(status_code=400, detail="OTP code has expired. Please request a new one.")
        
    if otp_data["otp"] != payload.otp.strip():
        raise HTTPException(status_code=400, detail="Invalid OTP code. Please check and try again.")
        
    new_password = otp_data["new_password"]
    
    # Retrieve user's JWT from Authorization header
    auth_header = request.headers.get("Authorization", "")
    jwt_token = ""
    if auth_header:
        if auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]
        elif auth_header.startswith("eyJ"):
            jwt_token = auth_header
            
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Missing authorization token")
        
    # Update password using user-specific client by seeding active session
    try:
        user_client = get_safe_supabase_client(SUPABASE_URL, SUPABASE_KEY, jwt_token)
        # Seed user session into client auth state to bypass AuthSessionMissingError
        user_client.auth.set_session(jwt_token, "dummy-refresh-token")
        user_client.auth.update_user(attributes={"password": new_password})
        
        # Evict from cache
        password_otps.pop(user_id, None)
    except Exception as e:
        logger.error(f"User password update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update password: {str(e)}")
        
    return {"status": "success", "message": "Password updated successfully."}



