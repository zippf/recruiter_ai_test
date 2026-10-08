"""
Question schemas.

Defines request/response models for screening questions.
"""
from pydantic import BaseModel


class QuestionCreateModel(BaseModel):
    question: str
    difficulty: str = "medium"
