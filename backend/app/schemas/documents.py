from pydantic import BaseModel, Field
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
    document_scope: str = "business"
    category: str = "General"
    tags: list[str] = Field(default_factory=list)
    status: str = "published"
    uploaded_by: Optional[str] = None
    storage_bucket: str = "business-documents"


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse] = Field(default_factory=list)


class HrPolicyDocumentResponse(DocumentResponse):
    uploaded_by_name: Optional[str] = None
    progress_percent: int = 0


class HrPolicyDocumentListResponse(BaseModel):
    documents: list[HrPolicyDocumentResponse] = Field(default_factory=list)


class HrPolicyDocumentUpdateRequest(BaseModel):
    business_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


class HrPolicyMergeCategoriesRequest(BaseModel):
    business_id: str
    from_category: str = Field(min_length=1)
    to_category: str = Field(min_length=1)


class HrPolicyBulkDeleteRequest(BaseModel):
    business_id: str
    document_ids: list[str] = Field(min_length=1)


class HrPolicyReadProgressRequest(BaseModel):
    business_id: str
    progress_percent: int = Field(ge=0, le=100)


class OnboardingChatRequest(BaseModel):
    business_id: str
    question: str = Field(min_length=1, max_length=2_000)
    document_id: Optional[str] = None


class OnboardingChatSource(BaseModel):
    document_id: str
    document_name: str
    category: Optional[str] = None
    excerpt: str
    similarity: float = 0


class OnboardingChatResponse(BaseModel):
    answer: str
    sources: list[OnboardingChatSource] = Field(default_factory=list)
