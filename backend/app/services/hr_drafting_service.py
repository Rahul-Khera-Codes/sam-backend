from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import httpx
from openai import AsyncOpenAI
from pypdf import PdfReader

from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.hr import HrDraftAssistRequest

AVA_MODEL = "gpt-4o-mini"
DOCUMENT_BUCKET = "business-documents"
MAX_KNOWLEDGE_BASE_ENTRIES = 6
MAX_KNOWLEDGE_BASE_CHARS_PER_ENTRY = 1_200
MAX_DOCUMENT_SOURCES = 3
MAX_DOCUMENT_CHARS_PER_SOURCE = 2_000

FULL_DRAFT_FIELDS = [
    "summary",
    "perks",
    "responsibilities",
    "qualifications",
    "requirements_skills",
    "benefits",
]


def _fetch_business_context(business_id: str) -> dict[str, Any]:
    business_rows = (
        supabase_admin.table("businesses")
        .select("name,type")
        .eq("id", business_id)
        .limit(1)
        .execute()
        .data
    )
    branding_rows = (
        supabase_admin.table("business_branding")
        .select("mission,target_niche,key_differentiator,extra_guidelines")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
        .data
    )
    business = business_rows[0] if business_rows else {}
    branding = branding_rows[0] if branding_rows else {}
    return {
        "business_name": business.get("name") or "This company",
        "business_type": business.get("type") or "",
        "mission": branding.get("mission") or "",
        "target_niche": branding.get("target_niche") or "",
        "key_differentiator": branding.get("key_differentiator") or "",
        "extra_guidelines": branding.get("extra_guidelines") or "",
    }


def _truncate_text(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _compact_lines(data: dict[str, Any]) -> str:
    lines = []
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        pretty_key = key.replace("_", " ").title()
        lines.append(f"- {pretty_key}: {value}")
    return "\n".join(lines)


def _fetch_knowledge_base_context(business_id: str) -> list[dict[str, str]]:
    rows = (
        supabase_admin.table("knowledge_base")
        .select("title,text_content,file_name,content_type,updated_at")
        .eq("business_id", business_id)
        .order("updated_at", desc=True)
        .limit(MAX_KNOWLEDGE_BASE_ENTRIES)
        .execute()
        .data
        or []
    )
    entries: list[dict[str, str]] = []
    for row in rows:
        source_text = row.get("text_content") or row.get("file_name") or ""
        excerpt = _truncate_text(source_text, MAX_KNOWLEDGE_BASE_CHARS_PER_ENTRY)
        if not excerpt:
            continue
        entries.append(
            {
                "title": row.get("title") or row.get("file_name") or "Knowledge base entry",
                "excerpt": excerpt,
            }
        )
    return entries


async def _extract_pdf_text_from_signed_url(signed_url: str) -> str:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(signed_url)
        response.raise_for_status()

    reader = PdfReader(io.BytesIO(response.content))
    chunks: list[str] = []
    total_chars = 0
    for page in reader.pages[:12]:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        remaining = MAX_DOCUMENT_CHARS_PER_SOURCE - total_chars
        if remaining <= 0:
            break
        chunk = text[:remaining]
        chunks.append(chunk)
        total_chars += len(chunk)
    return _truncate_text("\n".join(chunks), MAX_DOCUMENT_CHARS_PER_SOURCE)


async def _fetch_document_context(business_id: str) -> list[dict[str, str]]:
    rows = (
        supabase_admin.table("business_documents")
        .select("name,description,file_path,file_name,created_at")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .limit(MAX_DOCUMENT_SOURCES)
        .execute()
        .data
        or []
    )

    entries: list[dict[str, str]] = []
    for row in rows:
        excerpt = ""
        file_path = row.get("file_path")
        if file_path:
            try:
                signed = supabase_admin.storage.from_(DOCUMENT_BUCKET).create_signed_url(file_path, 600)
                signed_url = signed.get("signedURL")
                if signed_url:
                    excerpt = await _extract_pdf_text_from_signed_url(signed_url)
            except Exception:
                excerpt = ""

        if not excerpt:
            excerpt = _truncate_text(row.get("description") or row.get("name") or row.get("file_name") or "", 300)

        if not excerpt:
            continue

        entries.append(
            {
                "title": row.get("name") or row.get("file_name") or "Business document",
                "excerpt": excerpt,
            }
        )
    return entries


def _format_named_excerpts(items: list[dict[str, str]], empty_fallback: str) -> str:
    if not items:
        return empty_fallback
    return "\n".join(f"- {item['title']}: {item['excerpt']}" for item in items)


def _system_prompt() -> str:
    return (
        "You are Ava, an AI writing assistant for HR teams. "
        "You help recruiters turn rough hiring notes into clear, candidate-friendly job postings. "
        "Write in polished business English, stay concise, and keep the structure easy to scan. "
        "Use the business documents and knowledge base as your primary grounding context whenever they are available. "
        "If those sources conflict with the job context, prioritize the explicit job context and then the business documents. "
        "Do not invent compensation, legal claims, or company-specific benefits unless context supports them. "
        "Avoid exclusionary or biased phrasing. "
        "Return valid JSON only, with no markdown fences."
    )


def _user_prompt(
    req: HrDraftAssistRequest,
    business_context: dict[str, Any],
    document_context: list[dict[str, str]],
    knowledge_base_context: list[dict[str, str]],
) -> tuple[str, list[str]]:
    job_context = req.job_context.model_dump()
    job_context.pop("business_id", None)
    requested_fields: list[str]

    if req.mode in ("generate_draft", "refine_draft"):
        requested_fields = FULL_DRAFT_FIELDS
        mode_instruction = (
            "Generate a complete first-pass job draft for the fields below."
            if req.mode == "generate_draft"
            else "Refine the existing draft content for the fields below. Preserve the role intent but make the writing clearer, stronger, and more candidate-friendly."
        )
    else:
        requested_fields = [req.target_field] if req.target_field else []
        action_instruction_map = {
            "improve": "Improve the field while keeping its intent and making the text clearer and more polished.",
            "suggest": "Suggest strong, relevant content for the field based on the role context.",
            "format_list": "Rewrite the field as a clean, scannable bullet list with concise bullets.",
        }
        mode_instruction = action_instruction_map.get(req.action or "", "Improve the requested field.")

    output_contract = {
        "generated_fields": {field: "<string>" for field in requested_fields},
        "message": "One short sentence explaining what Ava generated.",
    }

    prompt = (
        "Business context:\n"
        f"{_compact_lines(business_context)}\n\n"
        "Business document context:\n"
        f"{_format_named_excerpts(document_context, 'No uploaded business document excerpts available.')}\n\n"
        "Knowledge base context:\n"
        f"{_format_named_excerpts(knowledge_base_context, 'No knowledge base excerpts available.')}\n\n"
        "Job context:\n"
        f"{_compact_lines(job_context)}\n\n"
        f"Task: {mode_instruction}\n"
        f"Requested fields: {', '.join(requested_fields)}\n\n"
        "Field guidance:\n"
        "- summary: 2-4 sentences, candidate-friendly, clear about role impact\n"
        "- perks: concise list-like sentence or bullets of attractive role perks\n"
        "- responsibilities: bullet list, concrete day-to-day ownership\n"
        "- qualifications: bullet list, clear baseline requirements\n"
        "- requirements_skills: bullet list, practical hard/soft skill signals\n"
        "- benefits: concise list-like sentence or bullets of employee benefits\n"
        "- comments: internal drafting notes, clearer and more structured if asked\n\n"
        "Return exactly this JSON shape:\n"
        f"{json.dumps(output_contract, ensure_ascii=True)}"
    )
    return prompt, requested_fields


async def generate_hr_draft_assistance(req: HrDraftAssistRequest) -> dict[str, Any]:
    business_context = _fetch_business_context(req.business_id)
    knowledge_base_context, document_context = await asyncio.gather(
        asyncio.to_thread(_fetch_knowledge_base_context, req.business_id),
        _fetch_document_context(req.business_id),
    )
    user_prompt, requested_fields = _user_prompt(req, business_context, document_context, knowledge_base_context)

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await openai_client.chat.completions.create(
        model=AVA_MODEL,
        response_format={"type": "json_object"},
        temperature=0.5,
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    generated_fields = payload.get("generated_fields") or {}
    message = payload.get("message") or "Draft updated."

    normalized_fields = {
        field: str(generated_fields.get(field, "") or "").strip()
        for field in requested_fields
    }
    updated_fields = [field for field, value in normalized_fields.items() if value]

    return {
        "model": AVA_MODEL,
        "generated_fields": normalized_fields,
        "updated_fields": updated_fields,
        "message": message,
        "used_knowledge_base_entries": len(knowledge_base_context),
        "used_document_sources": len(document_context),
    }
