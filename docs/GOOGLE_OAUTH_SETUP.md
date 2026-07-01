# Google OAuth Setup — Gmail & Calendar Integration

This sets up the Google credentials for Gmail sending and Google Calendar sync inside the app.

---

## Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown (top left) → **New Project**
3. Name it `aiemployeesinc-prod` → **Create**

## Step 2 — Enable APIs

1. **APIs & Services → Library**
2. Search and enable:
   - **Gmail API**
   - **Google Calendar API**

## Step 3 — OAuth Consent Screen

1. **APIs & Services → OAuth consent screen**
2. Select **External** → **Create**
3. Fill in:
   - **App name:** AI Employees Inc.
   - **User support email:** your email
   - **Authorised domain:** `aiemployeesinc.com`
   - **Developer contact email:** your email
4. **Save and Continue**
5. On Scopes → **Add or Remove Scopes**, add:
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/calendar.events`
6. **Save and Continue** → **Back to Dashboard**
7. Click **Publish App** → Confirm (status: In production)

## Step 4 — Create OAuth Credentials

1. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**
2. Application type: **Web application**
3. Name: `AI Employees Portal`
4. **Authorised JavaScript origins:**
   ```
   https://portal.aiemployeesinc.com
   ```
5. **Authorised redirect URIs:**
   ```
   https://portal.aiemployeesinc.com/integrations/google/callback
   https://portal.aiemployeesinc.com/integrations/gmail/callback
   ```
6. Click **Create**

## Step 5 — Send Credentials

Once created, send Rahul:
- **Client ID**
- **Client Secret**

Send these securely via WhatsApp or Signal — do not email them.
