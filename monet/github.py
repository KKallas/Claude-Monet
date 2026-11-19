"""Signing in with GitHub, for the share page only: who is watching a study someone shared.

An OAuth App the operator registers once on GitHub (MONET_GITHUB_ID, MONET_GITHUB_SECRET; its callback is
<host>/auth/github/back). No scope is asked for: GitHub shows only "read your public profile". The token GitHub gives
is used once, to ask who this is, and dropped: Monet keeps no token of anybody's. What is kept is a signed cookie in the
viewer's browser, {GitHub id, login, until}. Their notes go to GitHub as issues they write there themselves.
"""
import base64
import hmac
import json
import os
import secrets
import time
import urllib.parse

import httpx

from . import auth

COOKIE = "monet_gh"
STATE_COOKIE = "monet_gh_state"
DAYS = 30
AUTHORIZE = "https://github.com/login/oauth/authorize"
TOKEN = "https://github.com/login/oauth/access_token"
USER = "https://api.github.com/user"


def configured() -> tuple[str, str] | None:
    cid, csecret = os.environ.get("MONET_GITHUB_ID", "").strip(), os.environ.get("MONET_GITHUB_SECRET", "").strip()
    return (cid, csecret) if cid and csecret else None


def _pack(secret: str, data: dict) -> str:
    value = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{value}.{auth._sign(secret, 'gh:' + value)}"


def _unpack(secret: str, raw) -> dict | None:
    value, _, sig = str(raw or "").partition(".")
    if not value or not sig or not hmac.compare_digest(auth._sign(secret, "gh:" + value), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def safe_next(path) -> str:
    """Where to go back to after signing in: only a share page of this server."""
    path = str(path or "")
    return path if path.startswith("/s/") and "//" not in path and "\\" not in path and len(path) < 200 else "/"


def start(secret: str, next_path: str, callback: str) -> tuple[str, str]:
    """(GitHub's address to send the browser to, the value of the short cookie that goes with it). The state carries
    where to come back to and a nonce that must come back in that cookie: a sign-in started elsewhere is refused."""
    cid, _ = configured()
    nonce = secrets.token_urlsafe(16)
    state = _pack(secret, {"next": safe_next(next_path), "nonce": nonce, "until": int(time.time()) + 600})
    query = urllib.parse.urlencode({"client_id": cid, "redirect_uri": callback, "state": state, "allow_signup": "true"})
    return f"{AUTHORIZE}?{query}", nonce


def back(secret: str, code, state, nonce_cookie, callback: str, client: httpx.Client | None = None) -> tuple[dict, str]:
    """GitHub sent the browser back: (who it is {id, login, until}, where to go). Raises ValueError when anything is off."""
    got = _unpack(secret, state)
    if not got or not nonce_cookie or not hmac.compare_digest(str(got.get("nonce")), str(nonce_cookie)) or got.get("until", 0) < time.time():
        raise ValueError("this sign-in was not started here, or took too long: start it again")
    if not code or len(str(code)) > 200:
        raise ValueError("GitHub sent no code back")
    cid, csecret = configured()
    with (client or httpx.Client(timeout=15)) as http:
        token = http.post(TOKEN, data={"client_id": cid, "client_secret": csecret, "code": code, "redirect_uri": callback},
                          headers={"Accept": "application/json"}).json().get("access_token")
        if not token:
            raise ValueError("GitHub did not let this sign-in through: start it again")
        me = http.get(USER, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}).json()
    del token      # used once, to ask who this is: never kept
    if not isinstance(me.get("id"), int) or not isinstance(me.get("login"), str):
        raise ValueError("GitHub did not say who this is")
    return {"id": me["id"], "login": me["login"], "until": int(time.time()) + DAYS * 86400}, safe_next(got.get("next"))


def cookie(secret: str, who: dict, secure: bool) -> str:
    return f"{COOKIE}={_pack(secret, who)}; Path=/; Max-Age={DAYS * 86400}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")


def state_cookie(nonce: str, secure: bool) -> str:
    return f"{STATE_COOKIE}={nonce}; Path=/auth/github; Max-Age=600; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")


def viewer(secret: str, cookies: dict) -> dict | None:
    """Who is watching, from their cookie: {id, login}, or None (not signed in, or the cookie is old or not ours)."""
    who = _unpack(secret, cookies.get(COOKIE))
    if not who or not isinstance(who.get("id"), int) or not isinstance(who.get("login"), str) or who.get("until", 0) < time.time():
        return None
    return who
