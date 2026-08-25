Subject: Access needed to connect LinkedIn & TikTok posting (AIE-32)

Hi Sam,

To build the LinkedIn and TikTok posting integration, both platforms require the connection to be set up from an account that officially owns the AI Employees Inc. page/profile — so a few of these steps need to happen on your end. I've broken down exactly what to click and what to send back once each one is done. Neither platform charges anything for this — it's just a verification step both require.

Quick heads-up on timing: **LinkedIn is instant** — a few minutes of clicking. **TikTok requires their team to manually review the app before it can post publicly**, which typically takes 1–4 weeks. I've included every step below, including the review submission itself, so you can run the whole thing start to finish without waiting on me. The review part involves a couple of technical steps (below) — if you don't have someone on hand for those, flag it and I'll jump on a call.

---

## Part 1 — LinkedIn (quick, no waiting)

1. Go to **developer.linkedin.com/apps** and log in with the LinkedIn account that manages our Company Page.
2. Click **Create app**.
3. Fill in:
   - App name: `AI Employees Inc.`
   - LinkedIn Page: select our official AI Employees Inc. Company Page
   - Upload our logo
   - Accept the legal terms → **Create app**
4. On the **Products** tab of the new app, click **Request access** on these two (both approve instantly, no waiting):
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
5. On the **Auth** tab:
   - Copy the **Client ID**
   - Click "Show" next to **Client Secret** and copy that too
   - Under "Authorized redirect URLs," add: `https://portal.aiemployeesinc.com/integrations/linkedin/callback`

**Please send back:** Client ID, Client Secret, and confirmation of which Company Page you linked.

---

## Part 2 — TikTok (start this one today — full process, including the review, below)

### 2.1 Create the app

1. Go to **developers.tiktok.com**, log in with our business TikTok account, and go to **Manage apps → Create an app**.
2. Fill in the app name and category. It will ask for a **Privacy Policy URL** — use our published privacy policy page.
3. Under **Products**, add **Content Posting API**.
4. On the app's dashboard, copy the **Client Key** and **Client Secret** — send these to me now (step below), you'll also need them for testing in 2.2.
5. Also on the app dashboard, add a **Redirect URI**. Use: `https://portal.aiemployeesinc.com/integrations/tiktok/callback` — this page doesn't need to exist yet for testing; you'll just copy a code out of the browser's address bar after logging in (step 2.2 explains exactly how).

### 2.2 Get sandbox test accounts

1. In the app dashboard, find the **Sandbox** section and add up to 10 **Target TikTok users** for testing — these can be your own TikTok account or a spare one. Testing here never posts anything publicly, no matter what privacy setting you pick.

### 2.3 Run through the login + posting flow once (this becomes your demo recording)

**Start screen-recording your screen before this step** — TikTok's review requires a short video showing this entire flow, so you only need to do it once and save the recording.

1. **Log in as the test user:** paste this into your browser, swapping in your own Client Key and Redirect URI:
   ```
   https://www.tiktok.com/v2/auth/authorize?client_key=YOUR_CLIENT_KEY&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri=YOUR_REDIRECT_URI&state=test123
   ```
   Log in with the sandbox test account and approve access. TikTok will redirect you to the redirect URI with `?code=...` in the address bar (the page itself may show an error since nothing's hosted there yet — that's fine, you only need the `code` value from the URL).

2. **Exchange that code for an access token.** This step needs a tool that can send a web request — either [Postman](https://www.postman.com/downloads/) (free, has a simple form-based interface, no coding) or a developer can run this one line for you:
   ```
   curl -X POST https://open.tiktokapis.com/v2/oauth/token/ \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "client_key=YOUR_CLIENT_KEY&client_secret=YOUR_CLIENT_SECRET&code=THE_CODE_FROM_STEP_1&grant_type=authorization_code&redirect_uri=YOUR_REDIRECT_URI"
   ```
   The response includes an `access_token` — copy it.

3. **Upload and publish a short test video** (any short mp4 on your computer works):
   ```
   curl -X POST https://open.tiktokapis.com/v2/post/publish/video/init/ \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json; charset=UTF-8" \
     -d '{
       "post_info": {"title": "Test post", "privacy_level": "SELF_ONLY"},
       "source_info": {"source": "FILE_UPLOAD", "video_size": YOUR_VIDEO_SIZE_IN_BYTES, "chunk_size": YOUR_VIDEO_SIZE_IN_BYTES, "total_chunk_count": 1}
     }'
   ```
   This returns a `publish_id` and an `upload_url`. Upload the actual video file to that `upload_url`:
   ```
   curl --location --request PUT 'THE_UPLOAD_URL_FROM_ABOVE' \
     --header 'Content-Range: bytes 0-YOUR_VIDEO_SIZE_MINUS_1/YOUR_VIDEO_SIZE' \
     --header 'Content-Type: video/mp4' \
     --data-binary '@/path/to/your/test-video.mp4'
   ```
4. **Confirm it worked** by checking status (optional but good for the recording):
   ```
   curl -X POST https://open.tiktokapis.com/v2/post/publish/status/fetch/ \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json; charset=UTF-8" \
     -d '{"publish_id": "THE_PUBLISH_ID_FROM_ABOVE"}'
   ```
   **Stop the screen recording here.** You now have your demo video (steps 1–4) and a private test post on the sandbox account.

### 2.4 Submit for TikTok's review

1. Back in the TikTok developer portal, open the app → **App Review** (or "Submit for review") section.
2. For each product/scope requested (`user.info.basic`, `video.upload`, `video.publish`), write a short plain description of how it's used — e.g. *"Used to let AI Employees Inc. customers connect their TikTok account and publish marketing videos created in our platform on their behalf, with their explicit action each time."*
3. Describe how user data is handled — e.g. *"We store the connected account's access/refresh tokens to publish on the user's behalf; we do not store TikTok video content beyond what's needed to complete the post; users can disconnect at any time."*
4. Upload the demo recording from step 2.3 (TikTok accepts up to 5 videos, 50MB each).
5. Confirm the Privacy Policy URL is correct.
6. Click **Submit for review**.
7. TikTok typically responds in **1–4 weeks**, sometimes with follow-up questions — reply to those directly in the portal. Once approved, posts stop being forced private and use whatever privacy setting the user actually picked.

**Please send back now:** Client Key, Client Secret, and the Privacy Policy URL you used.
**Please let me know once you've submitted for review in step 2.4**, and forward any questions TikTok's review team sends back — some are technical and I may need to help you answer them.

---

## Summary — what I need from you

| Platform | What to send | Turnaround |
|---|---|---|
| LinkedIn | Client ID, Client Secret, Page used | A few minutes |
| TikTok | Client Key, Client Secret, Privacy Policy URL, + confirmation once you've submitted for review | A couple hours to get through testing + submission; TikTok's own review then takes 1–4 weeks |

Please send the Client ID/Secret and Client Key/Secret over WhatsApp or Signal rather than email, just to keep them off email threads.

Let me know if you hit any snag on either setup and I'll hop on a call to walk through it.

Thanks,
Rahul
