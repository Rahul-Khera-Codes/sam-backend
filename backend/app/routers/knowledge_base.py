"""
Knowledge Base router — website scraping endpoint.
POST /knowledge-base/scrape: crawl a business website via Jina AI Reader,
extract 8 structured sections via GPT-4o, write to knowledge_base table.
"""
import ipaddress
import logging
import socket
from typing import Optional
import httpx
import defusedxml.ElementTree as ET
from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter()

JINA_BASE = "https://r.jina.ai/"
MAX_PAGES = 15
PAGE_TIMEOUT = 30.0

SECTIONS = [
    "Business Overview",
    "Services / Products",
    "FAQ Database",
    "Contact Information",
    "Sales Information",
    "Customer Handling Rules",
    "AI Voice Agent Training",
    "Important Policies",
]

EXTRACTION_PROMPT = """You are extracting structured information from a business website to train an AI voice agent.

Given the following website content, extract and organize information into these exact 8 sections.
Return a JSON object with exactly these keys. If a section has no relevant content, return an empty string for that key.

Sections:
1. "Business Overview" - Company name, what they do, main services, unique selling points, history
2. "Services / Products" - For each service: name, description, benefits, pricing if available, common questions
3. "FAQ Database" - All FAQs: general, pricing, service, policies, booking, refund/cancellation
4. "Contact Information" - Phone numbers, emails, address, hours of operation, social media links
5. "Sales Information" - Promotions, guarantees, competitive advantages, testimonials, payment options
6. "Customer Handling Rules" - How appointments are booked, lead qualification, escalation process, when to transfer to human
7. "AI Voice Agent Training" - Greeting scripts, objection handling, call flows, booking scripts, upsell scripts
8. "Important Policies" - Refunds, cancellations, service limitations, legal disclaimers

Format rules:
- Use bullet points
- Be concise and structured
- Remove marketing fluff
- Make information easy for an AI to retrieve quickly

Return ONLY valid JSON with these exact 8 keys."""


class ScrapeRequest(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    url: Optional[str] = None


class ScrapeResponse(BaseModel):
    entries_created: int
    skipped_empty: int


def _validate_url_is_public(url: str) -> None:
    """
    Resolve the hostname in *url* and raise HTTP 400 if it maps to any
    private / reserved IP range (SSRF prevention).

    Only call this for URLs we fetch **directly** with httpx.
    Jina AI Reader URLs (r.jina.ai/…) do not need this check — we fetch
    the Jina service, not the target host directly.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: could not parse hostname.")

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"URL hostname could not be resolved: {exc}")

    for family, _type, _proto, _canonname, sockaddr in results:
        raw_ip = sockaddr[0]
        try:
            addr = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue

        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail="URL resolves to a private/internal address",
            )


def _same_domain(base: str, href: str) -> bool:
    """Check if href is on the same domain as base."""
    try:
        from urllib.parse import urlparse
        base_host = urlparse(base).netloc
        href_host = urlparse(href).netloc
        return href_host == base_host or href_host == ""
    except Exception:
        return False


def _normalize_url(base: str, href: str) -> Optional[str]:
    """Resolve relative URLs against base."""
    try:
        from urllib.parse import urljoin, urlparse
        resolved = urljoin(base, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            return None
        # Strip fragments
        return parsed._replace(fragment="").geturl()
    except Exception:
        return None


async def _fetch_via_jina(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Fetch a URL via Jina AI Reader and return clean markdown text."""
    try:
        r = await client.get(
            f"{JINA_BASE}{url}",
            headers={"Accept": "text/plain", "User-Agent": "Mozilla/5.0"},
            timeout=PAGE_TIMEOUT,
        )
        if r.status_code == 200 and len(r.text) > 100:
            return r.text
        logger.warning("Jina fetch returned %s for %s", r.status_code, url)
    except Exception as e:
        logger.warning("Jina fetch failed for %s: %s", url, e)
    return None


async def _get_page_urls(base_url: str, client: httpx.AsyncClient) -> list[str]:
    """
    Discover subpage URLs.
    1. Try sitemap.xml — parse <loc> tags
    2. Fall back to base URL only
    """
    from urllib.parse import urljoin, urlparse
    urls = [base_url]

    # Try sitemap
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    try:
        _validate_url_is_public(sitemap_url)
        r = await client.get(sitemap_url, timeout=10.0, follow_redirects=False)
        if r.status_code == 200 and "<?xml" in r.text[:100]:
            try:
                root = ET.fromstring(r.text)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                locs = root.findall(".//sm:loc", ns)
                if not locs:
                    # Try without namespace
                    locs = root.findall(".//loc")
                base_host = urlparse(base_url).netloc
                for loc in locs:
                    loc_url = (loc.text or "").strip()
                    if loc_url and urlparse(loc_url).netloc == base_host:
                        try:
                            _validate_url_is_public(loc_url)
                        except HTTPException:
                            logger.warning("Skipping sitemap URL that resolves to private address: %s", loc_url)
                            continue
                        if loc_url not in urls:
                            urls.append(loc_url)
                logger.info("Sitemap found %d URLs", len(urls))
                return urls[:MAX_PAGES]
            except ET.ParseError:
                pass
    except Exception as e:
        logger.info("No sitemap at %s: %s", sitemap_url, e)

    # No sitemap — extract links from main page markdown via Jina
    main_content = await _fetch_via_jina(base_url, client)
    if main_content:
        import re
        # Extract markdown links [text](url)
        hrefs = re.findall(r'\[(?:[^\]]*)\]\((https?://[^)]+)\)', main_content)
        for href in hrefs:
            normalized = _normalize_url(base_url, href)
            if normalized and _same_domain(base_url, normalized) and normalized not in urls:
                urls.append(normalized)
                if len(urls) >= MAX_PAGES:
                    break

    return urls[:MAX_PAGES]


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_website(
    req: ScrapeRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, req.business_id)

    # Resolve URL
    url = req.url
    if not url:
        biz_row = (
            supabase_admin.table("businesses")
            .select("website")
            .eq("id", req.business_id)
            .limit(1)
            .execute()
        )
        url = (biz_row.data[0].get("website") or "").strip() if biz_row.data else ""

    if not url:
        raise HTTPException(status_code=400, detail="No website URL configured. Add it in Company Info.")

    # Ensure URL has scheme
    if not url.startswith("http"):
        url = "https://" + url

    # Validate the URL resolves to a public address before any network fetch (SSRF prevention)
    _validate_url_is_public(url)

    # If custom URL provided, save it to businesses.website
    if req.url:
        supabase_admin.table("businesses").update({"website": url}).eq("id", req.business_id).execute()

    # Crawl
    async with httpx.AsyncClient(follow_redirects=True) as client:
        page_urls = await _get_page_urls(url, client)
        logger.info("Scraping %d pages for business %s", len(page_urls), req.business_id)

        pages_text = []
        for page_url in page_urls:
            content = await _fetch_via_jina(page_url, client)
            if content:
                pages_text.append(content)

    if not pages_text:
        raise HTTPException(status_code=400, detail="Could not fetch any content from the website.")

    combined_text = "\n\n---\n\n".join(pages_text)
    # Truncate to avoid GPT token limits (~100k chars ≈ ~25k tokens)
    if len(combined_text) > 100_000:
        combined_text = combined_text[:100_000]

    # Extract via GPT-4o
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": f"Website content:\n\n{combined_text}"},
            ],
            temperature=0,
        )
        import json
        extracted = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error("GPT-4o extraction failed: %s", e)
        raise HTTPException(status_code=502, detail=f"AI extraction failed: {e}")

    # Delete existing [Website] entries for this business+location
    delete_q = (
        supabase_admin.table("knowledge_base")
        .delete()
        .eq("business_id", req.business_id)
        .like("title", "[Website]%")
    )
    if req.location_id:
        delete_q = delete_q.eq("location_id", req.location_id)
    else:
        delete_q = delete_q.is_("location_id", "null")
    delete_q.execute()

    # Insert new entries
    entries_created = 0
    skipped_empty = 0

    for section in SECTIONS:
        content = extracted.get(section, "").strip()
        if not content:
            skipped_empty += 1
            continue

        row: dict = {
            "business_id": req.business_id,
            "title": f"[Website] {section}",
            "content_type": "text",
            "text_content": content,
        }
        if req.location_id:
            row["location_id"] = req.location_id

        supabase_admin.table("knowledge_base").insert(row).execute()
        entries_created += 1

    logger.info(
        "Website scrape complete for business %s: %d entries created, %d skipped",
        req.business_id, entries_created, skipped_empty,
    )
    return ScrapeResponse(entries_created=entries_created, skipped_empty=skipped_empty)
