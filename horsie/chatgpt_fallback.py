"""Opt-in ChatGPT plan fallback. Never reads ChatGPT chats or other app credentials."""
import asyncio
import base64
import ctypes
import json
import math
import os
import tempfile
import time
from pathlib import Path

import aiohttp

from horsie.ai_usage import record_api_usage
from horsie.data_storage import data_path


ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
PRIVACY = ("You have access only to the Discord context supplied in this request. "
           "You cannot access the subscription owner's ChatGPT conversations, memories, "
           "profile or other channels. Never claim to know, infer or reveal private facts "
           "from those sources, including weight, diet or calorie tracking. If asked, "
           "explain that you do not have access to that private information.")
REFRESH_LOCK = asyncio.Lock()
blocked_until = 0


class ChatGPTError(Exception):
    """Safe failure text; never includes provider bodies or credentials."""


def auth_path():
    return data_path("HORSE_CHATGPT_AUTH_FILE", "horse_chatgpt_auth.json")


def enabled():
    return os.getenv("CHATGPT_LAST_RESORT", "").lower() == "true" and (
        auth_path().is_file() or bool(os.getenv("HORSE_CHATGPT_AUTH_BOOTSTRAP", "")))


def require_usage_guard():
    # Explicit owner opt-out only; the default preserves the strict 75% rule.
    return os.getenv("CHATGPT_REQUIRE_USAGE_GUARD", "true").lower() != "false"


def bootstrap_auth():
    path = auth_path()
    if path.exists():
        return
    seed = os.getenv("HORSE_CHATGPT_AUTH_BOOTSTRAP", "")
    if not seed:
        raise ChatGPTError("No ChatGPT connection has been configured.")
    record = json.loads(base64.b64decode(seed))
    # The remote runtime has its own host identity, distinct from the login PC.
    import uuid
    record["ext_agent_host_id"] = "urn:uuid:" + str(uuid.uuid4())
    save_auth(path, record)
    load_auth(path)


def windows_protect(data, decrypt=False):
    """Use Windows user-bound encryption, rather than plaintext Windows files."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.windll.crypt32
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    # CRYPTPROTECT_UI_FORBIDDEN: credentials never trigger an unattended dialog.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Could not protect ChatGPT credentials for this Windows user.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def save_auth(path, record):
    """Atomically save only Horsie's own registration with protected storage."""
    path = Path(path)
    raw = json.dumps(record).encode()
    if os.name == "nt":
        raw = json.dumps({"protection": "windows-dpapi", "data": base64.b64encode(windows_protect(raw)).decode()}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".chatgpt-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_auth(path):
    if Path(path).stat().st_size > 64 * 1024:
        raise ChatGPTError("The saved ChatGPT registration is invalid.")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ChatGPTError("The saved ChatGPT registration is invalid.")
    if raw.get("protection") == "windows-dpapi":
        if os.name != "nt":
            raise ChatGPTError("Import credentials securely for this host before enabling ChatGPT.")
        raw = json.loads(windows_protect(base64.b64decode(raw["data"]), decrypt=True))
    if (not isinstance(raw, dict) or raw.get("issuer") != ISSUER or not str(raw.get("client_id", "")).startswith("oaiapp_")
            or "chatgpt.tokens.use.direct" not in raw.get("scopes", [])
            or not all(isinstance(raw.get(key), str) and raw[key] for key in ("subject", "access_token", "refresh_token", "ext_agent_host_id"))):
        raise ChatGPTError("Horsie's ChatGPT sign-in needs attention. Please sign in again.")
    return raw


async def access_record(session):
    async with REFRESH_LOCK:
        await asyncio.to_thread(bootstrap_auth)
        record = await asyncio.to_thread(load_auth, auth_path())
        if record.get("expires_at", 0) > time.time() + 60:
            return record
        async with session.post(TOKEN_ENDPOINT, data={"grant_type": "refresh_token",
            "client_id": record["client_id"], "refresh_token": record["refresh_token"],
            "resource": RESOURCE}, allow_redirects=False) as response:
            if response.status != 200:
                raise ChatGPTError("Horsie's ChatGPT sign-in expired or could not refresh. Please sign in again.")
            tokens = await response.json()
        scopes = tokens.get("scope", " ".join(record["scopes"])).split()
        if not isinstance(tokens.get("access_token"), str) or "chatgpt.tokens.use.direct" not in scopes:
            raise ChatGPTError("ChatGPT plan usage was not authorized.")
        updated = {**record, "access_token": tokens["access_token"], "scopes": scopes,
                   "expires_at": time.time() + float(tokens["expires_in"])}
        for key in ("refresh_token", "id_token"):
            if tokens.get(key):
                updated[key] = tokens[key]
        await asyncio.to_thread(save_auth, auth_path(), updated)
        return updated


def response_payload(messages, model):
    """Whitelist request data; no ChatGPT history IDs, tools or account profile."""
    instructions = [item["content"] for item in messages if item.get("role") == "system"]
    inputs = [{"role": item["role"], "content": item["content"]} for item in messages
              if item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str)]
    return {"model": model, "instructions": "\n\n".join(instructions + [PRIVACY]),
            "input": inputs, "store": False, "stream": True}


def reported_usage(response):
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details") or {}
    return {"usage": {"prompt_tokens": usage.get("input_tokens"),
                      "completion_tokens": usage.get("output_tokens"),
                      "prompt_tokens_details": {"cached_tokens": details.get("cached_tokens", 0)}}}


def usage_admitted(snapshot):
    """Admission requires fresh account-wide telemetry, never local token estimates.

    No documented SIWC source for this telemetry has been verified yet. The
    caller therefore supplies no snapshot and the integration stays fail-closed.
    This is deliberately not a manually entered percentage or a Codex quota.
    """
    if not isinstance(snapshot, dict) or snapshot.get("source") != "verified-chatgpt-plan":
        return False
    percent, observed, reset = (snapshot.get(key) for key in ("used_percent", "observed_at", "reset_at"))
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (percent, observed, reset)):
        return False
    return 0 <= percent < 75 and 0 <= time.time() - observed <= 15 and reset > time.time()


async def completion(messages, plan_usage=None):
    global blocked_until
    if not enabled() or time.monotonic() < blocked_until:
        raise ChatGPTError("ChatGPT fallback is not currently available.")
    if require_usage_guard() and not usage_admitted(plan_usage):
        raise ChatGPTError("ChatGPT fallback is paused: usage is at 75% or the shared Plus percentage cannot be verified.")
    model, status, measured = "unselected", 0, None
    attempted = False
    try:
        async with asyncio.timeout(15), aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            record = await access_record(session)
            if require_usage_guard() and plan_usage.get("subject") != record["subject"]:
                raise ChatGPTError("The usage reading does not match the authorized ChatGPT account.")
            model = os.getenv("CHATGPT_FALLBACK_MODEL", "").strip() or record.get("model", "")
            if not model:
                raise ChatGPTError("Select a ChatGPT fallback model during setup.")
            attempted = True
            async with session.post(RESOURCE + "/responses", headers={"Authorization": "Bearer " + record["access_token"]},
                json=response_payload(messages, model), allow_redirects=False) as response:
                status = response.status
                if status != 200:
                    blocked_until = time.monotonic() + 60
                    raise ChatGPTError("ChatGPT fallback could not answer. Check its sign-in and usage settings.")
                data_lines = []
                async for raw in response.content:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        event = json.loads("\n".join(data_lines))
                        data_lines = []
                        if event.get("type") in ("response.failed", "response.incomplete", "error"):
                            status = 0
                            blocked_until = time.monotonic() + 60
                            raise ChatGPTError("ChatGPT fallback could not complete the reply.")
                        if event.get("type") == "response.completed":
                            result = event["response"]
                            measured = reported_usage(result)
                            # Buffer until completed: never send partial answers as success.
                            answer = "".join(part.get("text", "") for item in result.get("output", [])
                                if item.get("type") == "message" for part in item.get("content", [])
                                if part.get("type") == "output_text")
                            if answer.strip():
                                print(f"Horsie ChatGPT last resort used: model={model}", flush=True)
                                return answer.strip()[:6000]
                status = 0
                raise ChatGPTError("ChatGPT fallback ended without a completed reply.")
    except (OSError, ValueError, TypeError, KeyError, aiohttp.ClientError, asyncio.TimeoutError) as error:
        blocked_until = time.monotonic() + 60
        status = 0
        raise ChatGPTError("ChatGPT fallback is unavailable. Check its connection and sign-in.") from error
    finally:
        if attempted:
            await record_api_usage("chat", "chatgpt/" + model, status, measured, retry=True)
