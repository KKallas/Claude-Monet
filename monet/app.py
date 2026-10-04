"""The web app: one process. The canvas and its API for the person, the agent's door
(MCP and plain HTTP) for their own LLM harness, and nothing else.

No accounts. Pressing Start makes a workspace with an unguessable id; its link is the
login. MONET_MAX_USERS says how many workspaces there may be.
"""
import base64
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

from . import __version__, agent, note as notes, render, tags as tagging
from .workspace import EXPORTS, ID_RE, Problem, Workspaces

ROOT = Path(__file__).resolve().parent.parent
CANVAS = ROOT / "canvas"
COOKIE = "monet_ws"
MCP_PATH = re.compile(r"^/w/([A-Za-z0-9_-]{16})/mcp/?$")
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
    return value


def tool_docs() -> dict:
    out = {}
    for name, fn in agent.TOOLS.items():
        params = [p for k, p in inspect.signature(fn).parameters.items() if k != "c"]
        out[name] = {"args": {p.name: ("required" if p.default is inspect.Parameter.empty else f"default {p.default!r}") for p in params},
                     "changes_things": name not in agent.READ_ONLY, "doc": inspect.cleandoc(fn.__doc__)}
    return out


def connection(ws, base: str) -> dict:
    """Everything someone who just got a workspace needs to know."""
    w = f"{base}/w/{ws.id}"
    return {
        "id": ws.id,
        "workspace": w,
        "canvas": w,
        "api": f"{w}/agent",
        "mcp": f"{w}/mcp",
        "docs": f"{base}/api",
        "projects": ws.projects(),
        "next": [
            f"Keep the id: it is the only key to this workspace. There is no other login.",
            f"Give the user the canvas link ({w}) to open in a browser: they watch the part there and click the faces they mean.",
            f"Read how to work here: GET {w}/agent/guide",
            f"Then: GET {w}/agent/status",
        ],
    }


def docs(base: str, workspaces) -> str:
    """The API, written for an LLM that was only given this address."""
    tools = []
    for name, d in tool_docs().items():
        args = ", ".join(f"{k} ({v})" for k, v in d["args"].items()) or "no arguments"
        tools.append(f"### {name}{'  (changes things)' if d['changes_things'] else ''}\n\n{d['doc']}\n\nArguments: {args}\n")
    return f"""# Monet API

Monet is a CAD workspace for 3D-printed parts. You (an LLM agent) write each part as a small Python file, a
"Note", using build123d. This server builds it, measures it, runs the user's checks, draws pictures, keeps
saved versions and exports files for printing. The human watches in a browser canvas and clicks the faces they mean.

Everything is plain HTTPS. No keys, no headers, no login: a workspace id in the address is the whole access.

## 1. Get a workspace id (once)

If the user gave you a workspace link ({base}/w/<id>), that is your workspace: skip this step.
Otherwise register one:

    GET {base}/api/register?name=<a short name>

The answer is JSON with `id`, `api` (your tool address), `canvas` (the link to give to the human) and `next`.
This instance allows {workspaces.max_users} workspaces; {workspaces.count()} are in use. Register once and keep the
id for the whole conversation; do not register again for every request.

## 2. Call tools

    GET  {base}/w/<id>/agent/<tool>?arg=value&arg=value
    POST {base}/w/<id>/agent/<tool>          with a JSON object of arguments

Both do the same. Answers are JSON. A mistake of yours comes back as {{"error": "what was wrong", "status": 4xx}}:
by POST with that HTTP status, by GET inside a 200 (so that a fetch tool which hides failed pages still shows it
to you). Always look for `error` in the answer.

Sending a Note (write_note) needs its whole source. Any of these works:

    POST .../agent/write_note   JSON {{"project": "...", "note": "...", "source": "..."}}
    POST .../agent/write_note?project=...&note=...     with the Python source as the body (Content-Type: text/plain)
    GET  .../agent/write_note?project=...&note=...&source=<URL-encoded source>
    GET  .../agent/write_note?project=...&note=...&source_b64=<base64url of the source>

Pictures: `look` answers with `image`, the address of a PNG. Fetch it and look at it.
Files: `export` answers with `url`, the address of the 3MF / STL / STEP / GLB.

Start with `guide` (the Note format, tags, checks, the loop to follow, the rules that are not yours to bend),
then `status`.

    GET {base}/w/<id>/agent/guide
    GET {base}/w/<id>/agent/status

## 3. The rules in one breath

Read a Note before you edit it. Send the whole file. Look at the picture, do not assume. A red check means
fix the geometry, never the check: checks belong to the user (you can add one, not change or remove one). Save
only when everything is green. If the load check of a saved Note is red, stop and tell the user. If you can
write files and run git on the user's computer, keep the Notes in a local folder and commit after every
successful save: the history is theirs.

## Tools

{chr(10).join(tools)}
## Also

- `GET {base}/w/<id>/agent` lists the tools as JSON.
- MCP (Claude Desktop, Claude Code and others): `{base}/w/<id>/mcp` (streamable HTTP).
- Source: {version()["source"]} ({version()["license"]}).
"""


def create_app(storage: str | Path, max_users: int = 20, templates: str | Path | None = None,
               profiles: str | Path | None = None) -> Starlette:
    workspaces = Workspaces(storage, templates or ROOT / "notes", profiles or ROOT / "profiles", max_users)
    info = version()

    def caller(ws, headers, scheme="http") -> agent.Caller:
        return agent.Caller(ws, f"{base_url(headers, scheme)}/w/{ws.id}")

    # ---- the agent's door, as MCP -------------------------------------------------
    def caller_from_mcp(headers) -> agent.Caller:
        ws = workspaces.get(headers.get("x-monet-workspace", ""))
        if ws is None:
            raise ValueError("no such workspace")
        return caller(ws, headers)

    from mcp.server.transport_security import TransportSecuritySettings
    mcp = agent.mcp_server(caller_from_mcp)
    # the workspace id in the address is the secret, not an ambient cookie: nothing for a rebound DNS name to ride on
    mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    # ---- helpers ------------------------------------------------------------------
    def api(fn):
        """An endpoint inside a workspace: fn(request, ws, body) runs off the event loop; a Problem is the caller's."""
        async def endpoint(request: Request):
            ws = workspaces.get(request.path_params["wid"])
            if ws is None:
                return JSONResponse({"error": "no such workspace"}, 404)
            body = {}
            if request.method in ("POST", "PUT"):
                raw = await request.body()
                if raw and "json" not in request.headers.get("content-type", "json"):
                    body = {"_raw": raw.decode("utf-8", "replace")}      # a Note sent as plain text
                elif raw:
                    try:
                        body = json.loads(raw)
                    except json.JSONDecodeError:
                        return JSONResponse({"error": "the body is not JSON"}, 400)
                    if not isinstance(body, dict):
                        return JSONResponse({"error": "the body must be a JSON object"}, 400)
            try:
                out = await run_in_threadpool(fn, request, ws, body)
            except Problem as e:
                return JSONResponse({"error": str(e)}, e.status)
            return out if isinstance(out, Response) else JSONResponse(out, headers=NO_STORE)
        return endpoint

    def note_of(request, ws):
        return ws.project(request.path_params["project"]), request.path_params["note"]

    # ---- pages --------------------------------------------------------------------
    async def home(request: Request):
        wid = request.cookies.get(COOKIE, "")
        if workspaces.get(wid):
            return RedirectResponse(f"/w/{wid}", 302)
        return FileResponse(CANVAS / "landing.html", headers=NO_STORE)

    async def canvas(request: Request):
        wid = request.path_params["wid"]
        if not workspaces.get(wid):
            return RedirectResponse("/?gone=1", 302)
        response = FileResponse(CANVAS / "index.html", headers=NO_STORE)
        response.set_cookie(COOKIE, wid, max_age=365 * 24 * 3600, httponly=True, samesite="lax")
        return response

    async def leave(_request: Request):
        response = RedirectResponse("/", 302)
        response.delete_cookie(COOKIE)
        return response

    async def get_version(_request: Request):
        return JSONResponse({**info, "workspaces": workspaces.count(), "max": workspaces.max_users,
                             "templates": workspaces.template_names()}, headers=NO_STORE)

    async def start(request: Request):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        try:
            ws = await run_in_threadpool(workspaces.create, str(body.get("name", "")))
        except Problem as e:
            return JSONResponse({"error": str(e)}, e.status)
        return JSONResponse({"id": ws.id, "url": f"/w/{ws.id}"})

    async def skill_zip(_request: Request):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted((ROOT / "skill" / "monet").rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, Path("monet") / f.relative_to(ROOT / "skill" / "monet"))
        return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="monet-skill.zip"'})

    # ---- the canvas API (the person) ----------------------------------------------
    def state(request, ws, _body):
        return {"workspace": {"id": ws.id, **ws.meta}, "projects": ws.projects(), "templates": ws.all.template_names(),
                "base": f"{base_url(request.headers, request.url.scheme)}/w/{ws.id}", "version": info}

    def rename(_request, ws, body):
        ws.write_meta({**ws.meta, "name": str(body.get("name", "")).strip()[:60]})
        return {"ok": True}

    def new_project(_request, ws, body):
        p = ws.create_project(str(body.get("name", "")), str(body.get("template", "")))
        return {"project": p.name}

    def project(request, ws, _body):
        p = ws.project(request.path_params["project"])
        return {**p.status(), "versions": p.versions(), "tolerance": p.tolerance}

    def rev(request, ws, _body):
        return {"rev": ws.project(request.path_params["project"]).rev}

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
        face = body.get("face")
        selector = tagging.propose(face) if face else dict(body.get("selector") or {})
        if not selector.get("kind"):
            raise Problem("click a face first")
        if body.get("role"):
            selector["role"] = str(body["role"]).strip()[:200]
        current = notes.parse(p.read(name))["tags"]
        return p.set_tags(name, {**current, tag: selector})

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
        return ws.project(request.path_params["project"]).save(str(body.get("message", "")), str(body.get("commit", "")))

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
        A Note can also be the body itself (text/plain), or travel as source_b64 when a query string mangles it."""
        name = request.path_params["tool"]
        fn = agent.TOOLS.get(name)
        args = dict(request.query_params)
        raw = body.pop("_raw", None)
        args.update(body)
        if raw is not None:
            args["source"] = raw
        if "source_b64" in args:
            try:
                args["source"] = base64.urlsafe_b64decode(args.pop("source_b64") + "==").decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                raise Problem("source_b64 is not base64url of UTF-8 text")
        if fn:
            args = {k: coerce(v, inspect.signature(fn).parameters[k].annotation) if k in inspect.signature(fn).parameters else v
                    for k, v in args.items()}
        try:
            result, png = agent.call(name, caller(ws, request.headers, request.url.scheme), args)
        except Problem as e:
            if request.method != "GET":
                raise
            # many LLM fetch tools show nothing of a 4xx answer: by GET, a mistake is told in a 200 the model can read
            return {"error": str(e), "status": e.status}
        if png and "image/png" in request.headers.get("accept", ""):
            return Response(png, media_type="image/png", headers=NO_STORE)
        return result

    def agent_tools(request, ws, _body):
        return {"workspace": ws.id, "api": f"{base_url(request.headers, request.url.scheme)}/w/{ws.id}/agent", "tools": tool_docs()}

    async def register(request: Request):
        """A workspace for whoever asks: the id, and where everything is. For an agent that starts on its own."""
        body = {}
        if request.method == "POST":
            with contextlib.suppress(json.JSONDecodeError):
                body = await request.json()
        name = str(request.query_params.get("name") or (body.get("name") if isinstance(body, dict) else "") or "")
        try:
            ws = await run_in_threadpool(workspaces.create, name)
        except Problem as e:   # by GET in a 200, like every mistake at the agent's door: see agent_call
            return JSONResponse({"error": str(e), "status": e.status}, 200 if request.method == "GET" else e.status, headers=NO_STORE)
        return JSONResponse(connection(ws, base_url(request.headers, request.url.scheme)), headers=NO_STORE)

    async def api_docs(request: Request):
        return Response(docs(base_url(request.headers, request.url.scheme), workspaces), media_type="text/markdown; charset=utf-8", headers=NO_STORE)

    n = "/w/{wid}/api/p/{project}/n/{note}"
    routes = [
        Route("/", home),
        Route("/leave", leave),
        Route("/healthz", lambda _r: JSONResponse({"ok": True})),
        Route("/api/version", get_version),
        Route("/api/start", start, methods=["POST"]),
        Route("/api", api_docs),
        Route("/llms.txt", api_docs),
        Route("/api/register", register, methods=["GET", "POST"]),
        Route("/skill.zip", skill_zip),
        Route("/w/{wid}", canvas),
        Route("/w/{wid}/api/state", api(state)),
        Route("/w/{wid}/api/name", api(rename), methods=["PUT"]),
        Route("/w/{wid}/api/projects", api(new_project), methods=["POST"]),
        Route("/w/{wid}/api/p/{project}", api(project)),
        Route("/w/{wid}/api/p/{project}/rev", api(rev)),
        Route("/w/{wid}/api/p/{project}/save", api(save), methods=["POST"]),
        Route("/w/{wid}/api/p/{project}/selection", api(select), methods=["POST"]),
        Route(n, api(get_note)),
        Route(n + "/model.glb", api(model)),
        Route(n + "/faces.json", api(faces)),
        Route(n + "/render.png", api(picture)),
        Route(n + "/fingerprint.json", api(fingerprint)),
        Route(n + "/tags", api(put_tag), methods=["POST"]),
        Route(n + "/tags/{tag}", api(delete_tag), methods=["DELETE"]),
        Route(n + "/checks", api(add_check), methods=["POST"]),
        Route(n + "/checks/{check}", api(put_check), methods=["PUT", "DELETE"]),
        Route(n + "/ack", api(acknowledge), methods=["POST"]),
        Route(n + "/diff", api(diff)),
        Route(n + "/diff.glb", api(diff_model)),
        Route(n + "/export.{fmt}", api(export)),
        Route("/w/{wid}/agent", api(agent_tools)),
        Route("/w/{wid}/agent/{tool}", api(agent_call), methods=["GET", "POST"]),
        Mount("/static", StaticFiles(directory=CANVAS)),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    # any origin may call: what opens a workspace is the id in the address, not a cookie a foreign page could ride on
    site = Starlette(routes=routes, lifespan=lifespan,
                     middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])])
    site.state.workspaces = workspaces

    async def app(scope, receive, send):
        """/w/<id>/mcp goes to the MCP app, with the workspace it is for written where a tool can read it."""
        if scope["type"] == "http":
            m = MCP_PATH.match(scope["path"])
            if m:
                if not workspaces.get(m.group(1)):
                    await JSONResponse({"error": "no such workspace"}, 404)(scope, receive, send)
                    return
                headers = [(k, v) for k, v in scope["headers"] if k != b"x-monet-workspace"]
                headers.append((b"x-monet-workspace", m.group(1).encode()))
                await mcp_app({**scope, "path": "/mcp", "raw_path": b"/mcp", "root_path": "", "headers": headers}, receive, send)
                return
        await site(scope, receive, send)

    app.state = site.state
    app.site = site
    return app
