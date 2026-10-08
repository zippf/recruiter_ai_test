"""
Auth schemas.

Defines request/response models for authentication and user management.
"""
from typing import Optional
from pydantic import BaseModel


class PasswordOtpRequestModel(BaseModel):
    new_password: str


class PasswordOtpConfirmModel(BaseModel):
    otp: str


class SignupRequestModel(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = ""


class AuthLogEventModel(BaseModel):
    action: str  # "user_login", "user_logout", "user_signup"
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    email: Optional[str] = None
    organization_id: Optional[str] = None
    metadata: Optional[dict] = None


class PruneLogsRequestModel(BaseModel):
    days_older_than: Optional[int] = None
    before_date: Optional[str] = None
    organization_id: Optional[str] = None
