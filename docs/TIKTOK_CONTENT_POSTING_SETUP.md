# TikTok Content Posting API Setup

Related: [AIE-32](https://linear.app/ai-employees-inc/issue/AIE-32/integrations) (Integrations — LinkedIn + TikTok). This is the harder half of that ticket — unlike LinkedIn's instant self-serve approval, TikTok gates real (public) posting behind a manual audit. **Start this early — it's the critical path for the whole ticket, not the coding.**

---

## Why this is slower than LinkedIn

Any app that hasn't passed TikTok's audit is stuck in **development mode**: every video posted through it is forced to `SELF_ONLY` (private, visible only to the creator) — regardless of what privacy setting the user picks. There is no way to post publicly until the audit clears. The audit itself is a real review (not a rubber stamp) and typically takes **2–4 weeks**, often with a few rounds of feedback.

Practically: we should build the integration against the sandbox now, submit for audit as soon as the flow works end-to-end, and treat the audit wait as parallel/background time rather than something to plan the release around.

## Step 1 — Create a TikTok Developer App

1. Go to [developers.tiktok.com](https://developers.tiktok.com) → **Manage apps** → **Create an app**
2. Fill in app name, category, and a **Privacy Policy URL** (required — must be live, publicly reachable)
3. Under **Products**, add **Content Posting API**. This adds two scopes:
   - `video.upload` — pushes a video to the user's TikTok drafts (user finishes posting manually in-app)
   - `video.publish` — posts directly to the account on the user's behalf ("Direct Post") — **this is the one that requires audit approval**; TikTok checks both that the app is approved for the scope AND that the specific user authorized it during OAuth

## Step 2 — Sandbox Testing (no review needed for this part)

- Up to 5 sandboxes per app, each shareable with up to 10 real TikTok test accounts
- Run the full OAuth + upload flow against real TikTok infra — posts stay private to the test accounts, nothing goes public
- Get this fully working before requesting audit — TikTok's audit submission requires a **demo video of the complete OAuth + upload flow**, so you need a working build first

## Step 3 — Domain Verification (only if posting by URL)

- If content is pushed by direct file upload (`PULL_FROM_URL` not used), domain verification is not required
- If instead we host video files and hand TikTok a URL to fetch, the hosting domain must be verified in the developer portal (signature file at a known path, or a DNS TXT record) — unverified domains are rejected outright

## Step 4 — Submit for Audit

Required for the submission:
- Privacy Policy URL (already set in Step 1)
- A working demo video showing the full OAuth consent → upload/publish flow
- A written description of how user data is handled (what's stored, for how long, how a user disconnects)
- Confirmation the following **UX requirements** are actually implemented in the product (TikTok checks these, they aren't optional):
  - Before every post, show the creator's TikTok username + avatar so they know which account they're posting as
  - Give the user a way to disclose branded/commercial content, and to declare whether it promotes their own business or a third party's

Expect 2–4 weeks, possibly multiple feedback rounds. Once approved, `video.publish` posts go out with the user's actual chosen privacy setting instead of being forced private.

## Step 5 — Send Credentials

Once the app is created, send Rahul:
- **Client Key** and **Client Secret**
- Confirm the Privacy Policy URL used
- Whether we're doing direct file upload or `PULL_FROM_URL` (determines if domain verification is needed)

Send credentials via WhatsApp/Signal — not email.

---

## Open questions before implementation

- Do we need `video.publish` (direct post) or is `video.upload` (push to drafts, user finishes manually) acceptable for v1? Drafts-only sidesteps the audit's stricter bar somewhat but still requires *an* audit to leave `SELF_ONLY` mode for any real use — confirm with the client whether draft-only is even useful to them.
- Same token-lifetime consideration as LinkedIn: TikTok access tokens also expire and require refresh/re-auth handling — needs its own check before implementation, not assumed to mirror LinkedIn's behavior.
- Given the 2–4 week audit lead time, recommend kicking off Step 1–2 (app creation + sandbox build) immediately, independent of when LinkedIn ships, so the audit clock starts running in parallel.
