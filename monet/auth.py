"""Users and who is asking (from Adam Designer / Nerva, in Python).

A username the admin hands out, a card, a password. The card is a login link (and its
QR) carrying a random UUID: it says who you are, like a username you do not have to
type; the password proves it. A new user has no password: the first visit by card asks
for one. Typing only a username cannot set a first password, so knowing someone's
username is not enough to claim their account.

New here: the agent key. Each user has one; it is in the link their own LLM harness
(Claude Desktop, Claude Code, anything that speaks MCP or HTTPS) connects with, because
such a harness cannot log in. What comes in with the key is "the agent": it works in
that user's workspace and can write Notes and add checks, but it cannot change, loosen
or remove a check, nor wave through a red load check. Those need the person, logged in.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid
from pathlib import Path

from .store import Store, now

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{24,48}$")
MIN_PASSWORD = 8
COOKIE = "monet"
YEAR = 365 * 24 * 3600
TRIES, WAIT = 8, 10 * 60     # a handful of wrong passwords, then a short wait


class HttpError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = _b64(os.urandom(16))
    h = hashlib.scrypt(str(password).encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt}${_b64(h)}"


def check_password(user: dict | None, password) -> bool:
    if not user or not user.get("password"):
        return False
    try:
        kind, salt, want = user["password"].split("$")
        want = _unb64(want)
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(str(password or "").encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=len(want))
    return hmac.compare_digest(want, got)


def password_problem(p) -> str | None:
    return f"a password needs at least {MIN_PASSWORD} characters" if len(str(p or "")) < MIN_PASSWORD else None


def _clean(v) -> str:
    return str(v or "").strip().lower()


def find_by_username(store: Store, username) -> dict | None:
    want = _clean(username)
    return next((u for u in store.users.values() if u["username"] == want), None)


def find_by_card(store: Store, card) -> dict | None:
    want = _clean(card)
    return next((u for u in store.users.values() if u["card"] == want), None) if want else None


def find_by_key(store: Store, key) -> dict | None:
    key = str(key or "")
    if not KEY_RE.match(key):
        return None
    return next((u for u in store.users.values() if u.get("key") and hmac.compare_digest(u["key"], key)), None)


def new_key() -> str:
    return secrets.token_urlsafe(24)


def make_user(store: Store, username=None, name=None, role=None, limit: int | None = None) -> dict:
    username = _clean(username)
    if not USERNAME_RE.match(username):
        raise HttpError(400, "a username is 2-32 letters, digits, dots, dashes or underscores")
    if find_by_username(store, username):
        raise HttpError(409, f'"{username}" is taken')
    if limit is not None and len(store.users) >= limit:
        raise HttpError(409, f"this instance takes {limit} users and has them: remove one, or raise MONET_MAX_USERS")
    return store.save_user({
        "id": str(uuid.uuid4()),
        "username": username,
        "name": str(name or "").strip()[:80] or username,
        "role": "admin" if role == "admin" else "user",
        "card": str(uuid.uuid4()),
        "key": new_key(),
        "password": None,
        "session": 1,
        "createdAt": now(),
    })


def ensure_admin(store: Store) -> dict:
    """The built-in admin always exists, and is never deleted or demoted, so an instance
    can never lock itself out of user management."""
    found = next((u for u in store.users.values() if u.get("builtin")), None)
    if found:
        return found
    admin = make_user(store, "monet-admin" if find_by_username(store, "admin") else "admin", "Admin", "admin")
    admin["builtin"] = True
    return store.save_user(admin)


def public_user(u: dict | None, with_card: bool = False) -> dict | None:
    """What the browser may see. Never the hash or the agent key; the card only for admins."""
    if not u:
        return None
    out = {k: u.get(k) for k in ("id", "username", "name", "role", "createdAt")}
    out.update(builtin=bool(u.get("builtin")), hasPassword=bool(u.get("password")), lastSeen=u.get("lastSeen"), lastAgent=u.get("lastAgent"))
    if with_card:
        out["card"] = u["card"]
    return out


# ---- who is asking ---------------------------------------------------------------

def session_secret(store: Store) -> str:
    """SESSION_SECRET from the environment, or one made up once and kept in data/, so that
    a fresh checkout works and logins survive a restart."""
    env = os.environ.get("SESSION_SECRET", "")
    if len(env) >= 16:
        return env
    file = Path(store.dir) / "session-secret"
    if not file.exists():
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_urlsafe(32))
    return file.read_text().strip()


def _sign(secret: str, value: str) -> str:
    return _b64(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())


def cookie_for(secret: str, user: dict) -> str:
    """"<user id>.<session>.<signature>". Bumping user.session (a password reset or change)
    ends every cookie issued before it."""
    value = f"{user['id']}.{user.get('session') or 1}"
    return f"{value}.{_sign(secret, value)}"


def user_from_cookie(store: Store, secret: str, raw) -> dict | None:
    parts = str(raw or "").split(".")
    if len(parts) != 3 or not all(parts):
        return None
    uid, session, sig = parts
    if not hmac.compare_digest(_sign(secret, f"{uid}.{session}"), sig):
        return None
    user = store.users.get(uid)
    return user if user and str(user.get("session") or 1) == session else None


def identify(store: Store, secret: str, cookies: dict, authorization: str | None) -> tuple[dict | None, bool]:
    """(user, via cookie?): by the cookie of the login page, else by HTTP Basic (curl -u mari:password) for scripts."""
    user = user_from_cookie(store, secret, cookies.get(COOKIE))
    if user:
        return user, True
    auth = authorization or ""
    if auth[:6].lower() == "basic ":
        try:
            name, _, password = base64.b64decode(auth[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None, False
        candidate = find_by_username(store, name)
        if candidate and check_password(candidate, password):
            return candidate, False
    return None, False


def session_cookie(secret: str, user: dict, secure: bool) -> str:
    return f"{COOKIE}={cookie_for(secret, user)}; Path=/; Max-Age={YEAR}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")


CLEAR_COOKIE = f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


class Throttle:
    """Kept in memory: a restart forgives."""

    def __init__(self):
        self.failures: dict[str, tuple[int, float]] = {}

    def too_many(self, key: str) -> bool:
        n, at = self.failures.get(key, (0, 0.0))
        return n >= TRIES and time.time() - at < WAIT

    def fail(self, key: str) -> None:
        n, at = self.failures.get(key, (0, 0.0))
        self.failures[key] = ((n + 1) if time.time() - at < WAIT else 1, time.time())

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)


def login(store: Store, throttle: Throttle, ip: str, card=None, username=None, password=None) -> dict:
    """A username or a card, then a password. The first visit by card sets the password
    instead of asking for it."""
    user = find_by_card(store, card) if card else find_by_username(store, username)
    key = f"{ip}|{_clean(card or username)}"
    if throttle.too_many(key):
        raise HttpError(429, "too many wrong passwords: wait ten minutes")
    if not user:
        throttle.fail(key)
        raise HttpError(401, "this card is not valid any more" if card else "wrong username or password")
    if not user.get("password"):
        if not card:
            raise HttpError(400, "no password yet: open the card link you were given to choose one", needsCard=True)
        problem = password_problem(password)
        if problem:
            raise HttpError(400, problem)
        user["password"] = hash_password(str(password))
        user["passwordSetAt"] = now()
        store.log(type="password-set", user=user["username"], who=user["username"])
    elif not check_password(user, password):
        throttle.fail(key)
        store.log(type="login-failed", user=user["username"], ip=ip)
        raise HttpError(401, "wrong password" if card else "wrong username or password")
    throttle.clear(key)
    user["lastSeen"] = now()
    store.save_user(user)
    store.log(type="login", user=user["username"], ip=ip)
    return user
