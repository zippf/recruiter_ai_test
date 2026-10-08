"""
Skills schemas.

Defines request/response models for skill-related operations.
Skills are stored as part of job openings and candidates; this module
holds the shared skill-shape models used across both resources.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel


class SkillItem(BaseModel):
    """A single skill with name, weight and optional category."""
    name: str
    weight: float
    category: Optional[str] = None
