"""The agent's door: what a person's own LLM harness can do in their workspace.

One set of tools, two ways in: MCP (Claude Desktop, Claude Code and anything else that
speaks it) at /w/<workspace>/mcp, and plain HTTP (POST /w/<workspace>/agent/<tool> with
a JSON body) for a harness that only has a shell.

What is deliberately not here: changing or removing a check, acknowledging a load check,
deleting a Note. Those are the user's, in the canvas.
"""
import inspect
import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import render, tags as tagging
from .workspace import EXPORTS, Problem, Workspace

GUIDE = Path(__file__).resolve().parent.parent / "skill" / "monet"
_selection: dict[tuple[str, str], dict] = {}


@dataclass
class Caller:
    ws: Workspace
    base: str     # https://host/w/<id>

    def canvas(self, project: str = "", note: str = "") -> str:
        return self.base + (f"#{project}" + (f"/{note}" if note else "") if project else "")


def remember_selection(ws_id: str, project: str, selection: dict | None) -> None:
    if selection is None:
        _selection.pop((ws_id, project), None)
    else:
        _selection[(ws_id, project)] = {**selection, "at": time.time()}


def guide(c: Caller) -> dict:
    """How to work in Monet: the Note format, tags, checks, the loop to follow and the rules that are not yours to
    bend. Read this once before the first edit of a session (it is the same text as the Monet skill)."""
    text = (GUIDE / "SKILL.md").read_text()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    refs = "".join(f"\n\n---\n\n{p.read_text()}" for p in sorted((GUIDE / "references").glob("*.md")))
    return {"guide": text.strip() + refs, "canvas": c.canvas()}


def status(c: Caller, project: str = "") -> dict:
    """Where things stand. Without a project: the projects of this workspace, the templates a new one can start
    from, and the link of the canvas (give it to the user so they can watch and point). With a project: its Notes,
    whether each builds, is saved, or has changed since the last save."""
    if not project:
        return {"projects": c.ws.projects(), "templates": c.ws.all.template_names(), "canvas": c.canvas(),
                "hint": "ask the user to open the canvas link in a browser; call guide() if you have not read the rules"}
    p = c.ws.project(project)
    return {**p.status(), "printer_profile": p.printer, "material_profile": p.material, "canvas": c.canvas(project)}


def new_project(c: Caller, name: str, template: str = "") -> dict:
    """Start a project (a folder of Notes). name: lowercase letters, digits, dashes. template: copy one of the
    templates listed by status(), or leave empty for an empty project."""
    p = c.ws.create_project(name, template)
    return {"project": p.name, "notes": p.files(), "canvas": c.canvas(p.name)}


def read_note(c: Caller, project: str, note: str) -> dict:
    """The source of a Note (or helper module) as the server has it, the checks on it and its last build report.
    Read before you edit: the user may have added tags from the canvas since you last wrote it."""
    p = c.ws.project(project)
    source = p.read(note)
    out = {"note": note, "source": source}
    if p.is_note(note):
        out["checks"] = p.checks(note)
        out["report"] = p.report(note)
    return out


def write_note(c: Caller, project: str, note: str, source: str) -> dict:
    """Send the whole source of a Note (one Python file: docstring, PARAMS, TAGS, build()). The server builds it and
    runs the checks; the answer is the report. `green: true` means it builds, every tag still finds its feature and
    every check passes. Refused if the load check of the saved Note is red: then stop and tell the user."""
    p = c.ws.project(project)
    report = p.write(note, source, agent=True)
    report["canvas"] = c.canvas(project, note)
    return report


def check(c: Caller, project: str, note: str) -> dict:
    """Build the Note as it is now and run its checks. Use after the user changed something from the canvas, or
    after you changed a module that this Note imports."""
    return c.ws.project(project).report(note)


def picture(p, note: str, views: str = "iso,top,front,right", version: str = "draft", tags: bool = True) -> bytes:
    """The PNG behind look() and behind the picture's own address."""
    glb = p.model(note, version)
    faces = highlight = None
    if tags and str(version) == "draft":
        r = p.result(note)
        faces = json.loads((p.out / note / "faces.json").read_text())["faces"]
        highlight = {k: t["faces"] for k, t in r["tags"].items() if t.get("faces")}
    names = tuple(v.strip() for v in views.split(",") if v.strip())
    return render.png(glb, names, faces=faces, highlight=highlight, title=f"{p.name}/{note} ({version})")


def look(c: Caller, project: str, note: str, views: str = "iso,top,front,right", version: str = "draft", tags: bool = True):
    """A picture of the part: look at it, do not assume. views: any of iso, iso_back, iso_under, top, bottom, front,
    back, left, right, comma separated. version: "draft" (as built now) or a saved version number. tags: paint the
    tagged faces (draft only) with a legend, to see what each tag points at. Over MCP the picture comes with the
    answer; over HTTP the answer carries its address (`image`, a PNG): fetch that."""
    p = c.ws.project(project)
    png = picture(p, note, views, version, tags)
    query = urllib.parse.urlencode({"views": views, "v": version, "tags": int(bool(tags)), "r": p.rev[-8:]})
    return {"note": note, "version": str(version), "views": views, "units": "mm, Z up",
            "image": f"{c.base}/api/p/{project}/n/{note}/render.png?{query}"}, png


def selection(c: Caller, project: str) -> dict:
    """What the user is pointing at in the canvas right now: the Note, the face they clicked (its kind, where it is,
    its size), the tag it already has if any, and the selector that would find it again. Call it when the user says
    "this face", "here", "that hole"."""
    c.ws.project(project)
    s = _selection.get((c.ws.id, project))
    if not s:
        return {"selected": False, "hint": f"nothing is selected; ask the user to click a face in the canvas: {c.canvas(project)}"}
    out = {"selected": True, "note": s.get("note"), "seconds_ago": round(time.time() - s["at"]), "face": s.get("face"),
           "point": s.get("point"), "tags": s.get("tags", [])}
    if s.get("face"):
        out["selector"] = tagging.propose(s["face"])
    return out


def add_check(c: Caller, project: str, note: str, what: str, min: float | None = None, max: float | None = None,
              equals: float | bool | None = None, why: str = "", id: str = "") -> dict:
    """Add a check to a Note: a measurement and the range it must stay in. what: volume_cm3, area_cm2, size_x,
    size_y, size_z, min_x..max_z, solids, fits_bed, or tag.<name>.<measure> such as tag.rod_bore.width,
    tag.rod_bore.through, tag.base.at. Give min and/or max, or equals. why: the rule in the user's words.
    You can add checks; you cannot change or remove one. Propose checks for every rule in the docstring."""
    p = c.ws.project(project)
    added = p.add_check(note, {"id": id, "what": what, "min": min, "max": max, "equals": equals, "why": why}, by="agent")
    return {"added": added, "report": p.report(note)}


def load_check(c: Caller, project: str, note: str) -> dict:
    """Semmelweis: rebuild the saved Note from its saved source and compare with what was saved. green: identical.
    yellow: within print tolerance (usually a library update): tell the user. red: something changed: do not edit,
    the user must look at it in the canvas and acknowledge."""
    return c.ws.project(project).load_check(note)


def save(c: Caller, project: str, message: str, commit: str = "") -> dict:
    """Save the project as a new version. Nothing is saved on red: every Note must build and pass its checks.
    message: what changed and why, one line. After a successful save, commit the same files in the user's local git
    folder (that is where the history lives); pass that commit's hash here next time if you have it."""
    p = c.ws.project(project)
    out = p.save(message, commit)
    out["canvas"] = c.canvas(project)
    return out


def versions(c: Caller, project: str, note: str = "") -> dict:
    """The saved versions of a project, or only those in which one Note changed."""
    p = c.ws.project(project)
    return {"versions": [{"version": m["n"], "at": m["at"], "message": m["message"], "commit": m.get("commit", ""),
                          "changed": [k for k, v in m["notes"].items() if v["v"] == m["n"]]} for m in p.versions(note or None)]}


def diff(c: Caller, project: str, note: str, a: str, b: str = "draft") -> dict:
    """Compare two states of a Note: a and b are saved version numbers or "draft". Returns how far the surfaces
    moved (mm, and where), the fingerprints side by side and what happened to each tagged feature. The user sees
    the same as a colour map in the canvas."""
    p = c.ws.project(project)
    s = p.diff(note, a, b)
    return {k: s[k] for k in ("note", "a", "b", "tolerance", "same", "removed", "added", "numbers", "tags")} | {
        "canvas": c.canvas(project, note)}


def export(c: Caller, project: str, note: str, format: str = "3mf", version: str = "draft") -> dict:
    """A file of the part for printing or for other CAD: 3mf, stl, step or glb. Returns a link; give it to the user
    (or download it into their local folder if you have a shell)."""
    p = c.ws.project(project)
    path = p.export(note, format, version)
    return {"url": f"{c.base}/api/p/{project}/n/{note}/export.{format}" + ("" if str(version) == "draft" else f"?v={version}"),
            "bytes": path.stat().st_size, "format": format, "mime": EXPORTS[format]}


TOOLS = {f.__name__: f for f in (guide, status, new_project, read_note, write_note, check, look, selection, add_check,
                                 load_check, save, versions, diff, export)}
READ_ONLY = {"guide", "status", "read_note", "check", "look", "selection", "load_check", "versions", "diff", "export"}


def call(name: str, caller: Caller, args: dict):
    """(result dict, png bytes or None). Raises Problem for anything the caller got wrong."""
    fn = TOOLS.get(name)
    if fn is None:
        raise Problem(f"no tool {name!r}; there are: {', '.join(TOOLS)}", 404)
    try:
        inspect.signature(fn).bind(caller, **args)
    except TypeError as e:
        raise Problem(f"{name}: {e}")
    out = fn(caller, **args)
    return out if isinstance(out, tuple) else (out, None)


def mcp_server(resolve_caller):
    """The same tools as an MCP server. resolve_caller(headers) -> Caller."""
    import anyio
    from mcp.server.mcpserver import Context, Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    server = MCPServer(
        "Monet",
        instructions="Monet is a CAD workspace: you write Notes (one build123d Python file per part), the server "
                     "builds them, runs the user's checks and shows the result in a browser canvas where the user "
                     "points at faces. Call guide() before your first edit and follow it.",
    )

    def bind(name, fn):
        sig = inspect.signature(fn)
        params = [p for k, p in sig.parameters.items() if k != "c"]

        async def tool(ctx: Context, **kwargs):
            try:
                caller = resolve_caller(ctx.headers or {})
            except ValueError as e:
                raise ToolError(str(e)) from None
            try:
                result, png = await anyio.to_thread.run_sync(lambda: call(name, caller, kwargs))
            except Problem as e:
                raise ToolError(str(e)) from None   # the caller's mistake, in words: it reaches the model as it is
            return [result, Image(data=png, format="png")] if png else result

        tool.__name__ = name
        tool.__doc__ = fn.__doc__
        tool.__signature__ = sig.replace(
            parameters=[inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context), *params],
            return_annotation=inspect.Signature.empty)
        tool.__annotations__ = {"ctx": Context, **{p.name: p.annotation for p in params}}
        server.add_tool(tool, name=name, description=inspect.cleandoc(fn.__doc__),
                        annotations=ToolAnnotations(readOnlyHint=name in READ_ONLY), structured_output=False)

    for name, fn in TOOLS.items():
        bind(name, fn)
    return server
