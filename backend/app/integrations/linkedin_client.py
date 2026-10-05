"""
LinkedIn integration client.

Handles LinkedIn OAuth token exchange and UGC post publishing.

The route handlers (authorize, callback, share-linkedin) live in
app/api/v1/linkedin.py and app/api/v1/integrations.py. This module
provides the pure HTTP calls to LinkedIn's API, separated from FastAPI
request/response concerns.

Extracted from main_commented (1).py lines 7255–7390 (OAuth) and
lines 7510–7660 (post sharing — embedded in jobs router currently).

Preserves:
- Mock flow for missing/placeholder LinkedIn credentials
- Token exchange with https://www.linkedin.com/oauth/v2/accessToken
- Member ID resolution via /v2/userinfo (fallback to /v2/me)
- UGC post creation via https://api.linkedin.com/v2/ugcPosts
- Company-page-to-personal-feed fallback on 403
"""
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from app.core.config import (
    BACKEND_BASE_URL,
    FRONTEND_BASE_URL,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
)
from app.core.logging import logger


def build_authorization_url(user_id: str) -> str:
    """
    Build the LinkedIn OAuth authorization URL for the given user.

    If LinkedIn credentials are not configured, returns a mock redirect URL
    for local testing.
    """
    if (
        not LINKEDIN_CLIENT_ID
        or "your_linkedin" in (LINKEDIN_CLIENT_ID or "").lower()
        or LINKEDIN_CLIENT_ID == "null"
    ):
        return f"{BACKEND_BASE_URL}/api/v1/auth/linkedin/callback?code=mock_oauth_code&state={user_id}"

    scopes = "openid profile w_member_social"
    encoded_redirect = urllib.parse.quote(LINKEDIN_REDIRECT_URI)
    encoded_scopes = urllib.parse.quote(scopes)
    return (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={LINKEDIN_CLIENT_ID}"
        f"&redirect_uri={encoded_redirect}"
        f"&state={user_id}"
        f"&scope={encoded_scopes}"
    )


def is_mock_oauth(code: str) -> bool:
    """Return True when the OAuth code or credentials indicate a mock/demo flow."""
    return (
        code == "mock_oauth_code"
        or not LINKEDIN_CLIENT_ID
        or "your_linkedin" in (LINKEDIN_CLIENT_ID or "").lower()
        or not LINKEDIN_CLIENT_SECRET
        or "your_linkedin" in (LINKEDIN_CLIENT_SECRET or "").lower()
    )


def build_mock_account_payload(user_id: str) -> Dict[str, Any]:
    """Return a mock linkedin_accounts upsert payload for demo/test flows."""
    expires_at = datetime.utcnow() + timedelta(days=60)
    return {
        "p_user_id": user_id,
        "p_linkedin_member_id": "mock_member_12345",
        "p_linkedin_access_token": "mock_access_token_abcde12345",
        "p_linkedin_refresh_token": "mock_refresh_token_xyz987",
        "p_expires_at": expires_at.isoformat(),
    }


async def exchange_code_for_token(code: str) -> Tuple[str, Optional[str], datetime]:
    """
    Exchange a LinkedIn OAuth authorization code for an access token.

    Returns (access_token, refresh_token, expires_at).
    Raises HTTPException on failure.
    """
    async with httpx.AsyncClient() as client:
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        }
        token_res = await client.post(token_url, data=data)
        if token_res.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"LinkedIn token exchange failed: {token_res.text}",
            )

        token_data = token_res.json()
        access_token: str = token_data["access_token"]
        refresh_token: Optional[str] = token_data.get("refresh_token")
        expires_in: int = token_data.get("expires_in", 5_184_000)  # default 60 days
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        return access_token, refresh_token, expires_at


async def resolve_linkedin_member_id(access_token: str) -> str:
    """
    Fetch the LinkedIn member ID for the given access token.

    Tries /v2/userinfo first, falls back to /v2/me.
    Returns 'unknown_member' if both endpoints fail.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        user_res = await client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        if user_res.status_code == 200:
            data = user_res.json()
            return data.get("sub") or data.get("id") or "unknown_member"

        me_res = await client.get("https://api.linkedin.com/v2/me", headers=headers)
        if me_res.status_code == 200:
            return me_res.json().get("id") or "unknown_member"

    return "unknown_member"


async def publish_ugc_post(
    access_token: str,
    author_urn: str,
    text: str,
    linkedin_member_id: Optional[str] = None,
) -> Tuple[str, bool]:
    """
    Publish a UGC post to LinkedIn.

    If posting to the given author URN (company page) returns 403, falls back
    to the personal profile URN if `linkedin_member_id` is provided.

    Returns (post_id, is_personal).
    Raises HTTPException on failure.
    """
    ugc_url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }
    is_personal = not author_urn.startswith("urn:li:organization:")

    ugc_payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(ugc_url, json=ugc_payload, headers=headers)

        # Fallback: company page 403 → retry as personal profile
        if res.status_code == 403 and not is_personal and linkedin_member_id:
            logger.warning(
                "LinkedIn Company Page post failed (403). Retrying as personal profile."
            )
            author_urn = f"urn:li:person:{linkedin_member_id}"
            ugc_payload["author"] = author_urn
            res = await client.post(ugc_url, json=ugc_payload, headers=headers)
            is_personal = True

        if res.status_code not in (200, 201):
            raise HTTPException(
                status_code=500,
                detail=f"LinkedIn API error (Status {res.status_code}): {res.text}",
            )

        post_id: str = res.json().get("id") or "urn:li:share:unknown"
        return post_id, is_personal
