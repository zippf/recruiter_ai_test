"""
Client schemas.

Defines the request/response models for the clients resource.
"""
from pydantic import BaseModel


class ClientModel(BaseModel):
    name: str
