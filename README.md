# KZTTS v0.3

Cloud TTS for streams. Twitch + Kick + YouTube feed one OBS Browser Source.

## Railway variables

- `APP_URL`
- `SESSION_SECRET`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `KICK_CLIENT_ID`
- `KICK_CLIENT_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Start command on Railway:

```bash
sh -c 'uvicorn main:app --host 0.0.0.0 --port "$PORT"'
```

## Twitch app
Redirect URL: `<APP_URL>/auth/twitch/callback`

## Kick app
Redirect URL: `<APP_URL>/auth/kick/callback`
Webhook URL: `<APP_URL>/webhooks/kick`
Scopes: `user:read channel:read events:subscribe`.

## YouTube / Google Cloud
Enable **YouTube Data API v3**. Create an OAuth 2.0 Client ID of type **Web application**.
Authorized redirect URI: `<APP_URL>/auth/youtube/callback`
KZTTS requests only `https://www.googleapis.com/auth/youtube.readonly`.
For an OAuth app in Testing, add your Google account as a test user.

KZTTS detects the authenticated channel's active broadcast and reads new live-chat messages using the official YouTube Live Streaming API. It respects `pollingIntervalMillis` and skips old chat history when first attached.

## Note
Overlay keys and auth sessions are still in RAM in v0.3. After a Railway restart/redeploy, reconnect accounts and regenerate the Browser Source URL. Dashboard TTS preferences are saved in browser localStorage.
