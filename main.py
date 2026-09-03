import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Dict
from urllib.parse import parse_qs, urlparse

import edge_tts
import httpx
import websockets
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

import storage

try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import CommentEvent
    TIKTOKLIVE_AVAILABLE = True
except Exception:
    TikTokLiveClient = None
    CommentEvent = None
    TIKTOKLIVE_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
APP_URL = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
KICK_CLIENT_ID = os.getenv("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.getenv("KICK_CLIENT_SECRET", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

app = FastAPI(title="KZTTS", version="0.5.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=APP_URL.startswith("https://"),
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Runtime overlay configs. The overlay key itself is stable per account, so changing settings no longer changes the OBS URL.
overlays: Dict[str, dict] = {}
# Active OBS Browser Sources. Updating settings restarts these sockets automatically,
# so OBS keeps the exact same URL and reconnects with the new configuration.
overlay_sources: Dict[str, list["OverlaySocket"]] = {}

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
KICK_EMOTE_RE = re.compile(r"\[emote:\d+:([^\]]+)\]", re.I)

# Official Kick RSA public key documented for webhook signature verification.
KICK_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAq/+l1WnlRrGSolDMA+A8
6rAhMbQGmQ2SapVcGM3zq8ANXjnhDWocMqfWcTd95btDydITa10kDvHzw9WQOqp2
MZI7ZyrfzJuz5nhTPCiJwTwnEtWft7nV14BYRDHvlfqPUaZ+1KR4OCaO/wWIk/rQ
L/TjY0M70gse8rlBkbo2a8rKhu69RQTRsoaf4DVhDPEeSeI5jVrRDGAMGL3cGuyY
6CLKGdjVEM78g3JfYOvDU/RvfqD7L89TZ3iN94jrmWdGz34JNlEI5hqK8dd7C5EF
BEbZ5jgB8s8ReQVH8+MkuffjdAj3ajDDX3DOJMIut1lBrUVD1AaSrGCKHooWoL2e
twIDAQAB
-----END PUBLIC KEY-----
"""
# Correct the one character above from the documented key if it ever drifts by
# preferring the API-fetched key is a future improvement. For v0.2 the literal
# below is replaced at import with the exact documented bytes.
KICK_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAq/+l1WnlRrGSolDMA+A8
6rAhMbQGmQ2SapVcGM3zq8ANXjnhDWocMqfWcTd95btDydITa10kDvHzw9WQOqp2
MZI7ZyrfzJuz5nhTPCiJwTwnEtWft7nV14BYRDHvlfqPUaZ+1KR4OCaO/wWIk/rQ
L/TjY0M70gse8rlBkbo2a8rKhu69RQTRsoaf4DVhDPEeSeI5jVrRDGAMGL3cGuyY
6CLKGdjVEM78g3JfYOvDU/RvfqD7L89TZ3iN94jrmWdGz34JNlEI5hqK8dd7C5EF
BEbZ5jgB8s8ReQV8H+MkuffjdAj3ajDDX3DOJMIut1lBrUVD1AaSrGCKHooWoL2e
twIDAQAB
-----END PUBLIC KEY-----
"""
KICK_PUBLIC_KEY = serialization.load_pem_public_key(KICK_PUBLIC_KEY_PEM)

# broadcaster_user_id -> key -> connected Browser Source socket
kick_clients: Dict[int, Dict[str, "OverlaySocket"]] = {}
kick_seen_ids: set[str] = set()
kick_seen_order: deque[str] = deque(maxlen=3000)


class OverlaySocket:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.lock = asyncio.Lock()

    async def send(self, payload: dict):
        async with self.lock:
            await self.ws.send_json(payload)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    voice: str = "es-MX-DaliaNeural"
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    overlay_key: str | None = None


class TestMessageRequest(BaseModel):
    platform: str = Field(default="tiktok", max_length=20)
    text: str = Field(default="probando KZTTS desde TikTok", min_length=1, max_length=400)
    user: str = Field(default="PruebaTikTok", min_length=1, max_length=100)
    overlay_key: str | None = Field(default=None, max_length=100)


class OverlayRequest(BaseModel):
    channel: str = Field(default="", max_length=50)
    enable_twitch: bool = True
    enable_kick: bool = False
    enable_youtube: bool = False
    youtube_handle: str = Field(default="", max_length=100)
    enable_tiktok: bool = False
    tiktok_handle: str = Field(default="", max_length=100)
    overlay_key: str | None = Field(default=None, max_length=100)
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


def kick_configured() -> bool:
    return bool(KICK_CLIENT_ID and KICK_CLIENT_SECRET)


def youtube_configured() -> bool:
    return bool(YOUTUBE_API_KEY)


def tiktok_configured() -> bool:
    return TIKTOKLIVE_AVAILABLE


def legacy_overlay_key(identity: str) -> str:
    """v0.4-compatible key so an existing OBS URL can survive the DB migration."""
    digest = hmac.new(SESSION_SECRET.encode(), f"kztts-overlay:{identity}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def get_account_id(request: Request, required: bool = False) -> str | None:
    account_id = request.session.get("account_id")
    if account_id and storage.get_account(account_id):
        return account_id
    if account_id:
        request.session.pop("account_id", None)
    if required:
        raise HTTPException(status_code=401, detail="Inicia sesión con Twitch o Kick primero")
    return None


def get_accounts(request: Request) -> dict:
    account_id = get_account_id(request)
    return storage.list_providers(account_id) if account_id else {}


def require_twitch_session(request: Request) -> dict:
    account = get_accounts(request).get("twitch")
    if not account:
        raise HTTPException(status_code=401, detail="Twitch no conectado")
    return account


def require_kick_session(request: Request) -> dict:
    account = get_accounts(request).get("kick")
    if not account:
        raise HTTPException(status_code=401, detail="Kick no conectado")
    return account


def attach_provider(
    request: Request,
    provider: str,
    provider_user_id: str,
    login: str,
    display_name: str,
    access_token: str,
    refresh_token: str,
    metadata: dict | None = None,
) -> str:
    if not storage.database_configured():
        raise HTTPException(status_code=500, detail="Falta DATABASE_URL (PostgreSQL) en Railway")

    current = get_account_id(request)
    existing = storage.find_account_by_provider(provider, str(provider_user_id))
    if existing:
        account_id = existing
    elif current:
        account_id = current
    else:
        identity = f"twitch:{login.lower()}" if provider == "twitch" else f"kick:{provider_user_id}"
        account_id = storage.create_account(legacy_overlay_key(identity))["id"]

    # Migration: v0.4 preferred Twitch when both were connected. Before the first
    # cloud config is saved, linking Twitch is allowed to adopt that old key.
    if provider == "twitch" and not storage.account_has_config(account_id):
        try:
            storage.set_overlay_key(account_id, legacy_overlay_key(f"twitch:{login.lower()}"))
        except Exception:
            pass

    storage.upsert_provider(
        account_id=account_id,
        provider=provider,
        provider_user_id=str(provider_user_id),
        login=login,
        display_name=display_name,
        access_token=access_token,
        refresh_token=refresh_token,
        metadata=metadata or {},
    )
    request.session["account_id"] = account_id
    return account_id


def account_overlay_key(request: Request) -> str:
    account_id = get_account_id(request, required=True)
    account = storage.get_account(account_id)
    if not account:
        raise HTTPException(status_code=401, detail="Cuenta KZTTS no encontrada")
    return account["overlay_key"]


def load_overlay_data(key: str) -> dict | None:
    data = overlays.get(key)
    if data is not None:
        return data
    row = storage.get_config_by_overlay_key(key) if storage.database_configured() else None
    if not row:
        return None
    account_id, data = row
    data["account_id"] = account_id
    overlays[key] = data
    return data


@app.on_event("startup")
async def init_persistent_storage():
    if storage.database_configured():
        await asyncio.to_thread(storage.init_db)


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


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


async def kick_subscribe_chat(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.kick.com/public/v1/events/subscriptions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "method": "webhook",
                "events": [{"name": "chat.message.sent", "version": 1}],
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Kick subscription {r.status_code}: {r.text[:300]}")
        return r.json()


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/overlay")
async def overlay_page():
    return FileResponse(BASE_DIR / "static" / "overlay.html")


@app.get("/api/config")
async def config(request: Request):
    db_ok = storage.database_configured()
    account_id = get_account_id(request) if db_ok else None
    accounts = storage.list_providers(account_id) if account_id else {}
    twitch = accounts.get("twitch") or {}
    kick = accounts.get("kick") or {}
    account = storage.get_account(account_id) if account_id else None
    overlay_key = account.get("overlay_key") if account else None
    saved = storage.get_config(account_id) if account_id else None
    return {
        "database_configured": db_ok,
        "twitch_configured": twitch_configured(),
        "kick_configured": kick_configured(),
        "twitch_connected": bool(twitch),
        "kick_connected": bool(kick),
        "youtube_configured": youtube_configured(),
        "tiktok_configured": tiktok_configured(),
        "twitch_account": twitch.get("display_name"),
        "kick_account": kick.get("name") or kick.get("display_name") or kick.get("slug"),
        "kick_subscription_ok": kick.get("subscription_ok", False),
        "kick_subscription_error": kick.get("subscription_error", ""),
        "voices": VOICE_OPTIONS,
        "default_blacklist": BOT_DEFAULTS,
        "app_url": APP_URL,
        "overlay_key": overlay_key,
        "overlay_url": f"{APP_URL}/overlay?key={overlay_key}" if overlay_key else None,
        "overlay_configured": bool(saved),
        "saved_settings": saved,
        "kick_webhook_url": f"{APP_URL}/webhooks/kick",
    }


@app.get("/auth/twitch")
async def twitch_login(request: Request):
    if not storage.database_configured():
        raise HTTPException(status_code=500, detail="Falta DATABASE_URL (PostgreSQL) en Railway")
    if not twitch_configured():
        raise HTTPException(status_code=500, detail="Faltan TWITCH_CLIENT_ID y TWITCH_CLIENT_SECRET")
    state = secrets.token_urlsafe(24)
    request.session["twitch_oauth_state"] = state
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
    if not secrets.compare_digest(state, request.session.get("twitch_oauth_state", "")):
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

    attach_provider(
        request=request,
        provider="twitch",
        provider_user_id=user["id"],
        login=user["login"],
        display_name=user["display_name"],
        access_token=access_token,
        refresh_token=token_data.get("refresh_token", ""),
    )
    request.session.pop("twitch_oauth_state", None)
    return RedirectResponse("/")


@app.get("/auth/kick")
async def kick_login(request: Request):
    if not storage.database_configured():
        raise HTTPException(status_code=500, detail="Falta DATABASE_URL (PostgreSQL) en Railway")
    if not kick_configured():
        raise HTTPException(status_code=500, detail="Faltan KICK_CLIENT_ID y KICK_CLIENT_SECRET")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    request.session["kick_oauth_state"] = state
    request.session["kick_pkce_verifier"] = verifier
    redirect_uri = f"{APP_URL}/auth/kick/callback"
    params = httpx.QueryParams({
        "response_type": "code",
        "client_id": KICK_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "user:read channel:read events:subscribe",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    return RedirectResponse(f"https://id.kick.com/oauth/authorize?{params}")


@app.get("/auth/kick/callback")
async def kick_callback(request: Request, code: str, state: str):
    if not secrets.compare_digest(state, request.session.get("kick_oauth_state", "")):
        raise HTTPException(status_code=400, detail="Kick OAuth state inválido")
    verifier = request.session.get("kick_pkce_verifier")
    if not verifier:
        raise HTTPException(status_code=400, detail="Falta PKCE verifier")

    redirect_uri = f"{APP_URL}/auth/kick/callback"
    async with httpx.AsyncClient(timeout=20) as client:
        token_r = await client.post(
            "https://id.kick.com/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": KICK_CLIENT_ID,
                "client_secret": KICK_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "code": code,
            },
        )
        if token_r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Kick token: {token_r.text[:300]}")
        token_data = token_r.json()
        access_token = token_data["access_token"]

        user_r = await client.get(
            "https://api.kick.com/public/v1/users",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_r.raise_for_status()
        users = user_r.json().get("data", [])
        if not users:
            raise HTTPException(status_code=502, detail="Kick no devolvió el usuario")
        user = users[0]

        channel_r = await client.get(
            "https://api.kick.com/public/v1/channels",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        channel_r.raise_for_status()
        channels = channel_r.json().get("data", [])
        channel = channels[0] if channels else {}

    kick_data = {
        "user_id": int(user["user_id"]),
        "name": user.get("name") or channel.get("slug") or str(user["user_id"]),
        "slug": channel.get("slug") or "",
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "subscription_ok": False,
        "subscription_error": "",
    }
    try:
        sub = await kick_subscribe_chat(access_token)
        kick_data["subscription_ok"] = True
        kick_data["subscription"] = sub
    except Exception as exc:
        kick_data["subscription_error"] = str(exc)

    attach_provider(
        request=request,
        provider="kick",
        provider_user_id=str(kick_data["user_id"]),
        login=kick_data.get("slug") or kick_data.get("name") or str(kick_data["user_id"]),
        display_name=kick_data.get("name") or kick_data.get("slug") or str(kick_data["user_id"]),
        access_token=kick_data["access_token"],
        refresh_token=kick_data.get("refresh_token", ""),
        metadata={
            "name": kick_data.get("name", ""),
            "slug": kick_data.get("slug", ""),
            "subscription_ok": kick_data.get("subscription_ok", False),
            "subscription_error": kick_data.get("subscription_error", ""),
            "subscription": kick_data.get("subscription"),
        },
    )
    request.session.pop("kick_oauth_state", None)
    request.session.pop("kick_pkce_verifier", None)
    return RedirectResponse("/")


@app.post("/auth/logout")
async def logout(request: Request):
    # Logout clears only this browser session. Cloud settings/tokens remain so the
    # same Twitch/Kick account can recover them on the next login.
    request.session.clear()
    return {"ok": True}


@app.post("/api/tts")
async def tts(req: TTSRequest, request: Request):
    if req.voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Voz no permitida")

    accounts = get_accounts(request)
    authorized = bool(accounts.get("twitch") or accounts.get("kick"))
    if req.overlay_key:
        authorized = load_overlay_data(req.overlay_key) is not None
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


@app.post("/api/test-message")
async def test_message(req: TestMessageRequest, request: Request):
    accounts = get_accounts(request)
    if not (accounts.get("twitch") or accounts.get("kick")):
        raise HTTPException(status_code=401, detail="Inicia sesión con Twitch o Kick primero")

    key = (req.overlay_key or "").strip() or account_overlay_key(request)
    data = load_overlay_data(key)
    if not data:
        raise HTTPException(status_code=400, detail="Primero guarda / actualiza la Browser Source")

    platform = req.platform.lower().strip()
    if platform not in {"twitch", "kick", "youtube", "tiktok"}:
        raise HTTPException(status_code=400, detail="Plataforma no válida")
    if not data.get(f"enable_{platform}"):
        raise HTTPException(status_code=400, detail=f"Activa {platform.title()} y guarda la Browser Source primero")

    sockets = list(overlay_sources.get(key, []))
    if not sockets:
        raise HTTPException(status_code=409, detail="La Browser Source no está abierta en OBS")

    login = req.user.strip() or "PruebaTikTok"
    cooldowns = data.setdefault(f"{platform}_test_cooldowns", {})
    clean = should_read(data, login, req.text, cooldowns)
    if not clean:
        raise HTTPException(status_code=400, detail="El mensaje de prueba fue bloqueado por tus filtros o cooldown")
    spoken = f"{login} dice: {clean}" if data["read_username"] else clean

    payload = {
        "type": "message",
        "platform": platform,
        "user": login,
        "text": spoken,
        "voice": data["voice"],
        "rate": data["rate"],
        "pitch": data["pitch"],
    }
    sent = 0
    for socket in sockets:
        try:
            await socket.send(payload)
            sent += 1
        except Exception:
            pass
    if not sent:
        raise HTTPException(status_code=409, detail="No pude enviar el mensaje a OBS")
    return {"ok": True, "sent": sent}


@app.post("/api/overlay")
async def create_overlay(req: OverlayRequest, request: Request):
    if not req.enable_twitch and not req.enable_kick and not req.enable_youtube and not req.enable_tiktok:
        raise HTTPException(status_code=400, detail="Activa al menos una plataforma")
    if req.voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Voz no permitida")

    accounts = get_accounts(request)
    if not (accounts.get("twitch") or accounts.get("kick")):
        raise HTTPException(status_code=401, detail="Inicia sesión con Twitch o Kick primero")
    twitch = accounts.get("twitch") if req.enable_twitch else None
    kick = accounts.get("kick") if req.enable_kick else None
    if req.enable_twitch and not twitch:
        raise HTTPException(status_code=401, detail="Conecta Twitch primero")
    if req.enable_kick and not kick:
        raise HTTPException(status_code=401, detail="Conecta Kick primero")
    if req.enable_youtube and not youtube_configured():
        raise HTTPException(status_code=500, detail="Falta YOUTUBE_API_KEY en Railway")
    youtube_handle = req.youtube_handle.strip()
    if req.enable_youtube and not youtube_handle:
        raise HTTPException(status_code=400, detail="Escribe el @handle de YouTube")
    tiktok_handle = req.tiktok_handle.strip()
    if req.enable_tiktok and not tiktok_configured():
        raise HTTPException(status_code=500, detail="TikTokLive no está disponible en el servidor")
    if req.enable_tiktok and not tiktok_handle:
        raise HTTPException(status_code=400, detail="Escribe el @usuario de TikTok")
    if req.enable_kick and not kick.get("subscription_ok"):
        raise HTTPException(
            status_code=400,
            detail=f"Kick conectado, pero falta la suscripción al chat: {kick.get('subscription_error') or 'reconecta Kick'}",
        )

    account_id = get_account_id(request, required=True)
    key = account_overlay_key(request)
    data = {
        "account_id": account_id,
        "voice": req.voice,
        "rate": req.rate,
        "pitch": req.pitch,
        "blacklist": sorted({x.strip().lower() for x in req.blacklist if x.strip()}),
        "ignore_commands": req.ignore_commands,
        "ignore_urls": req.ignore_urls,
        "read_username": req.read_username,
        "max_chars": req.max_chars,
        "cooldown": req.cooldown,
        "enable_twitch": req.enable_twitch,
        "enable_kick": req.enable_kick,
        "enable_youtube": req.enable_youtube,
        "enable_tiktok": req.enable_tiktok,
        "created_at": int(time.time()),
    }
    if twitch:
        data.update({
            "owner": twitch["login"],
            "channel": (req.channel or twitch["login"]).lower().lstrip("#"),
            "twitch_login": twitch["login"],
        })
    if kick:
        data.update({
            "kick_user_id": int(kick["user_id"]),
            "kick_name": kick.get("name") or kick.get("slug") or str(kick["user_id"]),
            "kick_slug": kick.get("slug", ""),
        })
    if req.enable_youtube:
        data.update({
            "youtube_handle": youtube_handle if youtube_handle.startswith("@") else f"@{youtube_handle}",
        })
    if req.enable_tiktok:
        data.update({
            "tiktok_handle": tiktok_handle if tiktok_handle.startswith("@") else f"@{tiktok_handle}",
        })
    existing = overlays.get(key)
    if existing is None:
        overlays[key] = data
    else:
        existing.clear()
        existing.update(data)
        data = existing

    storage.save_config(account_id, data)

    # Force currently open OBS sources to reconnect automatically using the same URL.
    for source in list(overlay_sources.get(key, [])):
        try:
            await source.ws.close(code=1012)
        except Exception:
            pass

    return {"url": f"{APP_URL}/overlay?key={key}", "key": key, "updated": True}


def sanitize_text(text: str, max_chars: int) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    text = KICK_EMOTE_RE.sub(lambda m: m.group(1), text)
    text = REPEAT_RE.sub(lambda m: m.group(1) * 3, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].strip()


def should_read(data: dict, login: str, message: str, cooldowns: Dict[str, float]) -> str | None:
    login_l = login.lower()
    if login_l in data["blacklist"]:
        return None
    if data["ignore_commands"] and message.lstrip().startswith("!"):
        return None
    if data["ignore_urls"] and URL_RE.search(message):
        return None

    now = time.monotonic()
    last = cooldowns.get(login_l, 0)
    if data["cooldown"] and now - last < data["cooldown"]:
        return None
    cooldowns[login_l] = now

    return sanitize_text(message, data["max_chars"])


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


async def ensure_overlay_twitch_token(data: dict):
    account_id = data.get("account_id")
    providers = storage.list_providers(account_id) if account_id else {}
    twitch = providers.get("twitch") or {}
    access_token = twitch.get("access_token", "")
    refresh_token = twitch.get("refresh_token", "")
    if not access_token:
        raise RuntimeError("Twitch no está conectado a esta cuenta KZTTS")
    if await twitch_validate(access_token):
        data["twitch_access_token"] = access_token
        data["twitch_refresh_token"] = refresh_token
        return
    if not refresh_token:
        raise RuntimeError("Token de Twitch vencido; reconecta Twitch")
    access, refresh = await twitch_refresh(refresh_token)
    storage.update_provider_tokens(account_id, "twitch", access, refresh)
    data["twitch_access_token"] = access
    data["twitch_refresh_token"] = refresh


async def twitch_reader(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    await ensure_overlay_twitch_token(data)
    async with websockets.connect("wss://irc-ws.chat.twitch.tv:443", ping_interval=20, ping_timeout=20) as twitch:
        await twitch.send(f"PASS oauth:{data['twitch_access_token']}")
        await twitch.send(f"NICK {data['twitch_login']}")
        await twitch.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        await twitch.send(f"JOIN #{data['channel']}")
        await socket.send({"type": "status", "platform": "twitch", "message": f"Twitch #{data['channel']} conectado"})

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
                clean = should_read(data, login, message, cooldowns)
                if not clean:
                    continue
                spoken = f"{display} dice: {clean}" if data["read_username"] else clean
                await socket.send({
                    "type": "message",
                    "platform": "twitch",
                    "user": display,
                    "text": spoken,
                    "voice": data["voice"],
                    "rate": data["rate"],
                    "pitch": data["pitch"],
                })


async def twitch_reader_safe(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    try:
        await twitch_reader(socket, data, cooldowns)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            await socket.send({"type": "error", "platform": "twitch", "message": f"Twitch: {exc}"})
        except Exception:
            pass


def register_kick_client(user_id: int, key: str, socket: OverlaySocket):
    kick_clients.setdefault(user_id, {})[key] = socket


def unregister_kick_client(user_id: int, key: str):
    group = kick_clients.get(user_id)
    if not group:
        return
    group.pop(key, None)
    if not group:
        kick_clients.pop(user_id, None)


async def youtube_channel_id(data: dict) -> str:
    cached = data.get("youtube_channel_id")
    if cached:
        return cached
    handle = (data.get("youtube_handle") or "").strip()
    if not handle:
        raise RuntimeError("Falta el @handle de YouTube")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "id,snippet",
                "forHandle": handle,
                "key": YOUTUBE_API_KEY,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"YouTube channel {r.status_code}: {r.text[:240]}")
        items = r.json().get("items", [])
        if not items:
            raise RuntimeError(f"No encontré el canal {handle}")
        data["youtube_channel_id"] = items[0]["id"]
        data["youtube_channel_title"] = (items[0].get("snippet") or {}).get("title") or handle
        return data["youtube_channel_id"]


async def youtube_live_video_id(data: dict) -> str | None:
    handle = (data.get("youtube_handle") or "").strip()
    if not handle:
        return None

    # First try YouTube's public /live route. This normally redirects straight
    # to the current broadcast and avoids consuming Search API quota.
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 KZTTS/0.3.1"},
        ) as client:
            r = await client.get(f"https://www.youtube.com/{handle}/live")
            parsed = urlparse(str(r.url))
            if parsed.path == "/watch":
                video_id = (parse_qs(parsed.query).get("v") or [None])[0]
                if video_id:
                    return video_id
    except Exception:
        pass

    # Fallback: official Data API search. Throttled while no stream is live.
    now = time.monotonic()
    if now - float(data.get("youtube_last_search", 0)) < 120:
        return None
    data["youtube_last_search"] = now

    channel_id = await youtube_channel_id(data)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "id",
                "channelId": channel_id,
                "eventType": "live",
                "type": "video",
                "maxResults": 5,
                "key": YOUTUBE_API_KEY,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"YouTube live search {r.status_code}: {r.text[:240]}")
        for item in r.json().get("items", []):
            video_id = (item.get("id") or {}).get("videoId")
            if video_id:
                return video_id
    return None


async def youtube_active_chat(data: dict) -> tuple[str, str] | None:
    video_id = await youtube_live_video_id(data)
    if not video_id:
        return None
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,liveStreamingDetails",
                "id": video_id,
                "key": YOUTUBE_API_KEY,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"YouTube video {r.status_code}: {r.text[:240]}")
        items = r.json().get("items", [])
        if not items:
            return None
        item = items[0]
        live = item.get("liveStreamingDetails") or {}
        chat_id = live.get("activeLiveChatId")
        if not chat_id:
            return None
        title = (item.get("snippet") or {}).get("title") or "Directo de YouTube"
        data["youtube_video_id"] = video_id
        return chat_id, title


YOUTUBE_CHAT_TYPES = {
    "textMessageEvent",
    "superChatEvent",
    "memberMilestoneChatEvent",
}


async def youtube_chat_page(data: dict, live_chat_id: str, page_token: str | None):
    params = {
        "liveChatId": live_chat_id,
        "part": "id,snippet,authorDetails",
        "maxResults": 200,
        "hl": "es",
        "key": YOUTUBE_API_KEY,
    }
    if page_token:
        params["pageToken"] = page_token
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/liveChat/messages",
            params=params,
        )
        if r.status_code in (403, 404):
            return None
        if r.status_code != 200:
            raise RuntimeError(f"YouTube chat {r.status_code}: {r.text[:240]}")
        return r.json()


async def youtube_reader(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    waiting_sent = False
    while True:
        chat_id = data.get("youtube_chat_id")
        if not chat_id:
            active = await youtube_active_chat(data)
            if not active:
                if not waiting_sent:
                    await socket.send({
                        "type": "status",
                        "platform": "youtube",
                        "message": f"YouTube {data.get('youtube_handle', '')}: esperando un directo activo",
                    })
                    waiting_sent = True
                await asyncio.sleep(20)
                continue
            chat_id, title = active
            data["youtube_chat_id"] = chat_id
            data["youtube_live_title"] = title
            data.pop("youtube_page_token", None)
            waiting_sent = False
            await socket.send({"type": "status", "platform": "youtube", "message": f"YouTube conectado: {title}"})

        page_token = data.get("youtube_page_token")
        page = await youtube_chat_page(data, chat_id, page_token)
        if page is None or page.get("offlineAt"):
            data.pop("youtube_chat_id", None)
            data.pop("youtube_live_title", None)
            data.pop("youtube_page_token", None)
            data.pop("youtube_video_id", None)
            await socket.send({"type": "status", "platform": "youtube", "message": "YouTube: el directo terminó; esperando el siguiente"})
            await asyncio.sleep(12)
            continue

        next_token = page.get("nextPageToken")
        first_page = page_token is None
        if next_token:
            data["youtube_page_token"] = next_token

        # Skip chat history on first attach; only read messages sent after KZTTS starts.
        if not first_page:
            for item in page.get("items", []):
                snippet = item.get("snippet") or {}
                if snippet.get("type") not in YOUTUBE_CHAT_TYPES:
                    continue
                message = snippet.get("displayMessage") or ""
                author = item.get("authorDetails") or {}
                display = author.get("displayName") or "YouTube"
                clean = should_read(data, display, message, cooldowns)
                if not clean:
                    continue
                spoken = f"{display} dice: {clean}" if data["read_username"] else clean
                await socket.send({
                    "type": "message",
                    "platform": "youtube",
                    "user": display,
                    "text": spoken,
                    "voice": data["voice"],
                    "rate": data["rate"],
                    "pitch": data["pitch"],
                })

        wait_ms = max(1000, int(page.get("pollingIntervalMillis") or 5000))
        await asyncio.sleep(wait_ms / 1000)


async def youtube_reader_safe(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    try:
        await youtube_reader(socket, data, cooldowns)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            await socket.send({"type": "error", "platform": "youtube", "message": f"YouTube: {exc}"})
        except Exception:
            pass


def tiktok_user_fields(event) -> tuple[str, str]:
    user = getattr(event, "user", None)
    unique_id = (getattr(user, "unique_id", "") or "").strip()
    nickname = (getattr(user, "nickname", "") or "").strip()
    login = unique_id or nickname or "tiktok"
    display = nickname or unique_id or "TikTok"
    return login, display


async def tiktok_reader(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    handle = (data.get("tiktok_handle") or "").strip()
    if not handle:
        raise RuntimeError("Falta el @usuario de TikTok")

    retry = 8
    waiting_sent = False
    while True:
        client = TikTokLiveClient(unique_id=handle)

        async def on_comment(event):
            login, display = tiktok_user_fields(event)
            message = (getattr(event, "comment", "") or "").strip()
            clean = should_read(data, login, message, cooldowns)
            if not clean:
                return
            spoken = f"{display} dice: {clean}" if data["read_username"] else clean
            await socket.send({
                "type": "message",
                "platform": "tiktok",
                "user": display,
                "text": spoken,
                "voice": data["voice"],
                "rate": data["rate"],
                "pitch": data["pitch"],
            })

        client.add_listener(CommentEvent, on_comment)
        try:
            is_live = await client.is_live()
            if not is_live:
                if not waiting_sent:
                    await socket.send({
                        "type": "status",
                        "platform": "tiktok",
                        "message": f"TikTok {handle}: esperando un LIVE público (la vista previa de LIVE Studio no cuenta)",
                    })
                    waiting_sent = True
                await asyncio.sleep(15)
                continue

            waiting_sent = False
            await socket.send({"type": "status", "platform": "tiktok", "message": f"TikTok conectando a {handle}"})
            live_task = await client.start()
            retry = 8
            await socket.send({"type": "status", "platform": "tiktok", "message": f"TikTok {handle} conectado"})
            await live_task
            await socket.send({"type": "status", "platform": "tiktok", "message": f"TikTok {handle}: LIVE terminado; esperando el siguiente"})
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            try:
                if getattr(client, "connected", False):
                    await client.disconnect()
            except Exception:
                pass
            raise
        except Exception as exc:
            await socket.send({"type": "error", "platform": "tiktok", "message": f"TikTok: {exc}"})
            await asyncio.sleep(retry)
            retry = min(int(retry * 1.7), 45)
        finally:
            try:
                if getattr(client, "connected", False):
                    await client.disconnect()
            except Exception:
                pass


async def tiktok_reader_safe(socket: OverlaySocket, data: dict, cooldowns: Dict[str, float]):
    try:
        await tiktok_reader(socket, data, cooldowns)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        try:
            await socket.send({"type": "error", "platform": "tiktok", "message": f"TikTok: {exc}"})
        except Exception:
            pass


@app.websocket("/ws/overlay")
async def overlay_ws(client_ws: WebSocket, key: str):
    await client_ws.accept()
    data = load_overlay_data(key)
    if not data:
        await client_ws.send_json({"type": "error", "message": "Fuente inválida o expirada"})
        await client_ws.close(code=1008)
        return

    socket = OverlaySocket(client_ws)
    overlay_sources.setdefault(key, []).append(socket)
    twitch_task = None
    youtube_task = None
    tiktok_task = None
    twitch_cooldowns: Dict[str, float] = {}
    youtube_cooldowns: Dict[str, float] = {}
    tiktok_cooldowns: Dict[str, float] = {}
    try:
        if data.get("enable_kick"):
            register_kick_client(data["kick_user_id"], key, socket)
            await socket.send({"type": "status", "platform": "kick", "message": f"Kick {data.get('kick_name', '')} listo"})
        if data.get("enable_twitch"):
            twitch_task = asyncio.create_task(twitch_reader_safe(socket, data, twitch_cooldowns))
        if data.get("enable_youtube"):
            youtube_task = asyncio.create_task(youtube_reader_safe(socket, data, youtube_cooldowns))
        if data.get("enable_tiktok"):
            tiktok_task = asyncio.create_task(tiktok_reader_safe(socket, data, tiktok_cooldowns))

        # Browser Source doesn't need to send anything. Waiting here lets us detect disconnects.
        while True:
            await client_ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await socket.send({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if twitch_task:
            twitch_task.cancel()
            try:
                await twitch_task
            except BaseException:
                pass
        if youtube_task:
            youtube_task.cancel()
            try:
                await youtube_task
            except BaseException:
                pass
        if tiktok_task:
            tiktok_task.cancel()
            try:
                await tiktok_task
            except BaseException:
                pass
        if data.get("enable_kick"):
            unregister_kick_client(data["kick_user_id"], key)
        sources = overlay_sources.get(key, [])
        if socket in sources:
            sources.remove(socket)
        if not sources:
            overlay_sources.pop(key, None)
        try:
            await client_ws.close()
        except Exception:
            pass


# Backwards compatibility for old v0.1 overlay pages.
@app.websocket("/ws/twitch")
async def legacy_twitch_ws(client_ws: WebSocket, key: str):
    return await overlay_ws(client_ws, key)


def verify_kick_signature(raw_body: bytes, headers) -> bool:
    message_id = headers.get("Kick-Event-Message-Id", "")
    timestamp = headers.get("Kick-Event-Message-Timestamp", "")
    signature_b64 = headers.get("Kick-Event-Signature", "")
    if not message_id or not timestamp or not signature_b64:
        return False
    signed = message_id.encode() + b"." + timestamp.encode() + b"." + raw_body
    try:
        signature = base64.b64decode(signature_b64)
        KICK_PUBLIC_KEY.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (ValueError, InvalidSignature):
        return False


def remember_kick_message(message_id: str) -> bool:
    if not message_id:
        return True
    if message_id in kick_seen_ids:
        return False
    if len(kick_seen_order) == kick_seen_order.maxlen:
        oldest = kick_seen_order[0]
        kick_seen_ids.discard(oldest)
    kick_seen_order.append(message_id)
    kick_seen_ids.add(message_id)
    return True


@app.post("/webhooks/kick")
async def kick_webhook(request: Request):
    raw = await request.body()
    if not verify_kick_signature(raw, request.headers):
        raise HTTPException(status_code=401, detail="Firma Kick inválida")

    event_type = request.headers.get("Kick-Event-Type", "")
    if event_type != "chat.message.sent":
        return {"ok": True}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    message_id = payload.get("message_id") or request.headers.get("Kick-Event-Message-Id", "")
    if not remember_kick_message(message_id):
        return {"ok": True, "duplicate": True}

    broadcaster = payload.get("broadcaster") or {}
    sender = payload.get("sender") or {}
    broadcaster_id = broadcaster.get("user_id")
    if broadcaster_id is None:
        return {"ok": True}
    try:
        broadcaster_id = int(broadcaster_id)
    except (TypeError, ValueError):
        return {"ok": True}

    display = sender.get("username") or "Kick"
    login = display.lower()
    message = payload.get("content") or ""

    targets = list((kick_clients.get(broadcaster_id) or {}).items())
    dead = []
    for key, socket in targets:
        data = load_overlay_data(key)
        if not data:
            dead.append(key)
            continue
        cooldowns = data.setdefault("kick_cooldowns", {})
        clean = should_read(data, login, message, cooldowns)
        if not clean:
            continue
        spoken = f"{display} dice: {clean}" if data["read_username"] else clean
        try:
            await socket.send({
                "type": "message",
                "platform": "kick",
                "user": display,
                "text": spoken,
                "voice": data["voice"],
                "rate": data["rate"],
                "pitch": data["pitch"],
            })
        except Exception:
            dead.append(key)

    for key in dead:
        unregister_kick_client(broadcaster_id, key)

    return {"ok": True}
