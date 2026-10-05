from typing import List, Optional

from pydantic import BaseModel


class RequirementModel(BaseModel):
    client_id: str
    title: str
    description: str
    skills: List[str]
    experience_min: int
    experience_max: int
    budget_min: float
    budget_max: float
    seniority: str
    notes: Optional[str] = ""
    num_posts_requested: int = 1


class RequirementUpdateModel(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[List[str]] = None
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    seniority: Optional[str] = None
    notes: Optional[str] = None
    num_posts_requested: Optional[int] = None
    status: Optional[str] = None
