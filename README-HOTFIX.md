# KZTTS v0.6.1 hotfix

- YouTube chat now uses `pytchat-ng`, avoiding the YouTube Data API quota drain caused by repeated Search API polling.
- YouTube LIVE detection first uses the public channel `/live`/`/streams` pages.
- TikTok no longer relies on `is_live()` before connecting; it attempts the actual room connection and logs errors to Railway.
- OBS URL, database schema, Twitch and Kick integrations are unchanged.
