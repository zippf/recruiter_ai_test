"""
Candidate schemas.

Defines request/response models for the candidates resource.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel


class CandidateModel(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = ""
    skills: List[str] = []
    experience_years: int = 0
    resume_url: Optional[str] = ""
    raw_text: Optional[str] = ""
    education: Optional[str] = ""
    working_or_not: Optional[bool] = True
    academic_details: Optional[str] = ""
    achievements: Optional[str] = ""
    source: str = "manual"
    summary: Optional[str] = ""
    job_id: Optional[str] = None
    uploaded_by: Optional[str] = None
    parsed_resume_json: Optional[Dict[str, Any]] = None


class CandidateUpdateModel(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_years: Optional[int] = None
    resume_url: Optional[str] = None
    raw_text: Optional[str] = None
    education: Optional[str] = None
    working_or_not: Optional[bool] = None
    academic_details: Optional[str] = None
    achievements: Optional[str] = None
    summary: Optional[str] = None
    job_id: Optional[str] = None
    uploaded_by: Optional[str] = None
    parsed_resume_json: Optional[Dict[str, Any]] = None


class CSVUploadModel(BaseModel):
    items: List[Dict[str, Any]]
    job_id: Optional[str] = None
