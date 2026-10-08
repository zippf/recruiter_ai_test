from typing import Optional

from fastapi import Header, HTTPException
from supabase import Client, ClientOptions, create_client

from app.core.config import SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


def get_safe_supabase_client(
    url: str, key: str, jwt_token: Optional[str] = None
) -> Client:
    dummy_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.key"
    headers = {}
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"

    client = create_client(url, dummy_jwt, options=ClientOptions(headers=headers))
    client.supabase_key = key
    client.options.headers["apiKey"] = key
    if not jwt_token:
        client.options.headers["Authorization"] = f"Bearer {key}"

    if hasattr(client, "auth") and client.auth:
        client.auth._headers["apiKey"] = key
        if jwt_token:
            client.auth._headers["Authorization"] = f"Bearer {jwt_token}"
        else:
            client.auth._headers["Authorization"] = f"Bearer {key}"

    return client


def get_admin_supabase_client() -> Client:
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    if not key:
        raise HTTPException(
            status_code=500, detail="Supabase key not configured on server"
        )
    return get_safe_supabase_client(SUPABASE_URL, key)


def get_supabase(authorization: Optional[str] = Header(None)) -> Client:
    jwt_token = None
    if authorization:
        if authorization.startswith("Bearer "):
            jwt_token = authorization.split(" ")[1]
        elif authorization.startswith("eyJ"):
            jwt_token = authorization
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    return get_safe_supabase_client(SUPABASE_URL, key, jwt_token)
