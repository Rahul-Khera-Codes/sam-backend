from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from openai import AsyncOpenAI
from pypdf import PdfReader

from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

DOCUMENT_BUCKET = "business-documents"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_DOCUMENT_TEXT_CHARS = 240_000
CHUNK_SIZE_CHARS = 2_400
CHUNK_OVERLAP_CHARS = 300
EMBEDDING_BATCH_SIZE = 32
INSERT_BATCH_SIZE = 20


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


def chunk_document_text(text: str) -> list[str]:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
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


async def _create_embeddings(chunks: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0,
        max_retries=2,
    )
    embeddings: list[list[float]] = []

    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )
        embeddings.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))

    return embeddings


def _replace_document_chunks(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    (
        supabase_admin.table("hr_document_chunks")
        .delete()
        .eq("document_id", document_id)
        .eq("business_id", business_id)
        .execute()
    )

    rows = [
        {
            "business_id": business_id,
            "document_id": document_id,
            "chunk_index": index,
            "content": content,
            "embedding": embedding,
            "embedding_model": EMBEDDING_MODEL,
            "metadata": {"document_name": document_name},
        }
        for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    ]

    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        supabase_admin.table("hr_document_chunks").insert(
            rows[start : start + INSERT_BATCH_SIZE]
        ).execute()


async def process_document_bytes(
    *,
    document_id: str,
    business_id: str,
    document_name: str,
    file_bytes: bytes,
    raise_on_error: bool = False,
) -> None:
    try:
        await asyncio.to_thread(
            _update_document_status,
            document_id,
            business_id,
            status="processing",
        )
        text = await asyncio.to_thread(extract_pdf_text, file_bytes)
        chunks = chunk_document_text(text)
        if not chunks:
            raise ValueError("No extractable text was found in this PDF.")

        embeddings = await _create_embeddings(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding response did not match the document chunk count.")

        await asyncio.to_thread(
            _replace_document_chunks,
            document_id=document_id,
            business_id=business_id,
            document_name=document_name,
            chunks=chunks,
            embeddings=embeddings,
        )
        await asyncio.to_thread(
            _update_document_status,
            document_id,
            business_id,
            status="ready",
            embedded_at=datetime.now(timezone.utc).isoformat(),
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


async def process_stored_document(
    *,
    document_id: str,
    business_id: str,
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
                .select("id,business_id,name,file_name,file_path")
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
        signed = await asyncio.to_thread(
            supabase_admin.storage.from_(DOCUMENT_BUCKET).create_signed_url,
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
