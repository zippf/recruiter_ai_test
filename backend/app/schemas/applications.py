"""
Application schemas.

Defines request/response models for the applications resource.
"""
from typing import Optional
from pydantic import BaseModel


class VerifyStatusModel(BaseModel):
    email: str
    application_id: Optional[str] = ""


class CandidateMessageCreateModel(BaseModel):
    message_text: str


class EndConversationModel(BaseModel):
    candidate_email: str
    job_id: str
