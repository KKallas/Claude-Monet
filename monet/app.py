"""The web app: one process. The canvas and its API for the person, the agent's door
(MCP and plain HTTP) for their own LLM harness, and the accounts.

People are let in by an admin (monet/auth.py): a username, a card, a password. Each has one
workspace. In the browser it is /w/<username>, behind the login. Their agent, which cannot
log in, comes through /w/<agent key>/agent and /w/<agent key>/mcp: the key is in the link the
canvas shows them, and it opens only what an agent may do.
"""
import contextlib
import inspect
import io
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, agent, auth, note as notes, tags as tagging
from .store import Store, now
from .workspace import EXPORTS, Problem, Workspaces

ROOT = Path(__file__).resolve().parent.parent
CANVAS = ROOT / "canvas"
MCP_PATH = re.compile(r"^/w/([A-Za-z0-9_-]{24,48})/mcp/?$")
NO_STORE = {"Cache-Control": "no-store"}


def version() -> dict:
    commit = os.environ.get("COMMIT", "")
    if not commit:
        try:
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            commit = ""
    return {"name": "Monet", "version": __version__, "commit": commit or "unknown",
            # AGPL: whoever can reach an instance must be able to reach its source
            "source": os.environ.get("MONET_SOURCE_URL", "https://github.com/KKallas/Claude-Monet"),
            "license": "AGPL-3.0-or-later", "note": os.environ.get("MONET_NOTE", "")}


def base_url(headers, scheme: str = "http") -> str:
    fixed = os.environ.get("MONET_BASE_URL", "").rstrip("/")
    if fixed:
        return fixed
    proto = (headers.get("x-forwarded-proto") or scheme).split(",")[0].strip()
    return f"{proto}://{headers.get('host', 'localhost')}"


def coerce(value, annotation):
    """A query string only has text: read it as what the tool's argument is."""
    if not isinstance(value, str):
        return value
    kind = str(annotation)
    low = value.strip().lower()
    if "bool" in kind and low in ("true", "false", "1", "0", "yes", "no"):
        return low in ("true", "1", "yes")
    if "float" in kind:
        if low in ("", "none", "null"):
            return None
        try:
            return float(value)
        except ValueError:
            raise Problem(f"{value!r} is not a number")
    if "int" in kind:
        try:
            return int(low)
        except ValueError:
            raise Problem(f"{value!r} is not a whole number")
    return value


def tool_docs() -> dict:
    out = {}
    for name, fn in agent.TOOLS.items():
        params = [p for k, p in inspect.signature(fn).parameters.items() if k != "c"]
        out[name] = {"args": {p.name: ("required" if p.default is inspect.Parameter.empty else f"default {p.default!r}") for p in params},
                     "changes_things": name not in agent.READ_ONLY, "doc": inspect.cleandoc(fn.__doc__)}
    return out


def docs(base: str) -> str:
    """The API, written for an LLM that was only given this address."""
    tools = []
    for name, d in tool_docs().items():
        args = ", ".join(f"{k} ({v})" for k, v in d["args"].items()) or "no arguments"
        tools.append(f"### {name}{'  (changes things)' if d['changes_things'] else ''}\n\n{d['doc']}\n\nArguments: {args}\n")
    return f"""# Monet API

Monet is a CAD workspace for 3D-printed parts. You (an LLM agent) write each part as a small Python file, a
"Note", using build123d. This server builds it, measures it, runs the user's checks, draws pictures, keeps
saved versions and exports files for printing. The human watches in a browser canvas and clicks the faces they mean.

Everything is plain HTTPS, with no headers and no login of your own: the user's agent key, in the address,
is your access to their workspace.

## 1. Your address

You need the user's **agent link**. It looks like {base}/w/AGENT-KEY and they find it in their canvas under
"Connect your agent" (people are let into an instance by its admin; there is no way to sign up from here). If
you were not given one, ask for it. Treat it as a password: it is theirs, do not show it to anyone else or put
it where others can read it. Below, KEY stands for the agent key in that link: put the real one in its place.

## 2. Call tools

    GET  {base}/w/KEY/agent/TOOL?arg=value&arg=value
    POST {base}/w/KEY/agent/TOOL          with a JSON object of arguments

Both do the same; the order of the arguments does not matter. (This page puts `note` first on purpose: some
page readers turn the letters "&not" into another sign.) Answers are JSON. A mistake of yours comes back as {{"error": "what was wrong", "status": 4xx}}:
by POST with that HTTP status, by GET inside a 200 (so that a fetch tool which hides failed pages still shows it
to you). Always look for `error` in the answer.

Sending a Note (write_note) needs its whole source. Any of these works:

    POST .../agent/write_note   JSON {{"project": "...", "note": "...", "source": "..."}}
    POST .../agent/write_note?note=...&project=...     with the Python source as the body (Content-Type: text/plain)
    GET  .../agent/write_note?note=...&project=...&source=THE-SOURCE-URL-ENCODED
    GET  .../agent/write_note?note=...&project=...&source_b64=THE-SOURCE-AS-BASE64URL

**If you can only GET, send a Note in parts.** Many fetch tools fail on a long address, without saying why, and
a Note does not fit in a short one. So cut the file into parts of a few whole lines each, small enough that every
address stays under about 700 characters after encoding, and fetch one address per part:

    GET .../agent/write_note?note=cube&project=demo&upload=k7&part=1&of=3&source=THE-FIRST-LINES-URL-ENCODED
    GET .../agent/write_note?note=cube&project=demo&upload=k7&part=2&of=3&source=THE-NEXT-LINES
    GET .../agent/write_note?note=cube&project=demo&upload=k7&part=3&of=3&source=THE-LAST-LINES

- `upload` is a short word you make up: the same in every part of one upload, a new one for every upload.
- A part is whole lines, with their indentation. The server puts a line break between parts, so do not end a
  part in the middle of a line. In the address a line break inside a part is %0A, a space %20, a quote %22.
- Any order, all at once if your tool can, and again if a fetch failed: sending a part twice does no harm.
- Each answer says `written: false` and lists what is `missing`. The answer to the part that completes the file
  has `written: true` and is the report (built, checks, green). If that answer got lost, send any part again:
  you get the report.
- If you can run code but only GET: base64url the whole file, cut that string anywhere, and send the pieces as
  `source_b64` instead of `source`, the same way.

Pictures: `look` answers with `image`, the address of a PNG. Fetch it and look at it.
Files: `export` answers with `url`, the address of the 3MF / STL / STEP / GLB. Both addresses carry the agent
key. The `canvas` links in the answers are for the user: they open in a browser, behind their login.

Start with `guide` (the Note format, tags, checks, the loop to follow, the rules that are not yours to bend),
then `status`.

    GET {base}/w/KEY/agent/guide
    GET {base}/w/KEY/agent/status

## 3. The rules in one breath

Read a Note before you edit it. Send the whole file. Look at the picture, do not assume. A red check means
fix the geometry, never the check: checks belong to the user (you can add one, not change or remove one). Save
only when everything is green. If the load check of a saved Note is red, stop and tell the user. If you can
write files and run git on the user's computer, keep the Notes in a local folder and commit after every
successful save: the history is theirs.

## Tools

{chr(10).join(tools)}
## Also

- `GET {base}/w/KEY/agent` lists the tools as JSON.
- MCP (Claude Desktop, Claude Code and others): `{base}/w/KEY/mcp` (streamable HTTP).
- What only the person can do, logged in at their canvas: change or remove a check, acknowledge a load check,
  delete a Note. The agent key does not open those.
- Source: {version()["source"]} ({version()["license"]}).
"""


def create_app(storage: str | Path, data: str | Path | None = None, max_users: int = 20, templates: str | Path | None = None,
               profiles: str | Path | None = None) -> Starlette:
    workspaces = Workspaces(storage, templates or ROOT / "notes", profiles or ROOT / "profiles")
    store = Store(data if data is not None else Path(storage).resolve().parent / "data")
    admin = auth.ensure_admin(store)
    secret = auth.session_secret(store)
    throttle = auth.Throttle()
    info = version()

    def caller(ws, owner, headers, scheme="http") -> agent.Caller:
        base = base_url(headers, scheme)
        return agent.Caller(ws, f"{base}/w/{owner['key']}", f"{base}/w/{owner['username']}")

    def me(request: Request) -> dict | None:
        return auth.identify(store, secret, request.cookies, request.headers.get("authorization"))[0]

    def secure(request: Request) -> bool:
        return (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip() == "https"

    def seen(owner: dict) -> None:
        """When this user's agent was last here: for the admin's eye. Written at most once a minute."""
        stamp = now()
        if (owner.get("lastAgent") or "")[:16] != stamp[:16]:
            owner["lastAgent"] = stamp
            store.save_user(owner)

    # ---- the agent's door, as MCP -------------------------------------------------
    def caller_from_mcp(headers) -> agent.Caller:
        owner = store.users.get(headers.get("x-monet-user", ""))
        if owner is None:
            raise ValueError("no such workspace")
        seen(owner)
        return caller(workspaces.of(owner["id"], owner["name"]), owner, headers)

    from mcp.server.transport_security import TransportSecuritySettings
    mcp = agent.mcp_server(caller_from_mcp)
    # the agent key in the address is the secret, not an ambient cookie: nothing for a rebound DNS name to ride on
    mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    # ---- helpers ------------------------------------------------------------------
    async def body_of(request: Request):
        if request.method not in ("POST", "PUT"):
            return {}
        raw = await request.body()
        if raw and "json" not in request.headers.get("content-type", "json"):
            return {"_raw": raw.decode("utf-8", "replace")}      # a Note sent as plain text
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            raise Problem("the body is not JSON")
        if not isinstance(body, dict):
            raise Problem("the body must be a JSON object")
        return body

    def inside(request, owner, fn):
        """Run fn(request, ws, body) in the workspace of `owner`, off the event loop; a Problem is the caller's."""
        async def go():
            try:
                body = await body_of(request)
                request.state.owner = owner
                out = await run_in_threadpool(lambda: fn(request, workspaces.of(owner["id"], owner["name"]), body))
            except Problem as e:
                return JSONResponse({"error": str(e)}, e.status)
            return out if isinstance(out, Response) else JSONResponse(out, headers=NO_STORE)
        return go()

    def api(fn):
        """The person's door: /w/<username>/…, behind the login. Theirs, or an admin looking in."""
        async def endpoint(request: Request):
            user = me(request)
            if user is None:
                return JSONResponse({"error": "log in first", "login": True}, 401)
            owner = auth.find_by_username(store, request.path_params["wid"])
            if owner is None or (owner["id"] != user["id"] and user["role"] != "admin"):
                return JSONResponse({"error": "no such workspace"}, 404)
            request.state.me = user
            return await inside(request, owner, fn)
        return endpoint

    def door(fn):
        """The agent's door: /w/<agent key>/…. The key says whose agent it is; it opens only what an agent may do."""
        async def endpoint(request: Request):
            owner = auth.find_by_key(store, request.path_params["wid"])
            if owner is None:
                why = "this agent link is not valid (any more): ask the user for the one in their canvas, under Connect your agent"
                return JSONResponse({"error": why, "status": 404}, 200 if request.method == "GET" else 404)
            seen(owner)
            return await inside(request, owner, fn)
        return endpoint

    def note_of(request, ws):
        return ws.project(request.path_params["project"]), request.path_params["note"]

    # ---- pages --------------------------------------------------------------------
    async def home(request: Request):
        user = me(request)
        return RedirectResponse(f"/w/{user['username']}" if user else "/login", 302)

    async def login_page(_request: Request):
        return FileResponse(CANVAS / "login.html", headers=NO_STORE)

    async def users_page(request: Request):
        user = me(request)
        if user is None:
            return RedirectResponse("/login?next=/users", 302)
        if user["role"] != "admin":
            return RedirectResponse(f"/w/{user['username']}", 302)
        return FileResponse(CANVAS / "users.html", headers=NO_STORE)

    async def canvas(request: Request):
        user, wid = me(request), request.path_params["wid"]
        if user is None:
            return RedirectResponse(f"/login?next=/w/{wid}", 302)
        owner = auth.find_by_username(store, wid)
        if owner is None or (owner["id"] != user["id"] and user["role"] != "admin"):
            return RedirectResponse(f"/w/{user['username']}", 302)
        return FileResponse(CANVAS / "index.html", headers=NO_STORE)

    async def get_version(_request: Request):
        return JSONResponse({**info, "templates": workspaces.template_names()}, headers=NO_STORE)

    async def skill_zip(_request: Request):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted((ROOT / "skill" / "monet").rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, Path("monet") / f.relative_to(ROOT / "skill" / "monet"))
        return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="monet-skill.zip"'})

    # ---- logging in (from Adam Designer) ------------------------------------------
    def fail(e: auth.HttpError):
        return JSONResponse({"error": e.message, **e.extra}, e.status, headers=NO_STORE)

    async def card_info(request: Request):
        """What the login page shows for a card: whose it is, and whether to ask for their password or have them choose one."""
        user = auth.find_by_card(store, request.path_params["card"])
        if not user:
            return JSONResponse({"error": "this card is not valid any more: ask an admin for a new one"}, 404)
        return JSONResponse({"username": user["username"], "name": user["name"], "hasPassword": bool(user.get("password"))}, headers=NO_STORE)

    async def do_login(request: Request):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        try:
            user = await run_in_threadpool(auth.login, store, throttle, request.client.host if request.client else "?",
                                           body.get("card"), body.get("username"), body.get("password"))
        except auth.HttpError as e:
            return fail(e)
        return JSONResponse({"ok": True, "user": auth.public_user(user), "home": f"/w/{user['username']}"},
                            headers={**NO_STORE, "Set-Cookie": auth.session_cookie(secret, user, secure(request))})

    async def do_logout(_request: Request):
        return JSONResponse({"ok": True}, headers={"Set-Cookie": auth.CLEAR_COOKIE})

    async def whoami(request: Request):
        """Every page asks this on load, so renewing the cookie here means you stay logged in for as long as you
        keep using the app, not a year from login."""
        user, via_cookie = auth.identify(store, secret, request.cookies, request.headers.get("authorization"))
        headers = {**NO_STORE, **({"Set-Cookie": auth.session_cookie(secret, user, secure(request))} if user and via_cookie else {})}
        return JSONResponse({"user": auth.public_user(user), "home": f"/w/{user['username']}" if user else None}, headers=headers)

    async def change_password(request: Request):
        """Changing your own password ends your other sessions, and keeps this one."""
        user = me(request)
        if user is None:
            return JSONResponse({"error": "log in first", "login": True}, 401)
        body = await request.json()
        if not auth.check_password(user, body.get("current")):
            return JSONResponse({"error": "the current password is wrong"}, 401)
        problem = auth.password_problem(body.get("password"))
        if problem:
            return JSONResponse({"error": problem}, 400)
        user["password"] = auth.hash_password(str(body["password"]))
        user["passwordSetAt"] = now()
        user["session"] = (user.get("session") or 1) + 1
        store.save_user(user)
        store.log(type="password-change", user=user["username"], who=user["username"])
        return JSONResponse({"ok": True}, headers={"Set-Cookie": auth.session_cookie(secret, user, secure(request))})

    # ---- the users, admins only (from Adam Designer) -------------------------------
    def admins(fn):
        async def endpoint(request: Request):
            user = me(request)
            if user is None:
                return JSONResponse({"error": "log in first", "login": True}, 401)
            if user["role"] != "admin":
                return JSONResponse({"error": "only an admin can do that"}, 403)
            target = None
            if "id" in request.path_params:
                target = store.users.get(request.path_params["id"])
                if target is None:
                    return JSONResponse({"error": "no such user"}, 404)
            try:
                body = await body_of(request)
                return await fn(request, user, target, body)
            except auth.HttpError as e:
                return fail(e)
            except Problem as e:
                return JSONResponse({"error": str(e)}, e.status)
        return endpoint

    def shown(u: dict) -> dict:
        ws = workspaces.get(u["id"])
        return {**auth.public_user(u, True), "projects": ws.projects() if ws else []}

    async def list_users(_request, _user, _target, _body):
        users = sorted(store.users.values(), key=lambda u: (not u.get("builtin"), u["username"]))
        return JSONResponse({"users": [shown(u) for u in users], "max": max_users, "log": store.tail(60)[::-1]}, headers=NO_STORE)

    async def add_user(_request, user, _target, body):
        new = auth.make_user(store, body.get("username"), body.get("name"), body.get("role"), limit=max_users)
        await run_in_threadpool(workspaces.of, new["id"], new["name"])      # their workspace, with the samples in it
        store.log(type="user-new", user=new["username"], role=new["role"], who=user["username"])
        return JSONResponse({"ok": True, "user": shown(new)})

    async def edit_user(_request, user, target, body):
        """Name and role. The username stays: it is what the log remembers, and it is in their address."""
        if body.get("name") is not None:
            target["name"] = str(body["name"]).strip()[:80] or target["username"]
        if body.get("role") is not None:
            if target.get("builtin") and body["role"] != "admin":
                raise auth.HttpError(400, "the built-in admin stays an admin")
            target["role"] = "admin" if body["role"] == "admin" else "user"
        store.save_user(target)
        store.log(type="user-edit", user=target["username"], role=target["role"], who=user["username"])
        return JSONResponse({"ok": True, "user": shown(target)})

    async def reset_user(_request, user, target, _body):
        """Forgot the password: clear it and sign them out everywhere. Their card then asks for a new one, exactly
        like the first time."""
        target["password"] = None
        target["session"] = (target.get("session") or 1) + 1
        store.save_user(target)
        store.log(type="user-reset", user=target["username"], who=user["username"])
        return JSONResponse({"ok": True, "user": shown(target)})

    async def recard_user(_request, user, target, _body):
        """Lost card: a new code, so the old link stops working."""
        target["card"] = str(__import__("uuid").uuid4())
        store.save_user(target)
        store.log(type="user-card", user=target["username"], who=user["username"])
        return JSONResponse({"ok": True, "user": shown(target)})

    async def rekey_user(_request, user, target, _body):
        """Their agent link got out, or their agent should stop: a new key, so the old link stops working."""
        target["key"] = auth.new_key()
        store.save_user(target)
        store.log(type="user-key", user=target["username"], who=user["username"])
        return JSONResponse({"ok": True, "user": shown(target)})

    async def delete_user(_request, user, target, _body):
        if target.get("builtin"):
            raise auth.HttpError(400, "the built-in admin cannot be deleted")
        if target["id"] == user["id"]:
            raise auth.HttpError(400, "you cannot delete yourself")
        store.delete_user(target["id"])      # their folder stays on the disk: storage/<id>
        store.log(type="user-delete", user=target["username"], id=target["id"], who=user["username"])
        return JSONResponse({"ok": True})

    async def card_svg(request, _user, target, _body):
        """The card's QR: a login link. Admins only, because it is half of a login."""
        import segno
        out = io.BytesIO()
        segno.make(f"{base_url(request.headers, request.url.scheme)}/login?card={target['card']}", error="m").save(out, kind="svg", border=0, xmldecl=False, svgns=True, scale=4)
        return Response(out.getvalue(), media_type="image/svg+xml", headers=NO_STORE)

    # ---- the canvas API (the person) ----------------------------------------------
    def state(request, ws, _body):
        owner, user, base = request.state.owner, request.state.me, base_url(request.headers, request.url.scheme)
        return {"workspace": {"name": owner["name"], "username": owner["username"]}, "me": auth.public_user(user),
                "projects": ws.projects(), "templates": ws.all.template_names(),
                "base": f"{base}/w/{owner['username']}", "agent": f"{base}/w/{owner['key']}", "origin": base, "version": info}

    def new_key(request, _ws, _body):
        """A new agent key for this workspace: the old agent link stops working at once."""
        owner = request.state.owner
        owner["key"] = auth.new_key()
        store.save_user(owner)
        store.log(type="user-key", user=owner["username"], who=request.state.me["username"])
        return {"agent": f"{base_url(request.headers, request.url.scheme)}/w/{owner['key']}"}

    def new_project(_request, ws, body):
        p = ws.create_project(str(body.get("name", "")), str(body.get("template", "")))
        return {"project": p.name}

    def project(request, ws, _body):
        p = ws.project(request.path_params["project"])
        return {**p.status(), "versions": p.versions(), "tolerance": p.tolerance}

    def looks(request, ws, body):
        p = ws.project(request.path_params["project"])
        return {"looks": p.set_look(list(body.get("names") or []), body.get("material"), body.get("color", ""))}

    def rev(request, ws, _body):
        p = ws.project(request.path_params["project"])
        return {"rev": p.rev, "building": p.building()}

    def get_note(request, ws, _body):
        p, name = note_of(request, ws)
        source = p.read(name)
        parsed = notes.parse(source)
        out = {"note": name, "source": source, "doc": parsed["doc"], "params": parsed["params"], "tags": parsed["tags"],
               "is_note": parsed["is_note"]}
        if parsed["is_note"]:
            out["report"] = p.report(name)
            r = p.cached(name) or {}
            out["params"] = r.get("params") or parsed["params"]     # as the build saw them: a Note may share a module's
            out["tag_faces"] = {k: t.get("faces", []) for k, t in (r.get("tags") or {}).items()}
            out["tag_hits"] = {k: {kind: t.get(kind, []) for kind in ("faces", "edges", "points", "parts", "curves")} for k, t in (r.get("tags") or {}).items()}
            out["checks"] = p.checks(name)
            out["versions"] = p.versions(name)
            out["load_check"] = p.load_check(name) if p.saved(name) else {"status": "new", "changes": []}
        return out

    def model(request, ws, _body):
        p, name = note_of(request, ws)
        return FileResponse(p.model(name, request.query_params.get("v", "draft")), media_type="model/gltf-binary", headers=NO_STORE)

    def faces(request, ws, _body):
        p, name = note_of(request, ws)
        p.result(name)
        f = p.out / name / "faces.json"
        if not f.exists():
            raise Problem(f"{name} does not build", 404)
        return FileResponse(f, media_type="application/json", headers=NO_STORE)

    def fingerprint(request, ws, _body):
        """What a saved version stores next to the Note: for the user's own git folder."""
        p, name = note_of(request, ws)
        v = request.query_params.get("v")
        saved = p.saved(name, int(v) if v else None)
        if not saved:
            raise Problem(f"{name} has not been saved" + (f" in version {v}" if v else ""), 404)
        return saved

    def picture(request, ws, _body):
        p, name = note_of(request, ws)
        q = request.query_params
        png = agent.picture(p, name, q.get("views", "iso,top,front,right"), q.get("v", "draft"), q.get("tags", "1") not in ("0", "false"))
        return Response(png, media_type="image/png", headers=NO_STORE)

    def put_tag(request, ws, body):
        """The person clicked a face and named it: the tag goes into the Note."""
        p, name = note_of(request, ws)
        tag = str(body.get("name", "")).strip()
        if not re.match(r"^[a-z][a-z0-9_]{0,39}$", tag):
            raise Problem("a tag name is lowercase letters, digits and underscores")
        try:
            if body.get("plane"):       # a plane put on a face, to draw on
                selector = {"kind": "plane", **tagging.clean_plane(body["plane"])}
                if body.get("face"):
                    selector["on"] = tagging.propose(body["face"])
            elif body.get("sketch"):    # a drawing made on a plane: the plane, the curves, and the face it lies on
                selector = {"kind": "sketch", **tagging.clean_sketch(body["sketch"])}
                if "on" not in selector and body.get("face"):
                    selector["on"] = tagging.propose(body["face"])
            elif body.get("items"):     # whatever is selected: one thing, or several as a group
                selector = tagging.propose_many(body["items"])
            elif body.get("face"):
                selector = tagging.propose(body["face"])
            else:
                selector = dict(body.get("selector") or {})
        except (KeyError, TypeError, ValueError) as e:
            raise Problem(f"that cannot be made a tag: {e}")
        if not selector.get("kind"):
            raise Problem("select something first")
        if body.get("role"):
            selector["role"] = str(body["role"]).strip()[:200]
        current = notes.parse(p.read(name))["tags"]
        return p.set_tags(name, {**current, tag: selector})

    def move_plane(request, ws, body):
        """A plane's distance off its face, changed afterwards. What was drawn on the plane goes with it."""
        p, name = note_of(request, ws)
        which = request.path_params["plane"]
        current = notes.parse(p.read(name))["tags"]
        plane = current.get(which)
        if not plane or plane.get("kind") != "plane":
            raise Problem(f"no plane {which!r} on {name}", 404)
        offset = body.get("offset")
        if not isinstance(offset, (int, float)) or isinstance(offset, bool) or abs(offset) > 1e5:
            raise Problem("the offset is a number of millimetres")
        by = float(offset) - float(plane.get("offset") or 0)
        plane["plane"] = {**plane["plane"], "origin": [round(o + by * n, 3) for o, n in zip(plane["plane"]["origin"], plane["plane"]["normal"])]}
        plane["offset"] = round(float(offset), 3)
        for tag in current.values():
            if tag.get("kind") == "sketch" and tag.get("plane_name") == which:
                tag["plane"] = dict(plane["plane"])
        return p.set_tags(name, current)

    def delete_tag(request, ws, _body):
        p, name = note_of(request, ws)
        current = notes.parse(p.read(name))["tags"]
        current.pop(request.path_params["tag"], None)
        return p.set_tags(name, current)

    def add_check(request, ws, body):
        p, name = note_of(request, ws)
        return {"added": p.add_check(name, body, by="user"), "report": p.report(name)}

    def put_check(request, ws, body):
        p, name = note_of(request, ws)
        p.put_check(name, request.path_params["check"], None if request.method == "DELETE" else body)
        return {"report": p.report(name)}

    def acknowledge(request, ws, _body):
        p, name = note_of(request, ws)
        return p.acknowledge(name)

    def save(request, ws, body):
        out = ws.project(request.path_params["project"]).save(str(body.get("message", "")), str(body.get("commit", "")))
        if out.get("saved") and not out.get("unchanged"):
            store.log(type="save", user=request.state.owner["username"], project=request.path_params["project"], version=out["version"], by="person")
        return out

    def diff(request, ws, _body):
        p, name = note_of(request, ws)
        q = request.query_params
        return p.diff(name, q.get("a", "1"), q.get("b", "draft"), float(q["tol"]) if q.get("tol") else None)

    def diff_model(request, ws, _body):
        p, name = note_of(request, ws)
        q = request.query_params
        path = p.diff_model(name, q.get("a", "1"), q.get("b", "draft"), q.get("side", "b"), float(q["tol"]) if q.get("tol") else None)
        return FileResponse(path, media_type="model/gltf-binary", headers=NO_STORE)

    def export(request, ws, _body):
        p, name = note_of(request, ws)
        fmt = request.path_params["fmt"]
        v = request.query_params.get("v", "draft")
        path = p.export(name, fmt, v)
        label = name if v == "draft" else f"{name}-v{v}"
        return FileResponse(path, media_type=EXPORTS[fmt], filename=f"{label}.{fmt}", headers=NO_STORE)

    def select(request, ws, body):
        p = ws.project(request.path_params["project"])
        agent.remember_selection(ws.id, p.name, body if body.get("items") or body.get("face") else None)
        return {"ok": True}

    # ---- the agent's door, as plain HTTP ------------------------------------------
    def agent_call(request, ws, body):
        """Any tool, by GET with a query string (for an LLM that can only fetch addresses) or by POST with JSON.
        A Note can also be the body itself (text/plain)."""
        name = request.path_params["tool"]
        fn = agent.TOOLS.get(name)
        args = dict(request.query_params)
        raw = body.pop("_raw", None)
        args.update(body)
        if raw is not None:
            args["source"] = raw
        if fn:
            args = {k: coerce(v, inspect.signature(fn).parameters[k].annotation) if k in inspect.signature(fn).parameters else v
                    for k, v in args.items()}
        owner = request.state.owner
        try:
            result, png = agent.call(name, caller(ws, owner, request.headers, request.url.scheme), args)
            if name not in agent.READ_ONLY and result.get("written", True) and not result.get("already"):      # what agents changed: for the admin's eye
                store.log(type="agent", user=owner["username"], tool=name, project=args.get("project") or args.get("name"), note=args.get("note"),
                          **({"version": result["version"]} if name == "save" and result.get("saved") else {}))
        except Problem as e:
            if request.method != "GET":
                raise
            # many LLM fetch tools show nothing of a 4xx answer: by GET, a mistake is told in a 200 the model can read
            return {"error": str(e), "status": e.status}
        if png and "image/png" in request.headers.get("accept", ""):
            return Response(png, media_type="image/png", headers=NO_STORE)
        return result

    def agent_tools(request, _ws, _body):
        owner = request.state.owner
        return {"workspace": owner["username"], "api": f"{base_url(request.headers, request.url.scheme)}/w/{owner['key']}/agent", "tools": tool_docs()}

    async def api_docs(request: Request):
        return Response(docs(base_url(request.headers, request.url.scheme)), media_type="text/markdown; charset=utf-8", headers=NO_STORE)

    n, f = "/w/{wid}/api/p/{project}/n/{note}", "/w/{wid}/file/p/{project}/n/{note}"
    routes = [
        Route("/", home),
        Route("/login", login_page),
        Route("/users", users_page),
        Route("/healthz", lambda _r: JSONResponse({"ok": True})),
        Route("/api/version", get_version),
        Route("/api", api_docs),
        Route("/llms.txt", api_docs),
        Route("/skill.zip", skill_zip),
        # logging in
        Route("/api/login", do_login, methods=["POST"]),
        Route("/api/login/card/{card}", card_info),
        Route("/api/logout", do_logout, methods=["POST"]),
        Route("/api/me", whoami),
        Route("/api/me/password", change_password, methods=["PUT"]),
        # the users, for admins
        Route("/api/users", admins(list_users)),
        Route("/api/users", admins(add_user), methods=["POST"]),
        Route("/api/users/{id}", admins(edit_user), methods=["PUT"]),
        Route("/api/users/{id}", admins(delete_user), methods=["DELETE"]),
        Route("/api/users/{id}/reset", admins(reset_user), methods=["POST"]),
        Route("/api/users/{id}/card", admins(recard_user), methods=["POST"]),
        Route("/api/users/{id}/key", admins(rekey_user), methods=["POST"]),
        Route("/api/users/{id}/card.svg", admins(card_svg)),
        # the person's door: /w/<username>, behind the login
        Route("/w/{wid}", canvas),
        Route("/w/{wid}/api/state", api(state)),
        Route("/w/{wid}/api/key", api(new_key), methods=["POST"]),
        Route("/w/{wid}/api/projects", api(new_project), methods=["POST"]),
        Route("/w/{wid}/api/p/{project}", api(project)),
        Route("/w/{wid}/api/p/{project}/rev", api(rev)),
        Route("/w/{wid}/api/p/{project}/looks", api(looks), methods=["PUT"]),
        Route("/w/{wid}/api/p/{project}/save", api(save), methods=["POST"]),
        Route("/w/{wid}/api/p/{project}/selection", api(select), methods=["POST"]),
        Route(n, api(get_note)),
        Route(n + "/model.glb", api(model)),
        Route(n + "/faces.json", api(faces)),
        Route(n + "/render.png", api(picture)),
        Route(n + "/fingerprint.json", api(fingerprint)),
        Route(n + "/tags", api(put_tag), methods=["POST"]),
        Route(n + "/tags/{tag}", api(delete_tag), methods=["DELETE"]),
        Route(n + "/planes/{plane}", api(move_plane), methods=["PUT"]),
        Route(n + "/checks", api(add_check), methods=["POST"]),
        Route(n + "/checks/{check}", api(put_check), methods=["PUT", "DELETE"]),
        Route(n + "/ack", api(acknowledge), methods=["POST"]),
        Route(n + "/diff", api(diff)),
        Route(n + "/diff.glb", api(diff_model)),
        Route(n + "/export.{fmt}", api(export)),
        # the agent's door: /w/<agent key>: the tools, and the files their answers point at
        Route("/w/{wid}/agent", door(agent_tools)),
        Route("/w/{wid}/agent/{tool}", door(agent_call), methods=["GET", "POST"]),
        Route(f + "/render.png", door(picture)),
        Route(f + "/model.glb", door(model)),
        Route(f + "/fingerprint.json", door(fingerprint)),
        Route(f + "/export.{fmt}", door(export)),
        Mount("/static", StaticFiles(directory=CANVAS)),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    # any origin may call: what opens a workspace is the id in the address, not a cookie a foreign page could ride on
    site = Starlette(routes=routes, lifespan=lifespan,
                     middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])])
    site.state.workspaces, site.state.store, site.state.admin = workspaces, store, admin

    async def app(scope, receive, send):
        """/w/<agent key>/mcp goes to the MCP app, with whose agent it is written where a tool can read it."""
        if scope["type"] == "http":
            m = MCP_PATH.match(scope["path"])
            if m:
                owner = auth.find_by_key(store, m.group(1))
                if owner is None:
                    await JSONResponse({"error": "this agent link is not valid (any more)"}, 404)(scope, receive, send)
                    return
                headers = [(k, v) for k, v in scope["headers"] if k != b"x-monet-user"]
                headers.append((b"x-monet-user", owner["id"].encode()))
                await mcp_app({**scope, "path": "/mcp", "raw_path": b"/mcp", "root_path": "", "headers": headers}, receive, send)
                return
        await site(scope, receive, send)

    app.state = site.state
    app.site = site
    return app
