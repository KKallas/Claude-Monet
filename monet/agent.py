"""The agent's door: what a person's own LLM harness can do in their workspace.

One set of tools, two ways in: MCP (Claude Desktop, Claude Code and anything else that
speaks it) at /w/<workspace>/mcp, and plain HTTP (POST /w/<workspace>/agent/<tool> with
a JSON body) for a harness that only has a shell. They open only while the person has
remote control on (monet/remote.py). Beside them, one route that is not a tool: the upload
of what the agent built on its own computer (upload(); the server never runs a Note).

What is deliberately not here: changing or removing a check, acknowledging a load check,
deleting a Note. Those are the user's, in the canvas. The canvas they have open the agent
may look at and take somewhere (screen, view, goto), never run code in: a change is made
here, through the server and its rules, not as the person in their page.
"""
import base64
import inspect
import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import joints, render, tags as tagging
from . import note as notes
from .workspace import EXPORTS, Problem, Workspace, build_files

GUIDE = Path(__file__).resolve().parent.parent / "skill" / "monet"
_selection: dict[tuple[str, str], dict] = {}


@dataclass
class Caller:
    ws: Workspace
    base: str       # https://host/w/<agent key>: the agent's own address; what it can fetch without a login
    page: str       # https://host/w/<username>: the person's canvas; they log in to see it
    owner: dict | None = None       # whose agent this is, as the accounts keep them
    remote: object | None = None    # their open canvases (monet.remote.Remote), while remote control is on
    done: Callable[[str, dict, dict], None] | None = None      # (tool, args, result): what it changed, written down

    def canvas(self, project: str = "", note: str = "") -> str:
        return self.page + (f"#{project}" + (f"/{note}" if note else "") if project else "")


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
        return {"projects": c.ws.projects(), "templates": c.ws.all.template_names(), "canvas": c.canvas(), **_remote(c),
                "hint": "the canvas link is where the user watches and points (they log in there); call guide() if you have not read the rules"}
    p = c.ws.project(project)
    return {**p.status(), "printer_profile": p.printer, "material_profile": p.material, "canvas": c.canvas(project), **_remote(c)}


def _remote(c: Caller) -> dict:
    """How long the door stays open, and the canvases the user has open: what screen, goto and view reach."""
    if c.remote is None or c.owner is None:
        return {}
    left = max(0.0, (c.owner.get("agent") or {}).get("until", 0) - time.time())
    return {"remote": {"minutes_left": round(left / 60), "ends": "by itself after 15 minutes with nothing from you or the user, and "
                       "at once when they switch it off or log out: then every call says so. Tell them; they switch it on again"},
            "pages": c.remote.pages(c.owner["id"])}


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
    """Send the whole source of a Note (one Python file: docstring, PARAMS, TAGS, build()). The server keeps it and
    never runs it: then build it on the user's computer and upload what it left (`monet.py push` does all three, and
    answers the report). Until then the report says `state` "stale" or "unbuilt" and what to run. Refused if the load
    check of the saved Note is red (stop and tell the user) or waiting (build the saved version first)."""
    p = c.ws.project(project)
    report = p.write(note, source, agent=True)
    report["canvas"] = c.canvas(project, note)
    return report


def sources(c: Caller, project: str, version: int = 0) -> dict:
    """Every Python file of a project as the server has it (version 0), or as saved version `version` has it: what
    a build is made from. `monet.py build` fetches these into a folder of its own and builds there."""
    p = c.ws.project(project)
    where = p.dir if not version else p._vpath(int(version))
    if version and not (where / "meta.json").exists():
        raise Problem(f"there is no version {version} of {project}", 404)
    return {"project": project, "version": int(version) or None,
            "files": {f.name: f.read_bytes().decode("utf-8") for f in sorted(where.glob("*.py")) if notes.NAME_RE.match(f.stem)}}


def upload(c: Caller, project: str, note: str, data: bytes, version: int | None = None) -> dict:
    """What the agent built of a Note on its own computer, as a zip (monet/build.py zipped()): taken by name, and
    only if it is a build of the files the server has."""
    p = c.ws.project(project)
    result = p.accept_build(note, build_files(data), version)
    result["canvas"] = c.canvas(project, note)
    if c.done:
        c.done("build", {"project": project, "note": note}, result)
    return result


def check(c: Caller, project: str, note: str) -> dict:
    """The Note's checks run again on its current build (none is made here). Use after the user changed something in
    the canvas: tags and joints they made are worked out again from the build. If its source (or a module it
    imports) changed since it was built, the report says so and what to run."""
    return c.ws.project(project).report(note)


def pose_values(values) -> dict:
    """Joint values as given: {"j1": 30} (JSON), or "j1=30, j2=-10" (a query string)."""
    if isinstance(values, dict):
        items = values.items()
    else:
        items = []
        for bit in str(values or "").replace(";", ",").split(","):
            if bit.strip():
                k, _, v = bit.partition("=") if "=" in bit else bit.partition(":")
                items.append((k, v))
    try:
        return {str(k).strip(): float(v) for k, v in items}
    except (TypeError, ValueError):
        raise Problem(f"joint values are name=number, comma separated, or {{name: number}}; not {values!r}") from None


def picture(p, note: str, views: str = "iso,top,front,right", version: str = "draft", tags: bool = True, pose=None) -> bytes:
    """The PNG behind look() and pose(), and behind the picture's own address."""
    glb = p.model(note, version)
    faces = highlight = parts = frames = None
    given = pose_values(pose) if pose else None
    if given:      # an assembly at a pose of its joints: the parts that clash there painted
        if str(version) != "draft":
            raise Problem("a pose is shown of the draft only")
        r, at = p.result(note), p.pose(note, given)
        described = json.loads((p.out / note / "faces.json").read_text())
        faces, parts = described["faces"], described["parts"]
        frames = joints.part_frames(r["motion"], given)
        span = {q["name"]: range(q["faces"][0], q["faces"][0] + q["faces"][1]) for q in parts}
        highlight = {f"{a} hits {b}: {v} mm³": [*span[a], *span[b]] for a, b, v in at["clashes"][:6]}
        tags = False
    if tags and str(version) == "draft":
        r = p.result(note)
        faces = json.loads((p.out / note / "faces.json").read_text())["faces"]
        highlight = {k: t["faces"] for k, t in r["tags"].items() if t.get("faces")}
        if not highlight and len(r.get("parts") or []) > 1:    # an assembly: every part in its own colour
            highlight = {q["name"]: list(range(q["faces"][0], q["faces"][0] + q["faces"][1])) for q in r["parts"]}
    names = tuple(v.strip() for v in views.split(",") if v.strip())
    title = f"{p.name}/{note} ({version})" + (f"  at {', '.join(f'{k} {v:g}' for k, v in given.items())}" if given else "")
    return render.png(glb, names, faces=faces, highlight=highlight, title=title, parts=parts, frames=frames)


def look(c: Caller, project: str, note: str, views: str = "iso,top,front,right", version: str = "draft", tags: bool = True):
    """A picture of the part: look at it, do not assume. views: any of iso, iso_back, iso_under, top, bottom, front,
    back, left, right, comma separated. version: "draft" (as built now) or a saved version number. tags: paint the
    tagged faces (draft only) with a legend, to see what each tag points at; an assembly without tags is painted
    part by part instead. Over MCP the picture comes with the
    answer; over HTTP the answer carries its address (`image`, a PNG): fetch that."""
    p = c.ws.project(project)
    png = picture(p, note, views, version, tags)
    query = urllib.parse.urlencode({"views": views, "v": version, "tags": int(bool(tags)), "r": p.rev[-8:]})
    return {"note": note, "version": str(version), "views": views, "units": "mm, Z up",
            "image": f"{c.base}/file/p/{project}/n/{note}/render.png?{query}"}, png


def pose(c: Caller, project: str, note: str, values: str = "", views: str = "iso,front"):
    """An assembly with its joints moved: what it hits there, and a picture of it. values: the joints moved by hand
    (read_note() or check() lists them under motion.joints; a joint with `follows` is worked out from the others),
    as "j1=30, j2=-10" or {"j1": 30}: degrees for a revolute joint, mm for a slider, 0 is as built. Returns every
    joint's value, the pairs of parts that newly overlap (mm³; what overlapped as built already is under
    motion.interference) and the picture, those parts painted. Each joint's own sweep, where it first hits each
    way, is in check()'s motion.sweeps."""
    p = c.ws.project(project)
    given = pose_values(values)
    out = p.pose(note, given)
    png = picture(p, note, views, "draft", False, given)
    query = urllib.parse.urlencode({"views": views, "pose": ",".join(f"{k}={v:g}" for k, v in given.items()), "r": p.rev[-8:]})
    return {"note": note, **out, "image": f"{c.base}/file/p/{project}/n/{note}/render.png?{query}"}, png


def reach(c: Caller, project: str, note: str, x: float, y: float, z: float, tip: str = "", start: str = "", views: str = "iso,front"):
    """Lead a tip of an assembly (its TIPS: a robot's nose, say) to the point x, y, z (mm, the assembly's frame) and
    find the joint values that put it there: inverse kinematics, within every joint's range, from `start` (joint
    values as in pose(); as built when empty). Returns the values, where the tip ends up, `off` (how far from the
    point: more than 0.05 mm means out of reach, and it is the nearest it gets), what that pose hits, and the
    picture. tip: which one, when there are several."""
    p = c.ws.project(project)
    r = p.result(note)
    tips = ((r.get("motion") or {}).get("tips") or {}) if r["ok"] else {}
    if not tips:
        raise Problem(f"{note} has no tips: give the Note TIPS = {{'nose': {{'on': '<part>', 'at': [x, y, z]}}}}" if r["ok"] else f"{note} does not build")
    tip = tip or next(iter(tips))
    try:
        solved = joints.solve(r["motion"], tip, [float(x), float(y), float(z)], pose_values(start) if start else {})
    except ValueError as e:
        raise Problem(str(e)) from None
    given = {k: v for k, v in solved["values"].items()}
    out = p.pose(note, given)
    png = picture(p, note, views, "draft", False, given)
    query = urllib.parse.urlencode({"views": views, "pose": ",".join(f"{k}={v:g}" for k, v in given.items()), "r": p.rev[-8:]})
    return {"note": note, "tip": tip, "target": [x, y, z], **solved, "clashes": out["clashes"],
            "image": f"{c.base}/file/p/{project}/n/{note}/render.png?{query}"}, png


def selection(c: Caller, project: str) -> dict:
    """What the user has selected in the canvas right now. They pick points, lines (edges), faces or objects (the
    parts of an assembly) and the lines of their sketches, one or many. `items` lists them: a face with its kind,
    place and size; an edge with its type, length and ends; a point with its coordinates; an object with its name and
    box; a sketch line (kind "curve") with the sketch it belongs to, the curve itself, its plane and the sketch's
    role. Each has the `selector` that would find it again as a tag. `measure` is what the canvas worked out from the selection (the distance between
    two points or two parallel faces, total length, total area). When exactly one face is selected, `face`,
    `selector` and `part` describe it directly. Call this when the user says "this face", "these edges", "here"."""
    c.ws.project(project)
    s = _selection.get((c.ws.id, project))
    if not s:
        return {"selected": False, "hint": f"nothing is selected; ask the user to click in the canvas: {c.canvas(project)}"}
    items = []
    for item in (s.get("items") or [])[:100]:
        item = dict(item)
        try:      # how each thing would be found again, were it made a tag
            item["selector"] = tagging.propose_item(item)
        except (KeyError, TypeError, ValueError):
            pass
        items.append(item)
    out = {"selected": True, "note": s.get("note"), "seconds_ago": round(time.time() - s["at"]), "mode": s.get("mode", "face"),
           "count": s.get("count", len(items) or 1), "items": items, "measure": s.get("measure") or {},
           "face": s.get("face"), "point": s.get("point"), "tags": s.get("tags", [])}
    if s.get("part"):      # in an assembly: which part the face belongs to
        out["part"] = s["part"]
    if s.get("face"):
        out["selector"] = tagging.propose(s["face"])
    return out


def _ask(c: Caller, what: str, args: dict | None = None, timeout: float = 30):
    if c.remote is None or c.owner is None:
        raise Problem("no canvas can be reached from here", 503)
    return c.remote.ask(c.owner, what, args or {}, timeout)


def screen(c: Caller) -> dict:
    """What the user's canvas shows right now, in words: the project and Note open, the area (sketch, part, assembly,
    motion), what is selected, and the text of the panel beside the view. Needs their canvas open in a browser
    (status() lists the pages). Call it when they say "what I have open", "look at my screen", "this one"."""
    return _ask(c, "screen")


def goto(c: Caller, project: str = "", note: str = "", room: str = "") -> dict:
    """Take the user's open canvas to a project, a Note in it, and/or an area: sketch, part, assembly or motion. They
    see it happen. Use it to show them what you made or changed. Answers where the canvas is now."""
    if room and room not in ("sketch", "part", "assembly", "motion"):
        raise Problem("room is sketch, part, assembly or motion")
    if project:
        c.ws.project(project)
    return _ask(c, "goto", {"project": project, "note": note, "room": room}, 60)


def view(c: Caller):
    """A picture of the user's canvas as it is on their screen: their camera, selection, pose, section and the parts
    they hid. Look at it when they talk about what they see. (`look` draws a Note on the server from fixed views;
    this is their view.) Over HTTP the answer has `image`, the address of the PNG: fetch it."""
    got = _ask(c, "view")
    png = base64.b64decode(str(got.pop("png", "") or "").split(",", 1)[-1] or b"") or None
    if not png:
        return {**got, "image": None, "hint": "no picture: use screen() for what the canvas shows"}
    c.remote.pictures[c.owner["id"]] = png
    return {**got, "image": f"{c.base}/file/view.png?n={int(time.time() * 1000):x}", "bytes": len(png)}, png


def add_check(c: Caller, project: str, note: str, what: str, min: float | None = None, max: float | None = None,
              equals: float | bool | None = None, why: str = "", id: str = "") -> dict:
    """Add a check to a Note: a measurement and the range it must stay in. what: volume_cm3, area_cm2, size_x,
    size_y, size_z, min_x..max_z, solids, fits_bed, or tag.NAME.MEASURE (the name of a tag, then one of its measures) such as tag.rod_bore.width,
    tag.rod_bore.through, tag.base.at. Of an assembly with joints: interference_mm3, joint.NAME.stop_min / stop_max
    (where moving that joint first hits something) and joint.NAME.clash_mm3 (the worst new overlap within its range). Give min and/or max, or equals. why: the rule in the user's words.
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
    """A file of the part for printing or for other CAD: 3mf, stl, step or glb. Returns a link that you can fetch
    (download it into the user's local folder if you have a shell). It carries your agent key: do not pass it on;
    the user downloads the same file from the Export panel of their canvas."""
    p = c.ws.project(project)
    path = p.export(note, format, version)
    return {"url": f"{c.base}/file/p/{project}/n/{note}/export.{format}" + ("" if str(version) == "draft" else f"?v={version}"),
            "bytes": path.stat().st_size, "format": format, "mime": EXPORTS[format]}


TOOLS = {f.__name__: f for f in (guide, status, new_project, read_note, write_note, sources, check, look, pose, reach, selection,
                                 add_check, load_check, save, versions, diff, export, screen, goto, view)}
READ_ONLY = {"guide", "status", "read_note", "sources", "check", "look", "pose", "reach", "selection", "load_check", "versions", "diff",
             "export", "screen", "view"}
TRIED = {"goto"}     # written down before it runs: the person saw the page move, whether or not it got there


def call(name: str, caller: Caller, args: dict):
    """(result dict, png bytes or None). Raises Problem for anything the caller got wrong."""
    fn = TOOLS.get(name)
    if fn is None:
        raise Problem(f"no tool {name!r}; there are: {', '.join(TOOLS)}", 404)
    try:
        inspect.signature(fn).bind(caller, **args)
    except TypeError as e:
        raise Problem(f"{name}: {e}")
    if name in TRIED and caller.done:
        caller.done(name, args, {})
    out = fn(caller, **args)
    result, png = out if isinstance(out, tuple) else (out, None)
    if caller.done and name not in READ_ONLY | TRIED and result.get("written", True) and not result.get("already"):
        caller.done(name, args, result)
    return result, png


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
