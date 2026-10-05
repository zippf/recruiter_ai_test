"""
LinkedIn schemas.

Defines request/response models for LinkedIn integration.
"""
from pydantic import BaseModel


class CompanyPageModel(BaseModel):
    company_page_id: str


class SharePostModel(BaseModel):
    text: str
