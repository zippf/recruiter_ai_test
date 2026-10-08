"""
Callback schemas.

Defines the inbound payload models that n8n AI workflows POST back to this
backend after completing a task (job generation, skill extraction, candidate
matching, question generation, job regeneration, question refinement).

These models must exactly match the JSON shapes that n8n sends — do not
rename fields without also updating the n8n workflows.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Job generation callbacks
# ---------------------------------------------------------------------------

class JobOpeningDraft(BaseModel):
    title: str
    overview: str
    responsibilities: List[str]
    qualifications: List[str]
    budget: str
    seniority: str
    keywords: List[str]
    category: Optional[str] = None
    sub_category: Optional[str] = None


class JobOpeningsCallback(BaseModel):
    requirement_id: str
    job_openings: List[JobOpeningDraft]


# ---------------------------------------------------------------------------
# Skill extraction callbacks
# ---------------------------------------------------------------------------

class ExtractedSkill(BaseModel):
    name: str
    weight: float
    category: Optional[str] = None


class JobSkillsCallback(BaseModel):
    job_opening_id: str
    skills: List[ExtractedSkill]


# ---------------------------------------------------------------------------
# Candidate matching callbacks
# ---------------------------------------------------------------------------

class CandidateMatchItem(BaseModel):
    candidate_id: str
    fuzzy_score: float
    strengths: List[str]
    skill_gaps: List[str]
    reasoning: Optional[str] = None


class CandidateMatchesCallback(BaseModel):
    job_opening_id: str
    matches: List[CandidateMatchItem]


# ---------------------------------------------------------------------------
# Screening question callbacks
# ---------------------------------------------------------------------------

class GeneratedQuestion(BaseModel):
    question: str
    difficulty: str
    category: Optional[str] = None
    order: Optional[int] = None
    reason: Optional[str] = None


class ScreeningQuestionsCallback(BaseModel):
    application_id: str
    questions: List[GeneratedQuestion]


# ---------------------------------------------------------------------------
# Job regeneration callbacks
# ---------------------------------------------------------------------------

class JobRegenerateCallback(BaseModel):
    job_opening_id: str
    title: str
    overview: str
    responsibilities: List[str]
    qualifications: List[str]
    budget: str
    seniority: str
    keywords: List[str]
    category: Optional[str] = None
    sub_category: Optional[str] = None


# ---------------------------------------------------------------------------
# Question refinement callbacks
# ---------------------------------------------------------------------------

class QuestionRefineCallback(BaseModel):
    application_id: str
    question_id: str
    refined_question: str
    difficulty: Optional[str] = None
    reason: Optional[str] = None
