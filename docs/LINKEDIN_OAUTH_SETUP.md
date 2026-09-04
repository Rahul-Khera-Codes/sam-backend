# LinkedIn OAuth Setup — Share on LinkedIn (personal profile posting)

Scope: posting on behalf of a **personal member profile** (not a Company Page). This uses LinkedIn's self-serve products — no manual LinkedIn review needed, unlike Company Page posting (Marketing Developer Platform).

Related: [AIE-32](https://linear.app/ai-employees-inc/issue/AIE-32/integrations) (Integrations — LinkedIn + TikTok). This doc covers LinkedIn only.

---

## Step 1 — Create a LinkedIn Developer App

1. Go to [developer.linkedin.com/apps](https://developer.linkedin.com/apps)
2. Click **Create app**
3. Fill in:
   - **App name:** `AI Employees Inc.`
   - **LinkedIn Page:** you must link an existing LinkedIn Company Page you admin (LinkedIn requires this even for personal-profile posting — it's just an app-ownership check, the Page itself won't be posted to)
   - **App logo:** upload the AI Employees logo
   - **Legal agreement:** accept
4. Click **Create app**

## Step 2 — Add Products

On the app's **Products** tab, request:

1. **Sign In with LinkedIn using OpenID Connect** — auto-approved instantly. Grants `openid`, `profile`, `email` scopes.
2. **Share on LinkedIn** — auto-approved instantly. Grants `w_member_social` scope (post/comment/like on behalf of the authenticated member).

Both are self-serve — no waiting on LinkedIn review.

## Step 3 — Auth Settings

On the app's **Auth** tab:

1. Note the **Client ID** and **Client Secret** (click "Show" for the secret)
2. Under **Authorized redirect URLs for your app**, add:
   ```
   https://portal.aiemployeesinc.com/integrations/marketing/linkedin/callback
   ```
   (Note the `/marketing/` segment — this doc previously omitted it, which caused a
   redirect_uri mismatch when the real app was created. See
   `docs/features/marketing-platform-integrations.md` for what actually shipped and the
   Company Page follow-up.)
3. Confirm the **OAuth 2.0 scopes** section shows: `openid`, `profile`, `email`, `w_member_social`

## Step 4 — Send Credentials

Once created, send Rahul:
- **Client ID**
- **Client Secret**
- Confirm which LinkedIn Company Page was used to verify the app (for our records, not for posting)

Send these securely via WhatsApp or Signal — do not email them.

---

## Integration notes (for implementation — read before building)

- **Auth flow:** standard 3-legged OAuth 2.0 authorization code flow. Authorize URL: `https://www.linkedin.com/oauth/v2/authorization`, token URL: `https://www.linkedin.com/oauth/v2/accessToken`.
- **Posting endpoint:** `POST https://api.linkedin.com/rest/posts` (versioned REST API — requires `LinkedIn-Version` and `X-Restli-Protocol-Version: 2.0.0` headers). The member's LinkedIn URN (`urn:li:person:{id}`) comes from the OpenID `/v2/userinfo` (or ID token `sub` claim) after login.
- **⚠️ No refresh tokens on this product tier.** Standard `w_member_social` access tokens last **60 days** and LinkedIn does **not** issue a `refresh_token` for non-Marketing-Developer-Platform apps — the only way to get a new token is to send the member through the LinkedIn login/consent screen again. This means:
  - We need to store `expires_at` per connected LinkedIn account and proactively prompt the user to reconnect before/at expiry (not silently fail on their next scheduled post).
  - Any "schedule a post 90 days out" UX needs a re-auth gate, since the token likely won't survive that long.
  - This is a product decision to confirm before implementation — flagging per the Phase 2 spec step.
- **Rate limits:** 150 requests/member/day, 100,000/app/day, reset daily at UTC.

## Open question before implementation

TikTok (also in AIE-32) has its own separate app-review process (Content Posting API requires app audit before it leaves sandbox mode) — that's a bigger lift and should be scoped separately from LinkedIn. Confirm with the client whether TikTok is needed in this same milestone or can follow later.
