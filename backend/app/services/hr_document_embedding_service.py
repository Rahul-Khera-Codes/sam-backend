from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langsmith import traceable
from openai import AsyncOpenAI
from pypdf import PdfReader

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services.hr_onboarding_langsmith_service import (
    HR_ONBOARDING_TRACE_METADATA,
    HR_ONBOARDING_TRACE_TAGS,
    compact_text,
    summarize_chunks,
    summarize_matches,
    summarize_metadata,
)

logger = logging.getLogger(__name__)

DOCUMENT_BUCKET = "business-documents"
HR_POLICY_DOCUMENT_BUCKET = "hr-policy-docs"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_DOCUMENT_TEXT_CHARS = 240_000
CHUNK_SIZE_CHARS = 2_400
CHUNK_OVERLAP_CHARS = 300
EMBEDDING_BATCH_SIZE = 32
INSERT_BATCH_SIZE = 20
HR_POLICY_CHUNK_SEPARATORS = ["\n\n", "\n", ". ", "; ", " ", ""]


def _process_extract_pdf_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    file_bytes = inputs.get("file_bytes") or b""
    return {"file_size_bytes": len(file_bytes)}


def _process_extract_pdf_outputs(outputs: str) -> dict[str, Any]:
    return {
        "text_chars": len(outputs or ""),
        "text_preview": compact_text(outputs),
    }


def _process_chunk_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    text = str(inputs.get("text") or "")
    return {
        "text_chars": len(text),
        "text_preview": compact_text(text),
    }


def _process_chunk_outputs(outputs: list[str]) -> dict[str, Any]:
    return summarize_chunks(outputs)


def _process_embedding_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    chunks = inputs.get("chunks") or inputs.get("batch") or []
    return summarize_chunks(chunks)


def _process_embedding_outputs(outputs: list[list[float]]) -> dict[str, Any]:
    first_embedding = outputs[0] if outputs else []
    return {
        "embedding_count": len(outputs),
        "embedding_dimensions": len(first_embedding),
        "embedding_model": EMBEDDING_MODEL,
    }


def _process_query_embedding_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    query = str(inputs.get("query") or "")
    return {
        "query_chars": len(query),
        "query_preview": compact_text(query),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
    }


def _process_query_embedding_outputs(outputs: list[float]) -> dict[str, Any]:
    return {
        "embedding_dimensions": len(outputs),
        "embedding_model": EMBEDDING_MODEL,
    }


def _process_replace_chunks_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    chunks = inputs.get("chunks") or []
    embeddings = inputs.get("embeddings") or []
    return {
        "document_id": inputs.get("document_id"),
        "business_id": inputs.get("business_id"),
        "document_name": inputs.get("document_name"),
        "chunking_strategy": inputs.get("chunking_strategy"),
        "metadata": summarize_metadata(inputs.get("metadata")),
        "chunks": summarize_chunks(chunks),
        "embedding_count": len(embeddings),
    }


def _process_document_bytes_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    file_bytes = inputs.get("file_bytes") or b""
    return {
        "document_id": inputs.get("document_id"),
        "business_id": inputs.get("business_id"),
        "document_name": inputs.get("document_name"),
        "file_size_bytes": len(file_bytes),
        "metadata": summarize_metadata(inputs.get("metadata")),
        "raise_on_error": inputs.get("raise_on_error", False),
    }


def _process_retrieval_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    query = str(inputs.get("query") or "")
    return {
        "business_id": inputs.get("business_id"),
        "query_chars": len(query),
        "query_preview": compact_text(query),
        "document_id": inputs.get("document_id"),
        "category": inputs.get("category"),
        "match_count": inputs.get("match_count"),
        "match_threshold": inputs.get("match_threshold"),
    }


def _process_retrieval_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_matches(outputs)


def _update_document_status(
    document_id: str,
    business_id: str,
    *,
    status: str,
    error: str | None = None,
    embedded_at: str | None = None,
) -> None:
    (
        supabase_admin.table("business_documents")
        .update(
            {
                "embedding_status": status,
                "embedding_error": error,
                "embedding_model": EMBEDDING_MODEL,
                "embedded_at": embedded_at,
            }
        )
        .eq("id", document_id)
        .eq("business_id", business_id)
        .execute()
    )


def extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages: list[str] = []
    total_chars = 0

    for page in reader.pages:
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        remaining = MAX_DOCUMENT_TEXT_CHARS - total_chars
        if remaining <= 0:
            break
        pages.append(page_text[:remaining])
        total_chars += min(len(page_text), remaining)

    return "\n\n".join(pages).strip()


@traceable(
    name="hr_onboarding.ingestion.extract_pdf_text",
    run_type="parser",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_extract_pdf_inputs,
    process_outputs=_process_extract_pdf_outputs,
)
def _extract_pdf_text_traced(file_bytes: bytes) -> str:
    return extract_pdf_text(file_bytes)


def _normalize_document_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def chunk_document_text(text: str) -> list[str]:
    normalized = _normalize_document_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(normalized)

    while start < text_length:
        end = min(start + CHUNK_SIZE_CHARS, text_length)
        if end < text_length:
            paragraph_break = normalized.rfind("\n\n", start + CHUNK_SIZE_CHARS // 2, end)
            sentence_break = normalized.rfind(". ", start + CHUNK_SIZE_CHARS // 2, end)
            split_at = max(paragraph_break, sentence_break)
            if split_at > start:
                end = split_at + (2 if split_at == sentence_break else 0)

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)

    return chunks


@traceable(
    name="hr_onboarding.ingestion.split_hr_policy_text",
    run_type="parser",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_chunk_inputs,
    process_outputs=_process_chunk_outputs,
)
def chunk_hr_policy_document_text(text: str) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_CHARS,
        chunk_overlap=CHUNK_OVERLAP_CHARS,
        length_function=len,
        separators=HR_POLICY_CHUNK_SEPARATORS,
        is_separator_regex=False,
    )

    return [chunk.strip() for chunk in splitter.split_text(normalized) if chunk.strip()]


async def _create_embeddings(chunks: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0,
        max_retries=2,
    )
    embeddings: list[list[float]] = []

    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        embeddings.extend(await _create_embedding_batch(client=client, batch=batch, batch_index=start // EMBEDDING_BATCH_SIZE))

    return embeddings


@traceable(
    name="hr_onboarding.ingestion.create_embeddings",
    run_type="embedding",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_embedding_inputs,
    process_outputs=_process_embedding_outputs,
)
async def _create_embeddings_traced(chunks: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0,
        max_retries=2,
    )
    embeddings: list[list[float]] = []

    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        embeddings.extend(
            await _create_embedding_batch_traced(
                client=client,
                batch=batch,
                batch_index=start // EMBEDDING_BATCH_SIZE,
            )
        )

    return embeddings


async def _create_embedding_batch(
    *,
    client: AsyncOpenAI,
    batch: list[str],
    batch_index: int,
) -> list[list[float]]:
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=batch,
        dimensions=EMBEDDING_DIMENSIONS,
        encoding_format="float",
    )
    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


@traceable(
    name="hr_onboarding.ingestion.create_embedding_batch",
    run_type="embedding",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_embedding_inputs,
    process_outputs=_process_embedding_outputs,
)
async def _create_embedding_batch_traced(
    *,
    client: AsyncOpenAI,
    batch: list[str],
    batch_index: int,
) -> list[list[float]]:
    return await _create_embedding_batch(client=client, batch=batch, batch_index=batch_index)


def _replace_document_chunks(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    chunking_strategy: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    (
        supabase_admin.table("hr_document_chunks")
        .delete()
        .eq("document_id", document_id)
        .eq("business_id", business_id)
        .execute()
    )

    base_metadata = metadata or {}
    rows = [
        {
            "business_id": business_id,
            "document_id": document_id,
            "chunk_index": index,
            "content": content,
            "embedding": embedding,
            "embedding_model": EMBEDDING_MODEL,
            "metadata": {
                **base_metadata,
                "business_id": business_id,
                "document_id": document_id,
                "document_name": document_name,
                "category": base_metadata.get("category") or "General",
                "chunk_index": index,
                "chunk_size_chars": len(content),
                "chunking_strategy": chunking_strategy,
                "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
                "embedding_model": EMBEDDING_MODEL,
            },
        }
        for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    ]

    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        supabase_admin.table("hr_document_chunks").insert(
            rows[start : start + INSERT_BATCH_SIZE]
        ).execute()


@traceable(
    name="hr_onboarding.ingestion.store_chunks",
    run_type="tool",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_replace_chunks_inputs,
)
def _replace_document_chunks_traced(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    chunking_strategy: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    _replace_document_chunks(
        document_id=document_id,
        business_id=business_id,
        document_name=document_name,
        chunks=chunks,
        embeddings=embeddings,
        chunking_strategy=chunking_strategy,
        metadata=metadata,
    )


async def _process_document_bytes_impl(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    file_bytes: bytes,
    metadata: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> None:
    try:
        await asyncio.to_thread(
            _update_document_status,
            document_id,
            business_id,
            status="processing",
        )
        is_hr_policy_document = (metadata or {}).get("document_scope") == "hr_onboarding"
        text = await asyncio.to_thread(
            _extract_pdf_text_traced if is_hr_policy_document else extract_pdf_text,
            file_bytes,
        )
        chunking_strategy = (
            "langchain_recursive_character"
            if is_hr_policy_document
            else "custom_character_boundary"
        )
        chunks = (
            chunk_hr_policy_document_text(text)
            if is_hr_policy_document
            else chunk_document_text(text)
        )
        if not chunks:
            raise ValueError("No extractable text was found in this PDF.")

        embeddings = await (
            _create_embeddings_traced(chunks)
            if is_hr_policy_document
            else _create_embeddings(chunks)
        )
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding response did not match the document chunk count.")

        embedded_at = datetime.now(timezone.utc).isoformat()
        enriched_metadata = {
            **(metadata or {}),
            "embedded_at": embedded_at,
        }

        await asyncio.to_thread(
            _replace_document_chunks_traced if is_hr_policy_document else _replace_document_chunks,
            document_id=document_id,
            business_id=business_id,
            document_name=document_name,
            chunks=chunks,
            embeddings=embeddings,
            chunking_strategy=chunking_strategy,
            metadata=enriched_metadata,
        )
        await asyncio.to_thread(
            _update_document_status,
            document_id,
            business_id,
            status="ready",
            embedded_at=embedded_at,
        )
        logger.info(
            "Embedded HR document %s for business %s into %d chunks.",
            document_id,
            business_id,
            len(chunks),
        )
    except Exception as exc:
        logger.exception("Failed to embed HR document %s: %s", document_id, exc)
        try:
            await asyncio.to_thread(
                _update_document_status,
                document_id,
                business_id,
                status="failed",
                error=str(exc)[:1_000],
            )
        except Exception:
            logger.exception("Failed to persist embedding failure for document %s.", document_id)
        if raise_on_error:
            raise


@traceable(
    name="hr_onboarding.ingestion.process_document",
    run_type="chain",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_document_bytes_inputs,
)
async def _process_hr_policy_document_bytes_traced(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    file_bytes: bytes,
    metadata: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> None:
    await _process_document_bytes_impl(
        document_id=document_id,
        business_id=business_id,
        document_name=document_name,
        file_bytes=file_bytes,
        metadata=metadata,
        raise_on_error=raise_on_error,
    )


async def process_document_bytes(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    file_bytes: bytes,
    metadata: dict[str, Any] | None = None,
    raise_on_error: bool = False,
) -> None:
    if (metadata or {}).get("document_scope") == "hr_onboarding":
        await _process_hr_policy_document_bytes_traced(
            document_id=document_id,
            business_id=business_id,
            document_name=document_name,
            file_bytes=file_bytes,
            metadata=metadata,
            raise_on_error=raise_on_error,
        )
        return

    await _process_document_bytes_impl(
        document_id=document_id,
        business_id=business_id,
        document_name=document_name,
        file_bytes=file_bytes,
        metadata=metadata,
        raise_on_error=raise_on_error,
    )


async def process_stored_document(
    *,
    document_id: str,
    business_id: str,
    storage_bucket: str | None = None,
    raise_on_error: bool = False,
) -> None:
    try:
        await asyncio.to_thread(
            _update_document_status,
            document_id,
            business_id,
            status="processing",
        )
        rows = await asyncio.to_thread(
            lambda: (
                supabase_admin.table("business_documents")
                .select("id,business_id,name,file_name,file_path,storage_bucket,document_scope,category,status,created_at")
                .eq("id", document_id)
                .eq("business_id", business_id)
                .limit(1)
                .execute()
                .data
            )
        )
        if not rows:
            raise ValueError("Business document was not found.")

        document = rows[0]
        bucket = storage_bucket or document.get("storage_bucket") or DOCUMENT_BUCKET
        signed = await asyncio.to_thread(
            supabase_admin.storage.from_(bucket).create_signed_url,
            document["file_path"],
            600,
        )
        signed_url = signed.get("signedURL")
        if not signed_url:
            raise RuntimeError("Could not create a signed URL for the business document.")

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(signed_url)
            response.raise_for_status()

        await process_document_bytes(
            document_id=document_id,
            business_id=business_id,
            document_name=document.get("name") or document.get("file_name") or "Business document",
            file_bytes=response.content,
            metadata={
                "document_scope": document.get("document_scope") or "business",
                "category": document.get("category") or "General",
                "status": document.get("status") or "published",
                "storage_bucket": bucket,
                "document_created_at": document.get("created_at"),
            },
            raise_on_error=True,
        )
    except Exception as exc:
        logger.exception("Failed to process stored HR document %s: %s", document_id, exc)
        try:
            await asyncio.to_thread(
                _update_document_status,
                document_id,
                business_id,
                status="failed",
                error=str(exc)[:1_000],
            )
        except Exception:
            logger.exception("Failed to persist embedding failure for document %s.", document_id)
        if raise_on_error:
            raise


async def process_business_documents(business_id: str) -> None:
    rows = await asyncio.to_thread(
        lambda: (
            supabase_admin.table("business_documents")
            .select("id")
            .eq("business_id", business_id)
            .neq("embedding_status", "ready")
            .order("created_at")
            .execute()
            .data
            or []
        )
    )
    for row in rows:
        await process_stored_document(
            document_id=row["id"],
            business_id=business_id,
        )


@traceable(
    name="hr_onboarding.chat.create_query_embedding",
    run_type="embedding",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_query_embedding_inputs,
    process_outputs=_process_query_embedding_outputs,
)
async def _create_query_embedding(query: str) -> list[float]:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=15.0,
        max_retries=1,
    )
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
        dimensions=EMBEDDING_DIMENSIONS,
        encoding_format="float",
    )
    return response.data[0].embedding


async def retrieve_relevant_document_chunks(
    *,
    business_id: str,
    query: str,
    match_count: int = 6,
    match_threshold: float = 0.15,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=15.0,
        max_retries=1,
    )
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
        dimensions=EMBEDDING_DIMENSIONS,
        encoding_format="float",
    )
    query_embedding = response.data[0].embedding

    result = await asyncio.to_thread(
        lambda: supabase_admin.rpc(
            "match_hr_document_chunks",
            {
                "query_embedding": query_embedding,
                "match_business_id": business_id,
                "match_count": match_count,
                "match_threshold": match_threshold,
            },
        ).execute()
    )
    return result.data or []


@traceable(
    name="hr_onboarding.chat.vector_retrieval",
    run_type="retriever",
    metadata=HR_ONBOARDING_TRACE_METADATA,
    tags=HR_ONBOARDING_TRACE_TAGS,
    process_inputs=_process_retrieval_inputs,
    process_outputs=_process_retrieval_outputs,
)
async def retrieve_relevant_hr_policy_chunks(
    *,
    business_id: str,
    query: str,
    document_id: str | None = None,
    category: str | None = None,
    match_count: int = 6,
    match_threshold: float = 0.15,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []

    query_embedding = await _create_query_embedding(query)

    result = await asyncio.to_thread(
        lambda: supabase_admin.rpc(
            "match_hr_policy_document_chunks",
            {
                "query_embedding": query_embedding,
                "match_business_id": business_id,
                "match_document_id": document_id,
                "match_category": category,
                "match_count": match_count,
                "match_threshold": match_threshold,
            },
        ).execute()
    )
    return result.data or []
