from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DocumentResponse(BaseModel):
    id: str
    business_id: str
    location_id: Optional[str] = None
    name: str
    description: str
    file_name: str
    file_size_bytes: int
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
