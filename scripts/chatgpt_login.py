"""Authorize Horsie's own optional ChatGPT connection using the public OAuth flow."""
import asyncio
import base64
import hashlib
import json
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "siwc_deps"))

import aiohttp
from aiohttp import web
from horsie.chatgpt_fallback import ISSUER, RESOURCE, TOKEN_ENDPOINT, auth_path, save_auth, load_auth, ChatGPTError
from horsie.data_storage import write_json


def authorization(host, redirect, client_id="dynamic_agent_client"):
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = {"client_id": client_id, "ext_agent_host_id": host, "response_type": "code",
        "redirect_uri": redirect, "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
        "resource": RESOURCE, "state": state, "nonce": nonce,
        "code_challenge_method": "S256", "code_challenge": challenge}
    if client_id == "dynamic_agent_client":
        query["agent_name_hint"] = "Horsie"
    return ISSUER + "/api/accounts/authorize?" + urlencode(query), state, nonce, verifier


async def validate_identity(session, token, client_id, nonce):
    import jwt
    async with session.get(ISSUER + "/.well-known/jwks.json", allow_redirects=False) as response:
        if response.status != 200:
            raise ChatGPTError("Could not verify the sign-in issuer.")
        keys = await response.json()
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise ChatGPTError("The sign-in used an unexpected signature algorithm.")
    matches = [key for key in keys["keys"] if key.get("kid") == header.get("kid")]
    if len(matches) != 1:
        raise ChatGPTError("Could not verify the sign-in signing key.")
    key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
    claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=ISSUER,
                        audience=client_id, leeway=5, options={"require": ["sub", "exp", "iat", "nonce"]})
    if not secrets.compare_digest(claims["nonce"], nonce) or not isinstance(claims["sub"], str) or not claims["sub"]:
        raise ChatGPTError("The sign-in identity did not match this attempt.")
    return claims["sub"]


async def login():
    try:
        import jwt
    except ImportError:
        raise ChatGPTError('Install the login dependency first: python -m pip install --target data/siwc_deps "PyJWT[crypto]>=2.10,<3"')
    path = auth_path()
    host_path = path.with_name("horse_chatgpt_host.json")
    if host_path.exists():
        host = json.loads(host_path.read_text())["ext_agent_host_id"]
    else:
        host = "urn:uuid:" + str(uuid.uuid4())
        write_json(host_path, {"ext_agent_host_id": host})
    previous = load_auth(path) if path.exists() else None
    client_id = previous["client_id"] if previous else "dynamic_agent_client"
    completed = asyncio.get_running_loop().create_future()
    used = False
    state = nonce = verifier = redirect = None

    async def callback(request):
        nonlocal used
        if used or not secrets.compare_digest(request.query.get("state", ""), state):
            return web.Response(status=400, text="This sign-in attempt is invalid. Start again from Horsie.")
        used = True
        try:
            if request.query.get("error"):
                raise ChatGPTError("ChatGPT sign-in was declined or unavailable for this account.")
            issued = request.query.get("client_id", client_id)
            if (not issued.startswith("oaiapp_") or (previous and issued != client_id)
                    or not request.query.get("code")):
                raise ChatGPTError("ChatGPT registration did not return a valid client and code.")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.post(TOKEN_ENDPOINT, data={"grant_type": "authorization_code", "client_id": issued,
                    "code": request.query["code"], "code_verifier": verifier,
                    "redirect_uri": redirect, "resource": RESOURCE}, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ChatGPTError("ChatGPT could not complete this authorization. Please start again.")
                    tokens = await response.json()
                subject = await validate_identity(session, tokens["id_token"], issued, nonce)
                if previous and subject != previous["subject"]:
                    raise ChatGPTError("The selected ChatGPT account did not match the saved registration.")
                scopes = tokens.get("scope", "").split()
                if "chatgpt.tokens.use.direct" not in scopes:
                    raise ChatGPTError("This sign-in did not grant ChatGPT plan usage.")
                async with session.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + tokens["access_token"]},
                                       allow_redirects=False) as response:
                    if response.status != 200:
                        raise ChatGPTError("The account did not provide a ChatGPT plan model catalog.")
                    catalog = await response.json()
                models = [item["slug"] for item in catalog.get("models", [])
                          if item.get("visibility") == "list" and isinstance(item.get("slug"), str)]
                if not models:
                    raise ChatGPTError("No eligible ChatGPT models were available for this account.")
            record = {"issuer": ISSUER, "subject": subject, "client_id": issued, "ext_agent_host_id": host,
                "scopes": scopes, "model": models[0], "expires_at": time.time() + float(tokens["expires_in"])}
            record.update({key: tokens[key] for key in ("access_token", "refresh_token", "id_token")})
            await asyncio.to_thread(save_auth, path, record)
            print("Horsie's separate ChatGPT connection is authorized. Selected model:", models[0], flush=True)
            print("Private ChatGPT conversations and memories were not requested or imported.", flush=True)
            completed.set_result(True)
            return web.Response(text="Horsie is connected. Eligible requests use your ChatGPT plan. "
                "No private ChatGPT chats or memories were imported. Manage app usage in ChatGPT Settings. "
                "The fallback remains disabled until enabled in Horsie's settings. You can close this tab.")
        except Exception:
            # Never print exception bodies: OAuth responses may contain secrets.
            completed.set_result(False)
            return web.Response(status=400, text="Horsie could not complete sign-in. No new connection was saved. "
                                "Account eligibility or the authorization could not be verified.")

    app = web.Application()
    app.router.add_get("/auth/callback", callback)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        redirect = f"http://127.0.0.1:{port}/auth/callback"
        url, state, nonce, verifier = authorization(host, redirect, client_id)
        print("Continue with ChatGPT (valid for 5 minutes):", flush=True)
        print(url, flush=True)
        print("This authorizes Horsie to use eligible ChatGPT plan requests, without reading existing chats.", flush=True)
        if not await asyncio.wait_for(asyncio.shield(completed), 300):
            raise ChatGPTError("Sign-in could not be completed; no new credentials were saved.")
        await asyncio.sleep(1)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(login())
    except (ChatGPTError, asyncio.TimeoutError) as error:
        print(str(error) if isinstance(error, ChatGPTError) else "Sign-in timed out. Run the login helper again.", flush=True)
        sys.exit(1)
