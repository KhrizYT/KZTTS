# KZTTS v0.2

Cloud TTS for streams. Twitch + Kick feed one OBS Browser Source.

## Railway variables

- `APP_URL`
- `SESSION_SECRET`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `KICK_CLIENT_ID`
- `KICK_CLIENT_SECRET`

Start command on Railway:

```bash
sh -c 'uvicorn main:app --host 0.0.0.0 --port "$PORT"'
```

## Twitch app
Redirect URL:
`<APP_URL>/auth/twitch/callback`

## Kick app
Redirect URL:
`<APP_URL>/auth/kick/callback`

Webhook URL:
`<APP_URL>/webhooks/kick`

Requested Kick scopes: `user:read channel:read events:subscribe`.

## Note
Overlay keys are still in RAM in v0.2. After a Railway restart/redeploy, regenerate the Browser Source URL. Dashboard TTS preferences are saved in browser localStorage.
