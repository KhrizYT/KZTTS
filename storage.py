import base64
import hashlib
import json
import os
import secrets
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # lets the app still boot before requirements finish / DB is configured
    psycopg = None
    dict_row = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
_FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(("kztts-token:" + SESSION_SECRET).encode()).digest())
FERNET = Fernet(_FERNET_KEY)


def database_configured() -> bool:
    return bool(DATABASE_URL and psycopg is not None)


def _connect():
    if not database_configured():
        raise RuntimeError("Falta DATABASE_URL (PostgreSQL) en Railway")
    return psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row)


def init_db() -> None:
    if not database_configured():
        return
    last_error = None
    for attempt in range(10):
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS kz_accounts (
                            id TEXT PRIMARY KEY,
                            overlay_key TEXT UNIQUE NOT NULL,
                            created_at BIGINT NOT NULL,
                            updated_at BIGINT NOT NULL
                        );
                        CREATE TABLE IF NOT EXISTS kz_provider_accounts (
                            account_id TEXT NOT NULL REFERENCES kz_accounts(id) ON DELETE CASCADE,
                            provider TEXT NOT NULL,
                            provider_user_id TEXT NOT NULL,
                            login TEXT NOT NULL DEFAULT '',
                            display_name TEXT NOT NULL DEFAULT '',
                            access_token_enc TEXT NOT NULL DEFAULT '',
                            refresh_token_enc TEXT NOT NULL DEFAULT '',
                            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                            updated_at BIGINT NOT NULL,
                            PRIMARY KEY (account_id, provider),
                            UNIQUE (provider, provider_user_id)
                        );
                        CREATE INDEX IF NOT EXISTS kz_provider_lookup
                            ON kz_provider_accounts(provider, provider_user_id);
                        CREATE TABLE IF NOT EXISTS kz_tts_configs (
                            account_id TEXT PRIMARY KEY REFERENCES kz_accounts(id) ON DELETE CASCADE,
                            config_json JSONB NOT NULL,
                            updated_at BIGINT NOT NULL
                        );
                        """
                    )
            return
        except Exception as exc:
            last_error = exc
            if attempt == 9:
                raise
            time.sleep(min(1 + attempt, 5))
    if last_error:
        raise last_error


def _encrypt(value: str | None) -> str:
    value = value or ""
    return FERNET.encrypt(value.encode()).decode() if value else ""


def _decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return FERNET.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def create_account(preferred_overlay_key: str | None = None) -> dict:
    now = int(time.time())
    account_id = str(uuid.uuid4())
    overlay_key = preferred_overlay_key or secrets.token_urlsafe(32)
    with _connect() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO kz_accounts(id, overlay_key, created_at, updated_at) VALUES (%s,%s,%s,%s) RETURNING *",
                    (account_id, overlay_key, now, now),
                )
            except Exception:
                # A legacy deterministic key can already belong to the same real user from a prior attempt.
                cur.execute("SELECT * FROM kz_accounts WHERE overlay_key=%s", (overlay_key,))
                row = cur.fetchone()
                if row:
                    return row
                raise
            return cur.fetchone()


def get_account(account_id: str | None) -> dict | None:
    if not account_id or not database_configured():
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kz_accounts WHERE id=%s", (account_id,))
            return cur.fetchone()


def get_account_by_overlay_key(overlay_key: str) -> dict | None:
    if not overlay_key or not database_configured():
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kz_accounts WHERE overlay_key=%s", (overlay_key,))
            return cur.fetchone()


def set_overlay_key(account_id: str, overlay_key: str) -> None:
    now = int(time.time())
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE kz_accounts SET overlay_key=%s, updated_at=%s WHERE id=%s",
                (overlay_key, now, account_id),
            )


def find_account_by_provider(provider: str, provider_user_id: str) -> str | None:
    if not database_configured():
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_id FROM kz_provider_accounts WHERE provider=%s AND provider_user_id=%s",
                (provider, str(provider_user_id)),
            )
            row = cur.fetchone()
            return row["account_id"] if row else None


def account_has_config(account_id: str) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM kz_tts_configs WHERE account_id=%s", (account_id,))
            return cur.fetchone() is not None


def upsert_provider(
    account_id: str,
    provider: str,
    provider_user_id: str,
    login: str,
    display_name: str,
    access_token: str,
    refresh_token: str,
    metadata: dict | None = None,
) -> None:
    now = int(time.time())
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kz_provider_accounts(
                    account_id, provider, provider_user_id, login, display_name,
                    access_token_enc, refresh_token_enc, metadata_json, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (account_id, provider) DO UPDATE SET
                    provider_user_id=EXCLUDED.provider_user_id,
                    login=EXCLUDED.login,
                    display_name=EXCLUDED.display_name,
                    access_token_enc=EXCLUDED.access_token_enc,
                    refresh_token_enc=EXCLUDED.refresh_token_enc,
                    metadata_json=EXCLUDED.metadata_json,
                    updated_at=EXCLUDED.updated_at
                """,
                (
                    account_id,
                    provider,
                    str(provider_user_id),
                    login or "",
                    display_name or "",
                    _encrypt(access_token),
                    _encrypt(refresh_token),
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            cur.execute("UPDATE kz_accounts SET updated_at=%s WHERE id=%s", (now, account_id))


def list_providers(account_id: str | None) -> dict[str, dict]:
    if not account_id or not database_configured():
        return {}
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kz_provider_accounts WHERE account_id=%s", (account_id,))
            rows = cur.fetchall()
    result = {}
    for row in rows:
        meta = row.get("metadata_json") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        item = {
            "provider_user_id": row["provider_user_id"],
            "login": row.get("login") or "",
            "display_name": row.get("display_name") or "",
            "access_token": _decrypt(row.get("access_token_enc")),
            "refresh_token": _decrypt(row.get("refresh_token_enc")),
            **meta,
        }
        # compatibility with existing main.py expectations
        if row["provider"] == "kick":
            try:
                item["user_id"] = int(row["provider_user_id"])
            except Exception:
                item["user_id"] = row["provider_user_id"]
            item.setdefault("name", item.get("display_name") or item.get("login"))
            item.setdefault("slug", item.get("login") or "")
        result[row["provider"]] = item
    return result


def update_provider_tokens(account_id: str, provider: str, access_token: str, refresh_token: str) -> None:
    now = int(time.time())
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kz_provider_accounts
                SET access_token_enc=%s, refresh_token_enc=%s, updated_at=%s
                WHERE account_id=%s AND provider=%s
                """,
                (_encrypt(access_token), _encrypt(refresh_token), now, account_id, provider),
            )


def save_config(account_id: str, config: dict) -> None:
    now = int(time.time())
    # strip purely runtime caches/cooldowns before persistence
    clean = {k: v for k, v in config.items() if not k.endswith("_cooldowns")}
    for key in list(clean):
        if key.startswith("youtube_") and key in {"youtube_channel_id", "youtube_live_video_id", "youtube_live_chat_id"}:
            clean.pop(key, None)
        if key in {"twitch_access_token", "twitch_refresh_token"}:
            clean.pop(key, None)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kz_tts_configs(account_id, config_json, updated_at)
                VALUES (%s,%s::jsonb,%s)
                ON CONFLICT (account_id) DO UPDATE SET
                    config_json=EXCLUDED.config_json,
                    updated_at=EXCLUDED.updated_at
                """,
                (account_id, json.dumps(clean), now),
            )
            cur.execute("UPDATE kz_accounts SET updated_at=%s WHERE id=%s", (now, account_id))


def get_config(account_id: str | None) -> dict | None:
    if not account_id or not database_configured():
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT config_json FROM kz_tts_configs WHERE account_id=%s", (account_id,))
            row = cur.fetchone()
    if not row:
        return None
    data = row["config_json"]
    if isinstance(data, str):
        data = json.loads(data)
    return dict(data)


def get_config_by_overlay_key(overlay_key: str) -> tuple[str, dict] | None:
    if not overlay_key or not database_configured():
        return None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id AS account_id, c.config_json
                FROM kz_accounts a
                JOIN kz_tts_configs c ON c.account_id=a.id
                WHERE a.overlay_key=%s
                """,
                (overlay_key,),
            )
            row = cur.fetchone()
    if not row:
        return None
    data = row["config_json"]
    if isinstance(data, str):
        data = json.loads(data)
    return row["account_id"], dict(data)
