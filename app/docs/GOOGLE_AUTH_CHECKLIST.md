# Google Auth Checklist — Fix 403 / Calendar Issues

## 1. Enable APIs in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → your project
2. **APIs & Services** → **Library**
3. Enable:
   - **Google Calendar API**
   - **Gmail API** (if using email)

## 2. Add Scopes to OAuth Consent Screen

1. **APIs & Services** → **OAuth consent screen**
2. Click **Edit app**
3. Under **Scopes** → **Add or remove scopes**
4. Add:
   - `https://www.googleapis.com/auth/calendar` (Calendar read/write)
   - `https://www.googleapis.com/auth/gmail.modify` (Gmail)
   - `email`, `openid`
5. Save

## 3. Add Test Users (if app is in Testing)

1. **OAuth consent screen** → **Test users**
2. Add the Google account you're connecting with
3. Only test users can connect while the app is in "Testing" mode

## 4. Verify Redirect URI

- In **Credentials** → your OAuth client → **Authorized redirect URIs**
- Must exactly match `GOOGLE_REDIRECT_URI` in `.env`
- For ngrok: `https://YOUR-NGROK-URL/auth/google/callback`

## 5. Reconnect After Changes

If you changed scopes or consent screen:

1. Revoke the app: [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
2. In WhatsApp, tap **Connect Google** again and go through the flow
3. This ensures you get a fresh token with the new scopes

## 6. Run the Test Script

```bash
# Get user_id from DB first
python scripts/test_google_auth.py <user_id>
```

This tests: token presence → fetch events → create event.

## Common 403 Causes

| Cause | Fix |
|-------|-----|
| Calendar API not enabled | Enable in API Library |
| Scopes not on consent screen | Add scopes in OAuth consent screen |
| App in Testing, user not added | Add your email as test user |
| Token expired (now auto-refreshed) | Reconnect once; refresh handles future expiry |
