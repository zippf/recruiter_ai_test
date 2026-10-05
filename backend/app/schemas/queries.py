"""
Candidate query schemas.

Defines request/response models for the candidate Q&A / queries feature.
"""
from pydantic import BaseModel


class CandidateQueryCreateModel(BaseModel):
    candidate_email: str
    query_text: str


class ResolveQueryModel(BaseModel):
    is_resolved: bool = True


class AnswerQueryModel(BaseModel):
    response_text: str
