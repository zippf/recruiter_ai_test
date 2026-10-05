"""
Job schemas.

Defines request/response models for job openings and related operations.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel


class JobOpeningModel(BaseModel):
    requirement_id: str
    title: str
    description: str
    responsibilities: List[str]
    qualifications: List[str]
    keywords: List[str]
    salary_range: str


class JobOpeningUpdateModel(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    responsibilities: Optional[List[str]] = None
    qualifications: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    salary_range: Optional[str] = None
    status: Optional[str] = None
    processing_status: Optional[str] = None
    error_message: Optional[str] = None
    custom_stages: Optional[List[str]] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    form_timer: Optional[int] = None
    form_threshold: Optional[int] = None
    form_start_date: Optional[str] = None
    form_end_date: Optional[str] = None
    form_fields: Optional[List[Dict[str, Any]]] = None
    form_theme: Optional[str] = None
    form_bg_mode: Optional[str] = None
    candidate_view_settings: Optional[Dict[str, bool]] = None
    stage_notifications: Optional[Dict[str, bool]] = None


class SkillsApprovalModel(BaseModel):
    skills: List[Dict[str, Any]]
    matching_scope: Optional[str] = "both"


class AppendJobsModel(BaseModel):
    additional_description: str
    num_posts_to_add: int


class JobRegenerateModel(BaseModel):
    instruction: str
