import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict

import edge_tts
import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
APP_URL = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")

app = FastAPI(title="KZTTS", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=APP_URL.startswith("https://"))
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# MVP storage. Overlay keys survive while the server process is alive.
# In v0.2 this moves to Postgres/Supabase so sources survive restarts.
overlays: Dict[str, dict] = {}

VOICE_OPTIONS = {
    "es-MX-DaliaNeural": "Dalia — México (femenina)",
    "es-MX-BeatrizNeural": "Beatriz — México (femenina)",
    "es-MX-RenataNeural": "Renata — México (femenina)",
    "es-MX-CandelaNeural": "Candela — México (femenina)",
    "es-MX-LarissaNeural": "Larissa — México (femenina)",
    "es-MX-JorgeNeural": "Jorge — México (masculina)",
}

BOT_DEFAULTS = [
    "nightbot",
    "streamelements",
    "streamlabs",
    "moobot",
    "fossabot",
    "sery_bot",
]

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
REPEAT_RE = re.compile(r"(.)\1{8,}", re.I)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    voice: str = "es-MX-DaliaNeural"
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    overlay_key: str | None = None


class OverlayRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=50)
    voice: str = "es-MX-DaliaNeural"
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    blacklist: list[str] = Field(default_factory=lambda: BOT_DEFAULTS.copy())
    ignore_commands: bool = True
    ignore_urls: bool = True
    read_username: bool = False
    max_chars: int = Field(default=180, ge=20, le=400)
    cooldown: float = Field(default=2.0, ge=0, le=60)


def twitch_configured() -> bool:
    return bool(TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET)


def require_twitch_session(request: Request) -> dict:
    account = request.session.get("twitch")
    if not account:
        raise HTTPException(status_code=401, detail="Twitch no conectado")
    return account


async def twitch_validate(access_token: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {access_token}"},
        )
        return r.status_code == 200


async def twitch_refresh(refresh_token: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["access_token"], data.get("refresh_token", refresh_token)


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/overlay")
async def overlay_page():
    return FileResponse(BASE_DIR / "static" / "overlay.html")


@app.get("/api/config")
async def config(request: Request):
    return {
        "twitch_configured": twitch_configured(),
        "connected": bool(request.session.get("twitch")),
        "account": request.session.get("twitch", {}).get("display_name"),
        "voices": VOICE_OPTIONS,
        "default_blacklist": BOT_DEFAULTS,
        "app_url": APP_URL,
    }


@app.get("/auth/twitch")
async def twitch_login(request: Request):
    if not twitch_configured():
        raise HTTPException(status_code=500, detail="Faltan TWITCH_CLIENT_ID y TWITCH_CLIENT_SECRET")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    redirect_uri = f"{APP_URL}/auth/twitch/callback"
    params = httpx.QueryParams({
        "client_id": TWITCH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "chat:read",
        "state": state,
        "force_verify": "false",
    })
    return RedirectResponse(f"https://id.twitch.tv/oauth2/authorize?{params}")


@app.get("/auth/twitch/callback")
async def twitch_callback(request: Request, code: str, state: str):
    if not secrets.compare_digest(state, request.session.get("oauth_state", "")):
        raise HTTPException(status_code=400, detail="OAuth state inválido")

    redirect_uri = f"{APP_URL}/auth/twitch/callback"
    async with httpx.AsyncClient(timeout=15) as client:
        token_r = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        token_r.raise_for_status()
        token_data = token_r.json()
        access_token = token_data["access_token"]
        user_r = await client.get(
            "https://api.twitch.tv/helix/users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": TWITCH_CLIENT_ID,
            },
        )
        user_r.raise_for_status()
        user = user_r.json()["data"][0]

    request.session["twitch"] = {
        "login": user["login"],
        "display_name": user["display_name"],
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
    }
    return RedirectResponse("/")


@app.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/api/tts")
async def tts(req: TTSRequest, request: Request):
    if req.voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Voz no permitida")

    authorized = bool(request.session.get("twitch"))
    if req.overlay_key:
        authorized = req.overlay_key in overlays
    if not authorized:
        raise HTTPException(status_code=401, detail="No autorizado")

    text = sanitize_text(req.text, 400)
    if not text:
        raise HTTPException(status_code=400, detail="Texto vacío")

    communicate = edge_tts.Communicate(
        text=text,
        voice=req.voice,
        rate=f"{req.rate:+d}%",
        pitch=f"{req.pitch:+d}Hz",
    )
    chunks = []
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TTS no disponible: {exc}")

    if not chunks:
        raise HTTPException(status_code=502, detail="No se recibió audio")
    return Response(content=b"".join(chunks), media_type="audio/mpeg")


@app.post("/api/overlay")
async def create_overlay(req: OverlayRequest, request: Request):
    account = require_twitch_session(request)
    if req.voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Voz no permitida")

    key = secrets.token_urlsafe(32)
    overlays[key] = {
        "owner": account["login"],
        "channel": req.channel.lower().lstrip("#"),
        "voice": req.voice,
        "rate": req.rate,
        "pitch": req.pitch,
        "blacklist": sorted({x.strip().lower() for x in req.blacklist if x.strip()}),
        "ignore_commands": req.ignore_commands,
        "ignore_urls": req.ignore_urls,
        "read_username": req.read_username,
        "max_chars": req.max_chars,
        "cooldown": req.cooldown,
        "access_token": account["access_token"],
        "refresh_token": account.get("refresh_token", ""),
        "login": account["login"],
        "created_at": int(time.time()),
    }
    return {"url": f"{APP_URL}/overlay?key={key}", "key": key}


def sanitize_text(text: str, max_chars: int) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    text = REPEAT_RE.sub(lambda m: m.group(1) * 3, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].strip()


def parse_irc_privmsg(line: str):
    if " PRIVMSG " not in line:
        return None
    tags = {}
    rest = line
    if line.startswith("@"):
        tag_part, rest = line.split(" ", 1)
        for item in tag_part[1:].split(";"):
            k, _, v = item.partition("=")
            tags[k] = v
    try:
        prefix, trailing = rest.split(" PRIVMSG ", 1)
        _, message = trailing.split(" :", 1)
        login = prefix.split("!", 1)[0].lstrip(":")
        display = tags.get("display-name") or login
        return display, login, message
    except ValueError:
        return None


async def ensure_overlay_token(data: dict):
    if await twitch_validate(data["access_token"]):
        return
    if not data.get("refresh_token"):
        raise RuntimeError("Token de Twitch vencido; vuelve a generar la fuente")
    access, refresh = await twitch_refresh(data["refresh_token"])
    data["access_token"] = access
    data["refresh_token"] = refresh


@app.websocket("/ws/twitch")
async def twitch_ws(client_ws: WebSocket, key: str):
    await client_ws.accept()
    data = overlays.get(key)
    if not data:
        await client_ws.send_json({"type": "error", "message": "Fuente inválida o expirada"})
        await client_ws.close(code=1008)
        return

    cooldowns: Dict[str, float] = {}
    try:
        await ensure_overlay_token(data)
        async with websockets.connect("wss://irc-ws.chat.twitch.tv:443", ping_interval=20, ping_timeout=20) as twitch:
            await twitch.send(f"PASS oauth:{data['access_token']}")
            await twitch.send(f"NICK {data['login']}")
            await twitch.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await twitch.send(f"JOIN #{data['channel']}")
            await client_ws.send_json({"type": "status", "message": f"Conectado a #{data['channel']}"})

            while True:
                raw = await twitch.recv()
                for line in raw.split("\r\n"):
                    if not line:
                        continue
                    if line.startswith("PING"):
                        await twitch.send(line.replace("PING", "PONG", 1))
                        continue

                    parsed = parse_irc_privmsg(line)
                    if not parsed:
                        continue
                    display, login, message = parsed
                    login_l = login.lower()
                    if login_l in data["blacklist"]:
                        continue
                    if data["ignore_commands"] and message.lstrip().startswith("!"):
                        continue
                    if data["ignore_urls"] and URL_RE.search(message):
                        continue

                    now = time.monotonic()
                    last = cooldowns.get(login_l, 0)
                    if data["cooldown"] and now - last < data["cooldown"]:
                        continue
                    cooldowns[login_l] = now

                    clean = sanitize_text(message, data["max_chars"])
                    if not clean:
                        continue
                    spoken = f"{display} dice: {clean}" if data["read_username"] else clean
                    await client_ws.send_json({
                        "type": "message",
                        "platform": "twitch",
                        "user": display,
                        "text": spoken,
                        "voice": data["voice"],
                        "rate": data["rate"],
                        "pitch": data["pitch"],
                    })
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await client_ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        try:
            await client_ws.close()
        except Exception:
            pass
