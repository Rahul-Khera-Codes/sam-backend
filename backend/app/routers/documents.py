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
from app.schemas.documents import (
    DocumentResponse,
    DocumentListResponse,
    HrPolicyBulkDeleteRequest,
    HrPolicyDocumentListResponse,
    HrPolicyDocumentResponse,
    HrPolicyDocumentUpdateRequest,
    HrPolicyMergeCategoriesRequest,
    HrPolicyReadProgressRequest,
)
from app.services.hr_document_embedding_service import (
    HR_POLICY_DOCUMENT_BUCKET,
    process_business_documents,
    process_document_bytes,
    process_stored_document,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

BUCKET = "business-documents"


def _require_admin(user_id: str, business_id: str) -> None:
    role = verify_business_access(user_id, business_id)
    if role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access is required for this document action.")


def _parse_tags(raw_tags: str) -> list[str]:
    tags = [tag.strip() for tag in raw_tags.replace("\n", ",").split(",")]
    return [tag for tag in tags if tag][:12]


def _normalize_category(category: str | None) -> str:
    normalized = (category or "").strip()
    return normalized or "General"


def _hr_policy_response(row: dict, progress_percent: int = 0) -> HrPolicyDocumentResponse:
    uploaded_by_name = None
    uploaded_by_profile = row.get("uploaded_by_profile")
    if isinstance(uploaded_by_profile, dict):
        parts = [
            uploaded_by_profile.get("first_name") or "",
            uploaded_by_profile.get("last_name") or "",
        ]
        uploaded_by_name = " ".join(part for part in parts if part).strip() or uploaded_by_profile.get("email")

    return HrPolicyDocumentResponse(
        **{key: value for key, value in row.items() if key != "uploaded_by_profile"},
        uploaded_by_name=uploaded_by_name,
        progress_percent=progress_percent,
    )


def _fetch_hr_policy_document(document_id: str, business_id: str) -> dict:
    result = (
        supabase_admin.table("business_documents")
        .select("*")
        .eq("id", document_id)
        .eq("business_id", business_id)
        .eq("document_scope", "hr_onboarding")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="HR policy document not found")
    return result.data[0]


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


@router.post("/hr-policy/upload", response_model=HrPolicyDocumentResponse)
async def upload_hr_policy_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(...),
    business_id: str = Form(...),
    description: str = Form(""),
    category: str = Form("General"),
    tags: str = Form(""),
    user_id: str = Depends(get_user_id),
):
    """Upload an HR policy PDF and queue it for onboarding AI context."""
    _require_admin(user_id, business_id)

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        filename_lower = (file.filename or "").lower()
        if not filename_lower.endswith(".pdf"):
            raise HTTPException(status_code=422, detail="Only PDF files are allowed")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    doc_id = str(uuid.uuid4())
    safe_filename = (file.filename or "hr-policy.pdf").replace(" ", "_")
    storage_path = f"{business_id}/{doc_id}_{safe_filename}"
    normalized_category = _normalize_category(category)
    parsed_tags = _parse_tags(tags)

    try:
        supabase_admin.storage.from_(HR_POLICY_DOCUMENT_BUCKET).upload(
            storage_path,
            file_bytes,
            {"content-type": "application/pdf"},
        )
    except Exception as e:
        logger.error("HR policy storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to upload file to storage: {e}")

    row = {
        "id": doc_id,
        "business_id": business_id,
        "location_id": None,
        "name": name.strip() or (file.filename or "HR policy document"),
        "description": description or "",
        "file_path": storage_path,
        "file_name": file.filename or safe_filename,
        "file_size_bytes": len(file_bytes),
        "document_scope": "hr_onboarding",
        "category": normalized_category,
        "tags": parsed_tags,
        "status": "published",
        "uploaded_by": user_id,
        "storage_bucket": HR_POLICY_DOCUMENT_BUCKET,
    }

    try:
        result = supabase_admin.table("business_documents").insert(row).execute()
        if not result.data:
            raise Exception("Insert returned no data")
        inserted = result.data[0]
    except Exception as e:
        try:
            supabase_admin.storage.from_(HR_POLICY_DOCUMENT_BUCKET).remove([storage_path])
        except Exception:
            pass
        logger.error("HR policy DB insert failed after storage upload: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save HR policy document record")

    background_tasks.add_task(
        process_document_bytes,
        document_id=doc_id,
        business_id=business_id,
        document_name=inserted["name"],
        file_bytes=file_bytes,
        metadata={
            "document_scope": "hr_onboarding",
            "category": normalized_category,
            "status": "published",
            "storage_bucket": HR_POLICY_DOCUMENT_BUCKET,
        },
    )

    return _hr_policy_response(inserted)


@router.get("/hr-policy", response_model=HrPolicyDocumentListResponse)
async def list_hr_policy_documents(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    """List HR policy documents for the onboarding library."""
    verify_business_access(user_id, business_id)
    result = (
        supabase_admin.table("business_documents")
        .select("*")
        .eq("business_id", business_id)
        .eq("document_scope", "hr_onboarding")
        .order("created_at", desc=True)
        .execute()
    )
    progress_rows = (
        supabase_admin.table("hr_document_read_progress")
        .select("document_id,progress_percent")
        .eq("business_id", business_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    progress_by_doc = {row["document_id"]: int(row.get("progress_percent") or 0) for row in progress_rows}
    documents = [
        _hr_policy_response(row, progress_by_doc.get(row["id"], 0))
        for row in (result.data or [])
    ]
    return HrPolicyDocumentListResponse(documents=documents)


@router.patch("/hr-policy/{document_id}", response_model=HrPolicyDocumentResponse)
async def update_hr_policy_document(
    document_id: str,
    req: HrPolicyDocumentUpdateRequest,
    user_id: str = Depends(get_user_id),
):
    _require_admin(user_id, req.business_id)
    _fetch_hr_policy_document(document_id, req.business_id)

    updates: dict = {}
    if req.name is not None:
        updates["name"] = req.name.strip() or "HR policy document"
    if req.description is not None:
        updates["description"] = req.description
    if req.category is not None:
        updates["category"] = _normalize_category(req.category)
    if req.tags is not None:
        updates["tags"] = [tag.strip() for tag in req.tags if tag.strip()][:12]
    if req.status is not None:
        if req.status not in ("draft", "in_review", "published", "archived"):
            raise HTTPException(status_code=422, detail="Invalid document status")
        updates["status"] = req.status

    if not updates:
        return _hr_policy_response(_fetch_hr_policy_document(document_id, req.business_id))

    result = (
        supabase_admin.table("business_documents")
        .update(updates)
        .eq("id", document_id)
        .eq("business_id", req.business_id)
        .eq("document_scope", "hr_onboarding")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="HR policy document not found")
    return _hr_policy_response(result.data[0])


@router.post("/hr-policy/merge-categories")
async def merge_hr_policy_categories(
    req: HrPolicyMergeCategoriesRequest,
    user_id: str = Depends(get_user_id),
):
    _require_admin(user_id, req.business_id)
    from_category = _normalize_category(req.from_category)
    to_category = _normalize_category(req.to_category)
    if from_category == to_category:
        return {"updated": 0, "category": to_category}

    result = (
        supabase_admin.table("business_documents")
        .update({"category": to_category})
        .eq("business_id", req.business_id)
        .eq("document_scope", "hr_onboarding")
        .eq("category", from_category)
        .execute()
    )
    return {"updated": len(result.data or []), "category": to_category}


@router.post("/hr-policy/bulk-delete")
async def bulk_delete_hr_policy_documents(
    req: HrPolicyBulkDeleteRequest,
    user_id: str = Depends(get_user_id),
):
    _require_admin(user_id, req.business_id)
    rows = (
        supabase_admin.table("business_documents")
        .select("id,file_path,storage_bucket")
        .eq("business_id", req.business_id)
        .eq("document_scope", "hr_onboarding")
        .in_("id", req.document_ids)
        .execute()
        .data
        or []
    )
    if not rows:
        return {"deleted": 0}

    paths_by_bucket: dict[str, list[str]] = {}
    for row in rows:
        bucket = row.get("storage_bucket") or HR_POLICY_DOCUMENT_BUCKET
        paths_by_bucket.setdefault(bucket, []).append(row["file_path"])

    for bucket, paths in paths_by_bucket.items():
        try:
            supabase_admin.storage.from_(bucket).remove(paths)
        except Exception as e:
            logger.warning("Failed to remove HR policy files from %s: %s", bucket, e)

    (
        supabase_admin.table("business_documents")
        .delete()
        .eq("business_id", req.business_id)
        .eq("document_scope", "hr_onboarding")
        .in_("id", [row["id"] for row in rows])
        .execute()
    )
    return {"deleted": len(rows)}


@router.get("/hr-policy/{document_id}/signed-url")
async def get_hr_policy_document_signed_url(
    document_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    doc = _fetch_hr_policy_document(document_id, business_id)
    bucket = doc.get("storage_bucket") or HR_POLICY_DOCUMENT_BUCKET
    try:
        signed = supabase_admin.storage.from_(bucket).create_signed_url(doc["file_path"], 3600)
    except Exception as e:
        logger.error("Failed to sign HR policy document %s: %s", document_id, e)
        raise HTTPException(status_code=500, detail="Failed to create document link")
    return {"url": signed.get("signedURL"), "expires_in_seconds": 3600}


@router.post("/hr-policy/{document_id}/process-embedding")
async def retry_hr_policy_document_embedding(
    document_id: str,
    business_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    _require_admin(user_id, business_id)
    _fetch_hr_policy_document(document_id, business_id)
    background_tasks.add_task(
        process_stored_document,
        document_id=document_id,
        business_id=business_id,
        storage_bucket=HR_POLICY_DOCUMENT_BUCKET,
    )
    return {"document_id": document_id, "status": "processing"}


@router.post("/hr-policy/{document_id}/progress")
async def save_hr_policy_read_progress(
    document_id: str,
    req: HrPolicyReadProgressRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, req.business_id)
    _fetch_hr_policy_document(document_id, req.business_id)
    row = {
        "business_id": req.business_id,
        "document_id": document_id,
        "user_id": user_id,
        "progress_percent": req.progress_percent,
    }
    supabase_admin.table("hr_document_read_progress").upsert(
        row,
        on_conflict="document_id,user_id",
    ).execute()
    return {"document_id": document_id, "progress_percent": req.progress_percent}


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
