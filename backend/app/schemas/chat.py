"""
Chat / chatbot schemas.

Defines request/response models for the in-app AI assistant.
"""
from typing import Dict, Optional, Any
from pydantic import BaseModel


class ChatMessageModel(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None
    current_page: Optional[str] = None
