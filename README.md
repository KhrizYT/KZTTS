# KZTTS v0.3.1

Cloud TTS for streams. Twitch + Kick + YouTube feed one OBS Browser Source.

## Railway variables

- `APP_URL`
- `SESSION_SECRET`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `KICK_CLIENT_ID`
- `KICK_CLIENT_SECRET`
- `YOUTUBE_API_KEY`

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

## YouTube
Enable **YouTube Data API v3** in Google Cloud and create a simple API key.
Add the key to Railway as `YOUTUBE_API_KEY`.

There is no Google/YouTube OAuth login in v0.3.1. In KZTTS you only type the channel handle, e.g. `@KhrizYT`.
KZTTS resolves that handle, detects the active public livestream and reads new public live-chat messages into the same TTS queue.

## Note
Twitch/Kick OAuth currently doubles as KZTTS sign-in/authorization. Overlay keys and auth sessions are still in RAM in v0.3.1. Dashboard TTS preferences are saved in browser localStorage. Persistent cloud settings per KZTTS account are the next storage step.
