"""
Approval workflow schemas.

Defines request/response models for the multi-stage approval pipeline system.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel


class StageApproverInput(BaseModel):
    role_id: Optional[str] = None
    member_id: Optional[str] = None


class StageInput(BaseModel):
    stage_name: str
    require_all_approvers: bool = False
    approvers: List[StageApproverInput] = []


class PipelineCreateInput(BaseModel):
    name: str
    description: Optional[str] = None
    is_template: bool = False
    entity_type: str = "custom"
    entity_id: Optional[str] = None
    custom_content: Optional[Dict[str, Any]] = None
    stages: List[StageInput] = []


class PipelineApproveInput(BaseModel):
    notes: Optional[str] = None


class HighlightedFieldInput(BaseModel):
    field_name: str
    field_value: Optional[str] = None
    note: Optional[str] = None


class PipelineRejectInput(BaseModel):
    reasons: List[str] = []
    highlighted_fields: List[Dict[str, Any]] = []
    feedback_notes: Optional[str] = None


class PipelineInstantiateInput(BaseModel):
    name: Optional[str] = None
    custom_content: Optional[Dict[str, Any]] = None


class PipelineAccessInput(BaseModel):
    role_id: Optional[str] = None
    member_id: Optional[str] = None
    access_level: str = "view"


class ApprovalEmailInput(BaseModel):
    to: str
    pipelineName: Optional[str] = "Approval Workflow"
    stageName: Optional[str] = "Approval Stage"
    submitterName: Optional[str] = "Team Member"
    contentPreview: Optional[str] = ""
    rejectionChecklist: Optional[Dict[str, Any]] = None
    feedbackNotes: Optional[str] = None
    subject: Optional[str] = None
    html: Optional[str] = None
