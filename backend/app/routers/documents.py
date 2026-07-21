"""
Business documents router.

Allows businesses to upload PDF documents that the AI voice agent can
email to customers on request during a call.
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from typing import Optional

from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.documents import DocumentResponse, DocumentListResponse
from app.services.hr_document_embedding_service import (
    process_business_documents,
    process_document_bytes,
    process_stored_document,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

BUCKET = "business-documents"


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    business_id: str = Form(...),
    location_id: Optional[str] = Form(None),
    user_id: str = Depends(get_user_id),
):
    """Upload a PDF document for a business. Stored in Supabase Storage."""
    verify_business_access(user_id, business_id)

    if location_id:
        location = (
            supabase_admin.table("locations")
            .select("id")
            .eq("id", location_id)
            .eq("business_id", business_id)
            .limit(1)
            .execute()
        )
        if not location.data:
            raise HTTPException(
                status_code=403,
                detail="The selected location does not belong to this business.",
            )

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Accept octet-stream as well since some browsers send that for PDFs
        filename_lower = (file.filename or "").lower()
        if not filename_lower.endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Only PDF files are allowed")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    doc_id = str(uuid.uuid4())
    safe_filename = (file.filename or "document.pdf").replace(" ", "_")
    storage_path = f"{business_id}/{doc_id}_{safe_filename}"

    try:
        supabase_admin.storage.from_(BUCKET).upload(
            storage_path,
            file_bytes,
            {"content-type": "application/pdf"},
        )
    except Exception as e:
        logger.error("Storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to upload file to storage: {e}")

    row = {
        "id": doc_id,
        "business_id": business_id,
        "location_id": location_id or None,
        "name": name,
        "description": description or "",
        "file_path": storage_path,
        "file_name": file.filename or safe_filename,
        "file_size_bytes": len(file_bytes),
    }

    try:
        result = supabase_admin.table("business_documents").insert(row).execute()
        if not result.data:
            raise Exception("Insert returned no data")
        inserted = result.data[0]
    except Exception as e:
        # Attempt to clean up the uploaded file
        try:
            supabase_admin.storage.from_(BUCKET).remove([storage_path])
        except Exception:
            pass
        logger.error("DB insert failed after storage upload: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save document record")

    background_tasks.add_task(
        process_document_bytes,
        document_id=doc_id,
        business_id=business_id,
        document_name=name,
        file_bytes=file_bytes,
    )

    return DocumentResponse(**inserted)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    business_id: str,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    """List documents for a business, optionally filtered by location."""
    verify_business_access(user_id, business_id)

    query = (
        supabase_admin.table("business_documents")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
    )
    if location_id:
        query = query.eq("location_id", location_id)
    else:
        query = query.is_("location_id", "null")

    result = query.execute()
    docs = result.data or []
    return DocumentListResponse(documents=[DocumentResponse(**d) for d in docs])


@router.post("/process-embeddings")
async def process_document_embeddings(
    business_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """Queue embedding generation for existing documents that are not ready."""
    role = verify_business_access(user_id, business_id)
    if role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access is required to reprocess documents.")
    result = (
        supabase_admin.table("business_documents")
        .select("id", count="exact")
        .eq("business_id", business_id)
        .neq("embedding_status", "ready")
        .execute()
    )
    queued_count = result.count or len(result.data or [])
    background_tasks.add_task(process_business_documents, business_id)
    return {"queued": queued_count, "status": "processing"}


@router.post("/{document_id}/process-embedding")
async def process_single_document_embedding(
    document_id: str,
    business_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """Retry embedding generation for one business document."""
    role = verify_business_access(user_id, business_id)
    if role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access is required to reprocess documents.")
    result = (
        supabase_admin.table("business_documents")
        .select("id")
        .eq("id", document_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    background_tasks.add_task(
        process_stored_document,
        document_id=document_id,
        business_id=business_id,
    )
    return {"document_id": document_id, "status": "processing"}


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    """Delete a document from storage and the database."""
    verify_business_access(user_id, business_id)

    # Fetch the row first to get the storage path
    result = (
        supabase_admin.table("business_documents")
        .select("id, file_path, business_id")
        .eq("id", document_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = result.data[0]
    storage_path = doc["file_path"]

    # Delete from storage (best-effort)
    try:
        supabase_admin.storage.from_(BUCKET).remove([storage_path])
    except Exception as e:
        logger.warning("Failed to remove file from storage (%s): %s", storage_path, e)

    # Delete DB row
    try:
        supabase_admin.table("business_documents").delete().eq("id", document_id).execute()
    except Exception as e:
        logger.error("Failed to delete document row: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete document record")

    return {"id": document_id, "deleted": True}
