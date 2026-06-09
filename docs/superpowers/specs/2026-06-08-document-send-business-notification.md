# Spec: Business Notification Email When Agent Sends a PDF

**Date:** 2026-06-08  
**Requested by:** Sam Maisuria (message 2026-06-08 5:14 PM)  
**Status:** Ready to implement

---

## Problem

When the AI agent emails a PDF document to a customer, the business has no record of who requested it or how to follow up. The business email is not notified.

---

## Desired Behaviour

After the agent successfully sends a PDF to a customer, the connected business Gmail account also receives a notification email **sent to itself** containing:
- Customer name
- Customer email
- Customer phone
- Document name sent
- Date/time of the call

This is a "self-email" — the business Gmail sends to its own address. Same pattern as staff booking notifications.

---

## Flow

```
Agent calls email_document(document_name, customer_email)
  ↓
Sends PDF to customer ✅ (existing)
  ↓
Sends notification to sender_email (the business Gmail itself):
  "A document was sent to [customer name] ([customer_email])"
  with customer phone and document name included
```

---

## Implementation

### 1. `agent/gmail_helpers.py` — new function `_gmail_send_document_notification`

```python
async def _gmail_send_document_notification(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    document_name: str,
    sent_at: str,          # human-readable datetime string
) -> None:
```

- Gets access token via `_gmail_get_valid_token` (same as all other send functions)
- Sends to `sender_email` (the Gmail account itself — self-email)
- Subject: `"Document Sent: {document_name} → {customer_name}"`
- Body: plain + simple HTML with customer details

### 2. `agent/agent.py` — `email_document` tool

After the existing `send_email_with_attachment()` success, call:
```python
await _gmail_send_document_notification(
    supabase=self._supabase,
    business_id=self._business_id,
    location_id=self._location_id,
    business_name=self._business_name or "",
    customer_name=customer_name,
    customer_email=customer_email,
    customer_phone=self._caller_phone or "",
    document_name=doc["name"],
    sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
)
```

Best-effort — failure logs a warning but does NOT affect the customer-facing result.

---

## Email Content

**Subject:** `Document Sent: Information Package → John Smith`

**Body:**
```
Hi [Business Name],

A document was sent to a customer during a call.

Document:   Information Package
Customer:   John Smith
Email:      john@example.com
Phone:      +1 416 555 0123
Sent at:    2026-06-08 14:32 UTC

You can follow up with this customer directly.

— AI Employees
```

---

## What does NOT change
- The PDF send to the customer — unchanged
- The `email_document` return value to the agent — unchanged  
- No new DB tables or columns needed
- Notification failure does not block the customer email
