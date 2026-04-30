# SMS Two-Factor Authentication — Setup Guide

This document walks the **client / account owner** through the one-time setup needed to enable SMS-code two-factor authentication for the AI Employees app.

You only need to do this once. After it's done, all users will be able to choose between an Authenticator App and SMS codes when setting up 2FA on their account.

---

## What This Does

When 2FA is enabled, users get prompted for a 6-digit code at login. That code can come from:

- An **Authenticator App** (Google Authenticator / Authy / 1Password) — *already working today*
- **SMS** sent to their phone number — *needs the setup in this doc*

---

## What You Need Before Starting

| Item | Where to get it |
|---|---|
| Twilio account (paid, not trial) | https://www.twilio.com — sign up + add a payment method |
| A Twilio phone number you can dedicate to OTP traffic | Buy in Twilio Console → Phone Numbers → Buy |
| Your business's legal name + EIN (US) or registration number | Your incorporation paperwork |
| Business address + authorized representative name & email | Internal records |
| ~$15-20 budget for A2P 10DLC registration fees | One-time + small monthly fees |
| Supabase project admin access | https://supabase.com/dashboard |

---

## Overview of the Steps

```
1. Buy a Twilio number (dedicated for OTPs)
2. Create a Twilio Messaging Service
3. Add the number to the Messaging Service Sender Pool
4. Set the Messaging Service Use Case
5. Register for A2P 10DLC (Brand + Campaign)        ← takes 1-3 business days for approval
6. Configure Supabase Phone Auth provider           ← do this last
7. Test the flow
```

Steps 1-4 take ~15 minutes. Step 5 has a waiting period for carrier approval (1-3 business days), so plan for it. Steps 6-7 take 10 minutes once everything's approved.

---

## Step 1 — Buy a Dedicated Twilio Number for OTPs

You should NOT reuse the phone numbers already used for inbound voice / appointment SMS. A separate number for 2FA OTPs keeps things isolated and easier to monitor.

1. Go to https://console.twilio.com
2. Left sidebar → **Phone Numbers → Manage → Buy a number**
3. Country: **United States**
4. Capabilities required: ✅ **SMS** (MMS optional)
5. Pick a number you like → **Buy** (~$1.15/month)
6. Note the number — you'll add it to the Messaging Service in Step 3

---

## Step 2 — Create a Twilio Messaging Service

1. Go to https://console.twilio.com
2. Left sidebar → **Messaging → Services**
3. Click **Create Messaging Service**
4. **Friendly name**: `AI Employees - 2FA OTP` (or similar)
5. Click **Create Messaging Service**

Twilio will land you on the new service's settings.

---

## Step 3 — Add Your Number to the Sender Pool

Inside the Messaging Service:

1. Left sidebar → **Sender Pool**
2. Click **Add Senders**
3. Pick **Phone Number** as the sender type
4. Select the number you bought in Step 1
5. Click **Add Phone Numbers**

You should now see your number listed with SMS capability.

---

## Step 4 — Set the Use Case

Inside the Messaging Service:

1. Left sidebar → **Properties**
2. **Messaging Service Use Case** dropdown → choose **"Notify my users"**
   *(If you see a more specific "2FA" or "Account Verification" option, prefer that — but "Notify my users" is fine.)*
3. Click **Save**
4. **Copy the "Messaging Service SID"** (starts with `MG...`) — you'll paste this into Supabase in Step 6. Save it somewhere temporary.

---
   
## Step 5 — Register for A2P 10DLC ⚠️ CRITICAL

> **Without this step, US carriers will silently drop most of your OTP messages.** This is non-optional for production use.

A2P 10DLC has 3 parts: **Brand → Campaign → Assignment**.

### 5a — Brand Registration

Inside the Messaging Service → left sidebar → **A2P & Compliance** → click **Register for A2P**.

You'll be guided through the brand registration form. Have these ready:

| Field | What to enter |
|---|---|
| Legal Business Name | **Must match exactly** what's on your incorporation papers / IRS records |
| Business Type | LLC / Corporation / Sole Proprietor (whatever applies) |
| Business Industry | Pick the closest match (likely "Technology" or "Professional Services") |
| Business Registration ID Type | EIN (for US businesses) |
| Business Registration ID | Your 9-digit EIN |
| Address | Your registered business address (must match official records) |
| Website URL | Your company website |
| Authorized Representative Name | A real person at your company |
| Authorized Rep Email | A real, monitored email at your company domain |
| Authorized Rep Phone | A real phone number |

**Cost:** ~$4 one-time brand registration fee.

**Approval time:** Usually a few hours, sometimes up to 1 business day. You'll get an email when approved.

### 5b — Campaign Registration

After your brand is approved (or sometimes you can submit it pending), register a Campaign:

| Field | What to enter |
|---|---|
| Campaign Use Case | **2FA** (Two-Factor Authentication) — pick this exact one if available; otherwise "Account Notification" |
| Description | "Sending one-time verification codes to authenticate users logging into the AI Employees web application." |
| Sample Message #1 | `Your AI Employees verification code is 123456. Do not share this code with anyone.` |
| Sample Message #2 | `Your login code is 654321. This code expires in 5 minutes.` |
| Message Flow / How users opt in | "Users opt in by enabling SMS-based two-factor authentication in their account settings on our web application. They can opt out at any time by disabling 2FA in the same settings page or by replying STOP." |
| Embedded links? | No |
| Embedded phone numbers? | No |
| Affiliate marketing? | No |
| Age-gated content? | No |

**Cost:** ~$10 one-time campaign vetting + ~$1.50/month per phone number.

**Approval time:** 1-3 business days. You'll get an email when approved.

### 5c — Assign the Campaign to the Messaging Service

Once the campaign is approved, Twilio will usually auto-link it. If not:

1. Go back to **Messaging → Services → AI Employees - 2FA OTP**
2. **A2P & Compliance** tab → confirm the registered Campaign is linked

You're done with Twilio side after this is approved.

---

## Step 6 — Configure Supabase Phone Auth

Once Twilio shows your Campaign as **Approved** (green status), do this in Supabase:

1. Go to https://supabase.com/dashboard
2. Pick the AI Employees project
3. Left sidebar → **Authentication → Sign In / Providers**
4. Find **Phone** in the list → click to expand
5. Toggle **Enable phone provider** → ON
6. **SMS provider** dropdown → choose **Twilio**
7. Fill in:

| Field | What to enter |
|---|---|
| **Twilio Account SID** | From Twilio Console home page (top of dashboard) |
| **Twilio Auth Token** | From Twilio Console home page (click "show" to reveal) |
| **Twilio Message Service SID** | The `MG...` SID you copied in Step 4 |
| **Twilio Verify Service SID** | LEAVE BLANK — we're not using Verify |

8. Click **Save**

That's it for Supabase. The "Save" button will validate the credentials by hitting Twilio's API; if anything's wrong, you'll get a red error here.

### Optional — OTP Settings

Same screen, scroll down for OTP options:

| Setting | Recommended value |
|---|---|
| OTP Length | 6 |
| OTP Expiry | 600 seconds (10 minutes) |
| SMS Template | `Your AI Employees verification code is {{ .Code }}. Do not share this code.` |
| Allow new users to sign up via Phone | OFF (we don't want phone-only signups; users still sign up with email) |

---

## Step 7 — Test the Flow

Before announcing this to users:

1. Log into the app as a test user
2. Go to **Account Settings → Two-Factor Authentication**
3. Choose **SMS** (after the dev team ships the UI; coordinate timing)
4. Enter your phone number → request OTP
5. Confirm you receive an SMS within ~10 seconds
6. Enter the code → confirm 2FA is enabled
7. Log out → log back in → confirm you're prompted for an SMS code
8. Repeat from a phone number on a different US carrier (AT&T, Verizon, T-Mobile) to confirm delivery on each

---

## What to Expect After Setup

| Item | Note |
|---|---|
| **OTP delivery time** | 5-15 seconds normally |
| **Cost per OTP** | ~$0.0079 + 10DLC carrier fees (~$0.002-$0.005). Budget ~$0.012/OTP for safety. |
| **Failed deliveries** | Some users on number-portability situations or with carrier filters may not receive SMS. The Authenticator App option is the fallback. |
| **International numbers** | This guide covers US only. For other countries, additional 10DLC-equivalent registration may be required (varies by country). Tell the dev team if you need international support. |

---

## Troubleshooting

### "I clicked Save in Supabase and got an error"

Most common: **Auth Token wrong** (it's case-sensitive and you may have copied a space). Re-copy from Twilio Console home → paste again.

### "I'm getting OTPs but they take 30+ seconds"

Likely A2P 10DLC isn't approved yet, OR the Campaign use case isn't "2FA". OTPs flagged as 2FA traffic get prioritized; generic notifications get queued.

### "Some users don't receive OTPs at all"

Check **Twilio Console → Monitor → Logs → Messaging** to see delivery status:
- `delivered` → SMS landed on the phone
- `failed` / `undelivered` → carrier rejected (often unregistered traffic before 10DLC, or recipient opted out via STOP)
- Look at the error code → Twilio docs explain each

### "I want to switch the dedicated number later"

Supabase config → no change needed; just update the Messaging Service Sender Pool with the new number. Twilio will route through whatever's currently in the pool.

### "I need to disable SMS 2FA temporarily"

Supabase Dashboard → Authentication → Sign In/Providers → Phone → toggle OFF. Users with SMS 2FA already enrolled will lose access — they'll need to use Authenticator App or recovery codes if available.

---

## Cost Estimate (US, 100 active users with SMS 2FA)

| Item | Cost |
|---|---|
| 1 dedicated Twilio number | $1.15 / month |
| A2P 10DLC Brand registration | ~$4 one-time |
| A2P 10DLC Campaign vetting | ~$10 one-time |
| A2P 10DLC Campaign monthly fee | ~$1.50 / month per number |
| OTP cost (assume 5 logins/month/user × 100 users = 500 SMS) | ~500 × $0.012 = $6 / month |
| **Total monthly (after one-time fees)** | **~$8.65 / month** |

Numbers scale roughly linearly with user count.

---

## Who to Contact

- **Twilio support** (billing, A2P 10DLC, deliverability): https://support.twilio.com
- **Supabase support** (Phone provider config): https://supabase.com/dashboard → Help button (paid plans get faster response)
- **Your dev team** (anything code-related, UI, or "is this working?"): contact them after Steps 1-5 are done so they can build the in-app SMS 2FA flow

---

## Status Checklist

Print this and check off as you go:

- [ ] Step 1 — Bought a dedicated Twilio number for OTPs
- [ ] Step 2 — Created Messaging Service `AI Employees - 2FA OTP`
- [ ] Step 3 — Added the number to the Sender Pool
- [ ] Step 4 — Set Use Case to "Notify my users"; saved Messaging Service SID
- [ ] Step 5a — Submitted Brand Registration; received approval email
- [ ] Step 5b — Submitted Campaign with Use Case "2FA"; received approval email
- [ ] Step 5c — Confirmed Campaign is linked to the Messaging Service
- [ ] Step 6 — Plugged Account SID + Auth Token + Messaging Service SID into Supabase
- [ ] Step 7 — Tested SMS OTP delivery on at least 2 carriers
- [ ] Notified the dev team that everything is configured and tested
