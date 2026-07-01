# Spec: Website → Knowledge Base Scraper

**Date:** 2026-06-20
**Requested by:** Sam Maisuria (morning meeting, Jun 20)
**Status:** Ready for implementation

---

## Problem

Businesses already have all their information on their website. Manually re-entering it into the Knowledge Base is tedious and incomplete. Owners need a one-click way to point the system at their website and have the KB populated automatically with structured, agent-ready entries.

Currently the KB has two input methods:
1. File upload (PDF/DOC)
2. Manual text entry

This adds a third: **URL → auto-scrape → structured KB entries.**

---

## Desired Behaviour

1. Owner opens Business Settings → Knowledge Base tab
2. Sees a "Generate from Website" button
3. If `businesses.website` is already set → button shows the URL and is immediately clickable
4. If `businesses.website` is not set → clicking the button opens a small dialog to enter the URL; saving it writes to `businesses.website` first, then triggers the scrape
5. Scrape runs: fetches website content, extracts 8 structured sections via GPT-4o
6. Each section becomes a separate `knowledge_base` row titled `[Website] {Section Name}`
7. On re-run: existing `[Website]` entries are deleted first, then replaced with fresh ones
8. Owner sees 8 new entries appear in the saved entries list

---

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| One entry or 8? | One entry per section | Each section is distinct; owner can delete/edit individually; agent retrieves specific info |
| Re-run behaviour | Delete `[Website]` entries, insert fresh | Prevents stale/duplicate entries when website content changes |
| How to identify scrape entries | Title prefix `[Website]` | No migration needed; agent reads them as `content_type = "text"` automatically |
| Scraping method | Jina AI Reader (`r.jina.ai`) | Handles JS-rendered sites; returns clean markdown; no new dependencies; tested on autocaller.io ✅ |
| Page discovery | Try `/sitemap.xml` first → fall back to main page only | Most SMB sites have sitemaps; single-page sites work fine with just the homepage |
| Max pages | 15 | Prevents runaway scraping on large sites |

---

## Extraction Sections (8 total)

GPT-4o extracts and returns JSON with these keys. Each becomes one KB entry:

| KB Title | Content |
|---|---|
| `[Website] Business Overview` | Company name, what they do, services summary, USPs, history |
| `[Website] Services / Products` | Per service: name, description, benefits, pricing, common questions |
| `[Website] FAQ Database` | All FAQs — general, pricing, policies, booking, refund/cancellation |
| `[Website] Contact Information` | Phones, emails, address, hours, social media links |
| `[Website] Sales Information` | Promotions, guarantees, competitive advantages, testimonials, payment options |
| `[Website] Customer Handling Rules` | Booking process, lead qualification, escalation, when to transfer to human |
| `[Website] AI Voice Agent Training` | Greeting scripts, objection handling, call flows, booking scripts, upsell scripts |
| `[Website] Important Policies` | Refunds, cancellations, service limitations, legal disclaimers |

If a section has no content (website doesn't mention it), GPT returns an empty string and that entry is skipped — no empty KB rows.

---

## Files to Change

### 1. Backend — new router

**File:** `backend/app/routers/knowledge_base.py` *(new file)*

**Endpoint:** `POST /knowledge-base/scrape`

**Request body:**
```python
class ScrapeRequest(BaseModel):
    business_id: str
    location_id: str | None = None
    url: str | None = None  # optional — reads businesses.website if not provided
```

**Logic:**
```
1. Auth: verify_business_access(user_id, business_id)
2. Resolve URL:
   - If url in body → use it + update businesses.website
   - Else → read businesses.website from DB
   - If still empty → 400 "No website URL configured"
3. Crawl (async):
   a. Try GET {url}/sitemap.xml
      → If valid XML: parse <loc> tags, collect up to 15 URLs (same domain only)
      → If not XML (e.g. React SPA returns HTML): use [url] only
   b. For each URL: GET https://r.jina.ai/{url} with 30s timeout
   c. Combine all markdown text
4. GPT-4o extraction:
   - Model: gpt-4o
   - System: "Extract structured information..."
   - User: combined markdown + Sam's 8-section prompt
   - response_format: { type: "json_object" }
   - Returns: { "Business Overview": "...", "Services / Products": "...", ... }
5. DB write:
   a. DELETE FROM knowledge_base
      WHERE business_id = ? AND title LIKE '[Website]%'
      AND (location_id = ? OR location_id IS NULL)
   b. INSERT one row per non-empty section
6. Return: { entries_created: N, entries: [...] }
```

**Error handling:**
- Jina returns non-200 → skip that page, continue with others
- GPT fails → 502 with message
- All pages fail → 400 "Could not fetch website content"

---

### 2. Backend — register router

**File:** `backend/app/main.py`

```python
from app.routers import knowledge_base
app.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["knowledge-base"])
```

---

### 3. Frontend API

**File:** `ai-employees-app/src/lib/voiceAgentApi.ts`

```typescript
export const scrapeWebsiteToKB = async (
  businessId: string,
  locationId?: string | null,
  url?: string,
): Promise<{ entries_created: number }> => { ... }
```

---

### 4. Frontend — KB tab UI

**File:** `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx`

**New state:**
```typescript
const [isScraping, setIsScraping] = useState(false);
const [scrapeDialogOpen, setScrapeDialogOpen] = useState(false);
const [scrapeUrlInput, setScrapeUrlInput] = useState("");
```

**New UI block** — added above the file upload section in the Knowledge Base tab:

```
┌─────────────────────────────────────────────────────┐
│  Generate from Website                               │
│  Automatically populate your knowledge base         │
│  by scraping your website.                          │
│                                                     │
│  [website url shown here if set]                    │
│                                                     │
│  [ Generate from Website ▶ ]                        │
│   → if no website: opens dialog                     │
│   → if website set: runs scrape directly            │
└─────────────────────────────────────────────────────┘
```

**Dialog (shown when no website URL set):**
```
┌─────────────────────────────────────┐
│  Enter Your Website URL             │
│                                     │
│  [https://yourbusiness.com      ]   │
│                                     │
│  This will also save the URL to     │
│  your Company Info.                 │
│                                     │
│  [Cancel]  [Save & Generate]        │
└─────────────────────────────────────┘
```

**Loading state:**
- Button disabled + spinner + "Generating..." text
- Small note: "This may take 20–30 seconds"

**Success:**
- Toast: "8 entries added from your website"
- Re-fetch KB entries — new `[Website] ...` entries appear in the saved list

**On re-run:**
- No confirmation dialog — just runs and replaces silently (same as saving any form)
- Toast on completion confirms how many entries were created

---

## What Does NOT Change

- Agent `_fetch_knowledge_base_for_location` — already fetches `content_type = "text"` which includes `[Website]` entries automatically. No agent changes.
- Manual text entries — unaffected by scrape (only `[Website]` titled rows are deleted on re-run)
- File upload entries — unaffected
- `knowledge_base` table schema — no migration needed

---

## Known Limitations

- **JS-rendered SPAs with no content in HTML** — Jina handles most cases (tested). Deep SPAs that load everything via API calls may return thin content.
- **Bot-blocked sites** — Jina will get a 403/captcha page; the extracted content will be minimal. Show a warning toast if extracted text is < 500 chars.
- **Sites with no sitemap** — falls back to homepage only. Multi-page content on subpages won't be scraped unless linked from the homepage markdown.
- **Large sites** — hard-capped at 15 pages. Content beyond that is not extracted.

---

## Testing

1. Set a business website URL in Company Info (or use the dialog)
2. Click "Generate from Website"
3. Wait ~20–30 seconds
4. Verify 8 entries appear in KB list, each titled `[Website] {Section}`
5. Verify entries have meaningful content (not empty)
6. Run scrape again → verify old `[Website]` entries are replaced, not duplicated
7. Verify agent reads the new entries on next call (check prompt in logs)
8. Test with no website set → verify dialog appears → enter URL → scrape runs → URL saved in Company Info

---

## Summary of Changes

| File | Change |
|---|---|
| `backend/app/routers/knowledge_base.py` | New file — scrape endpoint |
| `backend/app/main.py` | Register knowledge_base router |
| `ai-employees-app/src/lib/voiceAgentApi.ts` | Add `scrapeWebsiteToKB` function |
| `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx` | Generate from Website button + dialog + loading state |
