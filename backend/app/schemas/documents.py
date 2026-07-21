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
    embedding_status: str = "pending"
    embedding_error: Optional[str] = None
    embedding_model: Optional[str] = None
    embedded_at: Optional[datetime] = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
