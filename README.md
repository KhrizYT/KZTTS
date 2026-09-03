# KZTTS v0.4

TTS multistream cloud para Twitch, Kick, YouTube y TikTok.

## v0.4
- TikTok LIVE por `@usuario` usando TikTokLive 7.0.0 (sin login de TikTok).
- Browser Source estable por cuenta: guardar cambios reutiliza la misma URL.
- Al guardar cambios, la Browser Source abierta se reconecta sola con la nueva configuración.
- Twitch + Kick + YouTube + TikTok comparten filtros, voz y cola.

## Railway
Conserva las variables ya existentes:
- APP_URL
- SESSION_SECRET (NO cambiar; también mantiene estable la URL de OBS)
- TWITCH_CLIENT_ID
- TWITCH_CLIENT_SECRET
- KICK_CLIENT_ID
- KICK_CLIENT_SECRET
- YOUTUBE_API_KEY

No hay variables nuevas para TikTok.

## Nota TikTok
TikTok no ofrece una API pública oficial para leer los comentarios de LIVE. Esta versión usa TikTokLive, un cliente comunitario/no oficial. Puede requerir cambios si TikTok modifica su protocolo.
