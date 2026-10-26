"""Workspaces and projects: the working files, in a folder on the server.

Every user has one workspace: a folder named by their id (not by their name, and not by
their agent key: the place where Notes are run can list these folders, and must learn
nothing from their names that opens a door).

    <storage>/<user id>/workspace.json
    <storage>/<user id>/<project>/
        monet.json                  printer, material
        <note>.py                   the Notes, as last sent
        <note>.checks.json          the checks (the user's)
        out/<note>/                 the current build: result.json, model.glb, faces.json, exports
        versions/0001/              a save: every source file, and for each Note that changed
                                    its <note>.glb and <note>.fingerprint.json; out/<note>/ what was
                                    built of it (result.json, exports), for the load check

A project goes out and comes in as an archive: a zip of all of that but out/, which is made again.

Nothing here runs a Note. The agent builds on its own computer (monet/build.py) and uploads what the build left
(accept_build); a build is current while every file it read is as it was (but for the Note's TAGS, JOINTS, GROUND
and TIPS, which are worked out again here from what the build left: monet/derive.py).

History is the user's own git, on their own computer: the agent commits there after
every successful save. A version here is what the viewer needs to compare and export.
"""
import hashlib
import io
import json
import math
import re
import shutil
import threading
import time
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from . import derive, feynman, joints, note as notes, runner, semmelweis

ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
EXPORTS = {"stl": "model/stl", "3mf": "model/3mf", "step": "model/step", "glb": "model/gltf-binary"}
MATERIALS = ("pla", "pom", "aluminium")      # what the canvas can render a part as (canvas/look.js)
MAX_SOURCE = 200_000
MAX_ARCHIVE = 100_000_000      # bytes of a project as an archive: of the zip, and of what it unpacks to
MAX_ARCHIVE_FILES = 5000
# what an archive of a project holds, and all that is taken from one that comes in: the Notes, their checks, the
# settings, and of every saved version the same and what was kept of each Note
_NOTE = r"[a-z][a-z0-9_]{0,47}"
ARCHIVED = re.compile(rf"^(versions/[0-9]{{4}}/)?({_NOTE}\.py|{_NOTE}\.checks\.json|monet\.json)$"
                      rf"|^versions/[0-9]{{4}}/(meta\.json|{_NOTE}\.glb|{_NOTE}\.fingerprint\.json)$")

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_times_guard = threading.Lock()


class Problem(Exception):
    """Something the caller did that cannot be done. The message is for them."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_solid_cache: dict = {}


def _shapes(out_dir: Path) -> dict:
    """The parts of a build as closed meshes, for asking what overlaps: read from its preview, kept while it is."""
    glb = out_dir / "model.glb"
    key = (str(out_dir), glb.stat().st_mtime_ns)
    if key not in _solid_cache:
        from . import render
        verts, tris, _ = render.load(glb)
        parts = json.loads((out_dir / "faces.json").read_text())["parts"]
        if len(_solid_cache) > 8:
            _solid_cache.clear()
        _solid_cache[key] = joints.solids(verts, tris, parts)
    return _solid_cache[key]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# what an upload of a build may carry, each by its name
BUILT = re.compile(r"^(result\.json|faces\.json|model\.(glb|stl|3mf|step))$")
DEP = re.compile(rf"^{_NOTE}\.py$")
# what result.json has to say for the server to read it
FINGERPRINT = ("volume", "area", "bbox", "com", "solids", "faces")


def build_files(data: bytes) -> dict:
    """The files of an uploaded build, read from its zip into memory: by their names, which must be those a build
    has (BUILT), at the top of the zip. Nothing in it says where a file goes."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            files = [i for i in z.infolist() if not i.is_dir()]
            unknown = sorted(i.filename for i in files if not BUILT.match(i.filename))
            if unknown:
                raise Problem(f"not part of a build: {', '.join(unknown[:5])}")
            if sum(i.file_size for i in files) > MAX_ARCHIVE:
                raise Problem(f"that build unpacks to more than {MAX_ARCHIVE // 1_000_000} MB", 413)
            return {i.filename: z.read(i) for i in files}
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError):
        raise Problem("that is not a zip that can be read")


def _build_problem(name: str, files: dict) -> dict:
    """The result.json of an upload, if it is one the server can read; else why not (a Problem)."""
    if "result.json" not in files:
        raise Problem("a build carries result.json (and, built, faces.json and model.glb)")
    unknown = sorted(k for k in files if not BUILT.match(k))
    if unknown:
        raise Problem(f"not part of a build: {', '.join(unknown[:5])}")
    try:
        r = json.loads(files["result.json"].decode("utf-8"))
        geo = json.loads(files["faces.json"].decode("utf-8")) if "faces.json" in files else None
    except ValueError:
        raise Problem("result.json or faces.json of that build cannot be read")
    if not isinstance(r, dict) or r.get("note") != name or not isinstance(r.get("ok"), bool):
        raise Problem(f"that result.json is not of a build of {name}")
    deps = r.get("deps")
    if not isinstance(deps, dict) or f"{name}.py" not in deps or not all(DEP.match(str(k)) and isinstance(v, str) for k, v in deps.items()):
        raise Problem("that result.json does not say what the build read (deps)")
    if r["ok"]:
        fp, glb = r.get("fingerprint"), files.get("model.glb", b"")
        good = isinstance(fp, dict) and all(k in fp for k in FINGERPRINT) and isinstance(r.get("tags"), dict) \
            and isinstance(r.get("parts"), list) and isinstance(r.get("literals"), str) \
            and isinstance(geo, dict) and all(isinstance(geo.get(k), list) for k in ("faces", "parts"))
        if not good:
            raise Problem("that build is missing what a build has: fingerprint, tags, parts, literals, faces.json")
        if glb[:4] != b"glTF":
            raise Problem("model.glb of that build is not a GLB")
    return r


class Workspaces:
    def __init__(self, storage: str | Path, templates: str | Path, profiles: str | Path):
        self.storage = Path(storage).resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.templates = Path(templates)
        self.profiles = Path(profiles)
        self._guard = threading.Lock()

    def of(self, user_id: str, name: str = "") -> "Workspace":
        """The workspace of a user: made, with a copy of every template in it, the first time it is asked for."""
        if not ID_RE.match(user_id or ""):
            raise Problem("no such workspace", 404)
        with self._guard:
            fresh = not (self.storage / user_id).is_dir()
            if fresh:
                (self.storage / user_id).mkdir()
                Workspace(self, user_id).write_meta({"name": str(name or "").strip()[:80], "createdAt": now()})
        ws = Workspace(self, user_id)
        if fresh:
            for template in self.template_names():
                ws.create_project(template, template)
        return ws

    def get(self, user_id: str) -> "Workspace | None":
        if not ID_RE.match(user_id or "") or not (self.storage / user_id).is_dir():
            return None
        return Workspace(self, user_id)

    def template_names(self) -> list[str]:
        return sorted(p.name for p in self.templates.iterdir() if p.is_dir() and PROJECT_RE.match(p.name)) if self.templates.is_dir() else []

    def profile(self, kind: str, name: str) -> dict | None:
        f = self.profiles / kind / f"{name}.json"
        return json.loads(f.read_text()) if re.match(r"^[a-z0-9_]+$", name or "") and f.exists() else None


class Workspace:
    def __init__(self, all_: Workspaces, wid: str):
        self.all, self.id = all_, wid
        self.dir = all_.storage / wid

    @property
    def meta(self) -> dict:
        f = self.dir / "workspace.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def write_meta(self, meta: dict) -> None:
        (self.dir / "workspace.json").write_text(json.dumps(meta, indent=1))

    def projects(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir() if p.is_dir() and PROJECT_RE.match(p.name))

    def project(self, name: str) -> "Project":
        if not PROJECT_RE.match(name or "") or not (self.dir / name).is_dir():
            raise Problem(f"no project {name!r}; there are: {', '.join(self.projects()) or 'none yet'}", 404)
        return Project(self, name)

    def create_project(self, name: str, template: str = "") -> "Project":
        if not PROJECT_RE.match(name or ""):
            raise Problem("a project name is lowercase letters, digits, dashes or underscores")
        target = self.dir / name
        if target.exists():
            raise Problem(f"there is already a project {name!r}", 409)
        if template:
            if template not in self.all.template_names():
                raise Problem(f"no template {template!r}; there are: {', '.join(self.all.template_names())}", 404)
            # with what Monet built of its own templates when its image was made (monet/prebuild.py): they open built
            shutil.copytree(self.all.templates / template, target,
                            ignore=shutil.ignore_patterns("_*", "versions", "__pycache__", ".*"))
        else:
            target.mkdir()
        if not (target / "monet.json").exists():
            (target / "monet.json").write_text(json.dumps({"printer": "bambu_x1c", "material": "pla"}, indent=1) + "\n")
        return Project(self, name)

    def listing(self) -> list[dict]:
        """The projects, each with what tells it from the others: how many Notes, the last saved version and when."""
        out = []
        for name in self.projects():
            p = Project(self, name)
            head = p.head()
            out.append({"name": name, "notes": len(p.note_names()), "version": head["n"] if head else None, "saved": head["at"] if head else None})
        return out

    def delete_project(self, name: str) -> None:
        """The project and every saved version of it, gone from the server. The user's door only."""
        p = self.project(name)
        with p.lock:
            gone = self.dir / f".deleted-{name}-{time.time_ns()}"
            p.dir.rename(gone)      # from here on it is no project; then its files go
            shutil.rmtree(gone, ignore_errors=True)

    def import_project(self, name: str, data: bytes) -> tuple["Project", int]:
        """A project from an archive, as Project.archive() makes them: (the project, how many files of the zip were
        left out). Only what an archive holds is taken, by its name, and written here under that name: nothing in a
        zip says where a file goes. The user's door only: the checks in it become the checks."""
        if not PROJECT_RE.match(name or ""):
            raise Problem("a project name is lowercase letters, digits, dashes or underscores")
        target = self.dir / name
        if target.exists():
            raise Problem(f"there is already a project {name!r}: give this one another name", 409)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                files = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
                # zipped as a folder (as Download does) or as what is in it
                tops = {i.filename.split("/")[0] for i in files}
                folder = f"{tops.pop()}/" if len(tops) == 1 and all("/" in i.filename for i in files) else ""
                take = {i.filename[len(folder):]: i for i in files if ARCHIVED.match(i.filename[len(folder):])}
                if len(take) > MAX_ARCHIVE_FILES or sum(i.file_size for i in take.values()) > MAX_ARCHIVE:
                    raise Problem(f"that archive unpacks to more than a project may be ({MAX_ARCHIVE // 1_000_000} MB)", 413)
                got = {rel: z.read(i) for rel, i in take.items()}
        except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError):
            raise Problem("that is not a zip that can be read")
        if not any("/" not in rel for rel in got):
            raise Problem("there is nothing of a project in that archive: no Notes, no monet.json")
        docs = {}
        for rel, raw in got.items():
            if rel.endswith(".glb"):
                continue
            try:
                text = raw.decode("utf-8")
                docs[rel] = json.loads(text) if rel.endswith(".json") else text
            except ValueError:
                raise Problem(f"{rel} in that archive cannot be read")
            if rel.endswith(".json") and not isinstance(docs[rel], dict):
                raise Problem(f"{rel} in that archive is not what Monet writes there")
            if rel.endswith(".py") and "/" not in rel and len(text) > MAX_SOURCE:
                raise Problem(f"{rel} is too long for a Note")
        # a saved version is whole or it is refused: what it says of each Note has to be in the archive too
        for n in sorted({rel.split("/")[1] for rel in got if "/" in rel}):
            meta = docs.get(f"versions/{n}/meta.json") or {}
            kept = meta.get("notes")
            whole = meta.get("n") == int(n) and isinstance(meta.get("at"), str) and isinstance(meta.get("message"), str) and isinstance(kept, dict) and all(
                isinstance(v, dict) and isinstance(v.get("v"), int)
                and {"fingerprint", "tags", "libs"} <= set(docs.get(f"versions/{v['v']:04d}/{k}.fingerprint.json") or {})
                and (v["v"] != int(n) or f"versions/{n}/{k}.glb" in got) for k, v in kept.items())
            if not whole:
                raise Problem(f"version {int(n)} in that archive is not whole: it is not an archive Monet made")
        coming = self.dir / f".incoming-{name}-{time.time_ns()}"
        try:
            for rel, raw in got.items():
                (coming / rel).parent.mkdir(parents=True, exist_ok=True)
                (coming / rel).write_bytes(raw)
            if "monet.json" not in got:
                (coming / "monet.json").write_text(json.dumps({"printer": "bambu_x1c", "material": "pla"}, indent=1) + "\n")
            try:
                coming.rename(target)      # there whole, or not at all
            except OSError:
                raise Problem(f"there is already a project {name!r}: give this one another name", 409)
        finally:
            shutil.rmtree(coming, ignore_errors=True)
        return Project(self, name), len(files) - len(take)


class Project:
    def __init__(self, ws: Workspace, name: str):
        self.ws, self.name = ws, name
        self.dir = ws.dir / name
        self.out = self.dir / "out"
        self.vdir = self.dir / "versions"
        with _locks_guard:
            self.lock = _locks.setdefault(str(self.dir), threading.RLock())

    # ---- settings ----------------------------------------------------------------
    @property
    def settings(self) -> dict:
        f = self.dir / "monet.json"
        return json.loads(f.read_text()) if f.exists() else {}

    @property
    def printer(self) -> dict | None:
        return self.ws.all.profile("printers", self.settings.get("printer", ""))

    @property
    def material(self) -> dict | None:
        return self.ws.all.profile("materials", self.settings.get("material", ""))

    def set_look(self, names: list, material: str | None = None, color: str | None = "") -> dict:
        """What Notes (or the parts of an assembly, by name) are made of and their colour: how the canvas renders
        them. color None goes back to the material's own; "" leaves it as it is."""
        if material is not None and material not in MATERIALS:
            raise Problem(f"materials are: {', '.join(MATERIALS)}")
        if color and not re.match(r"^#[0-9a-fA-F]{6}$", color):
            raise Problem("a colour is #rrggbb")
        with self.lock:
            settings = self.settings
            looks = settings.setdefault("looks", {})
            for name in names:
                if not re.match(r"^[A-Za-z0-9_./-]{1,80}$", str(name)):
                    raise Problem(f"{name!r} is not the name of a Note or a part")
                entry = dict(looks.get(name, {}))
                if material is not None:
                    entry["material"] = material
                if color is None:
                    entry.pop("color", None)
                elif color:
                    entry["color"] = color.lower()
                looks[name] = entry
            (self.dir / "monet.json").write_text(json.dumps(settings, indent=1) + "\n")
            self.touch()
            return looks

    def set_animation(self, note: str, animation: dict | None) -> dict:
        """The keyframes of an assembly's joints, from the canvas's timeline: {fps, length, tracks: {joint: [[frame,
        value], …]}}, frames whole and within 0…length. None takes it away. Kept in monet.json beside the looks:
        nothing is built from it, and an archive carries it."""
        if not re.match(rf"^{_NOTE}$", str(note)):
            raise Problem(f"{note!r} is not the name of a Note")
        clean = None
        if animation is not None:
            if not isinstance(animation, dict):
                raise Problem("an animation is {fps, length, tracks}")
            fps, length, tracks = animation.get("fps", 30), animation.get("length", 120), animation.get("tracks") or {}
            if not (isinstance(fps, int) and 1 <= fps <= 120):
                raise Problem("fps is a whole number from 1 to 120")
            if not (isinstance(length, int) and 1 <= length <= 100_000):
                raise Problem("length is a whole number of frames from 1 to 100000")
            if not isinstance(tracks, dict) or len(tracks) > 200:
                raise Problem("tracks are {joint: [[frame, value], …]}, at most 200 of them")
            clean = {"fps": fps, "length": length, "tracks": {}}
            for joint, keys in tracks.items():
                if not re.match(r"^[A-Za-z0-9_.-]{1,80}$", str(joint)):
                    raise Problem(f"{joint!r} is not the name of a joint")
                if not isinstance(keys, list) or len(keys) > 5000:
                    raise Problem(f"{joint}: the keys are a list of [frame, value], at most 5000")
                kept = {}
                for k in keys:
                    ok = isinstance(k, list) and len(k) == 2 and isinstance(k[0], int) and not isinstance(k[0], bool) \
                        and isinstance(k[1], (int, float)) and not isinstance(k[1], bool) and math.isfinite(k[1])
                    if not ok or not 0 <= k[0] <= length:
                        raise Problem(f"{joint}: a key is [frame, value], the frame whole and from 0 to {length}")
                    kept[k[0]] = float(k[1])
                if kept:
                    clean["tracks"][str(joint)] = [[f, kept[f]] for f in sorted(kept)]
        with self.lock:
            settings = self.settings
            animations = settings.setdefault("animations", {})
            if clean is None:
                animations.pop(note, None)
            else:
                animations[note] = clean
            (self.dir / "monet.json").write_text(json.dumps(settings, indent=1) + "\n")
            self.touch()
            return animations

    @property
    def tolerance(self) -> float:
        return float((self.printer or {}).get("tolerance", 0.1))

    def touch(self) -> None:
        """Tell the open canvases that something changed."""
        self.out.mkdir(exist_ok=True)
        (self.out / ".rev").write_text(str(time.time_ns()))

    @property
    def rev(self) -> str:
        f = self.out / ".rev"
        return f.read_text() if f.exists() else "0"

    # ---- files -------------------------------------------------------------------
    def files(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.py") if notes.NAME_RE.match(p.stem))

    def _path(self, name: str) -> Path:
        if not notes.NAME_RE.match(name or ""):
            raise Problem("a Note's name is a Python module name: lowercase letters, digits, underscores")
        return self.dir / f"{name}.py"

    def read(self, name: str) -> str:
        p = self._path(name)
        if not p.exists():
            raise Problem(f"no Note {name!r} in {self.name}; there are: {', '.join(self.files()) or 'none yet'}", 404)
        return p.read_text()

    def is_note(self, name: str) -> bool:
        return notes.parse(self.read(name))["is_note"]

    def archive(self) -> bytes:
        """The project as a zip, in a folder of its name: to keep, or to upload here or to another Monet. The Notes,
        their checks, the settings and the saved versions; not the builds, which are made again from the Notes."""
        buf = io.BytesIO()
        with self.lock, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(self.dir.glob("*")) + sorted(self.vdir.glob("[0-9][0-9][0-9][0-9]/*")):
                rel = f.relative_to(self.dir).as_posix()
                if ARCHIVED.match(rel) and f.is_file() and not f.is_symlink():
                    z.write(f, f"{self.name}/{rel}")
        return buf.getvalue()

    def note_names(self) -> list[str]:
        return [n for n in self.files() if self.is_note(n)]

    # ---- builds (made by the agent; nothing is built here) ---------------------------
    def _building(self, name: str) -> threading.RLock:
        with _locks_guard:
            return _locks.setdefault(f"{self.dir}/{name}", threading.RLock())

    def _fresh(self, result: dict | None, where: Path | None = None) -> bool:
        """Whether a build is of the files as they are now (in the project, or in a saved version: where): with this
        server's Monet and kernel, and every file it read unchanged (the Note's own TAGS, JOINTS, GROUND and TIPS
        aside: note.geometry_key)."""
        where = where or self.dir
        if not result or not result.get("deps") or result.get("libs") != runner.versions():
            return False
        return all(DEP.match(f) and (where / f).exists() and notes.dep_key(f, (where / f).read_bytes(), result.get("note")) == h
                   for f, h in result["deps"].items())

    def _stale(self, where: Path, result: dict) -> str | None:
        """The first file a build read that is not as it was then, or what else makes it not current."""
        if result.get("libs") != runner.versions():
            return f"built with {result.get('libs')}, and this server has {runner.versions()}"
        for f, h in (result.get("deps") or {}).items():
            if not DEP.match(f) or not (where / f).exists():
                return f"{f} is not in the project"
            if notes.dep_key(f, (where / f).read_bytes(), result.get("note")) != h:
                return f"{f} is not as it was when that build was made"
        return None

    def cached(self, name: str) -> dict | None:
        f = self.out / name / "result.json"
        try:
            return json.loads(f.read_text()) if f.exists() else None
        except json.JSONDecodeError:
            return None

    def waiting(self, name: str) -> str:
        """What the agent is told when a Note has no build for its source as it is now."""
        what = "has no build for its source as it is now" if self.cached(name) else "is not built yet"
        return f"{name} {what}: your agent builds it on its own computer and uploads it (monet.py build {self.name} {name})"

    def result(self, name: str, exports=()) -> dict:
        """The current build of a Note: what the agent built for its files as they are now. None is made here: one
        that is not current is refused (409). Where only the Note's TAGS, JOINTS, GROUND or TIPS changed since (the
        person tagged a face, made a joint), its tags and joints are worked out again from what the build left."""
        source = self.read(name)
        with self._building(name):
            r = self.cached(name)
            if not self._fresh(r):
                raise Problem(self.waiting(name), 409)
            if r["ok"] and r.get("literals") != notes.literals_key(source):
                r = self._derive(name, r, source)
            missing = [e for e in exports if not (self.out / name / f"model.{e}").exists()]
            if r["ok"] and missing:
                raise Problem(f"{name} was built without {', '.join(missing)}: your agent builds it again with "
                              f"--export {','.join(missing)} (monet.py build {self.name} {name} --export {','.join(missing)})", 409)
            return r

    def _derive(self, name: str, r: dict, source: str) -> dict:
        """The build's tags and joints worked out again for the Note's TAGS, JOINTS, GROUND and TIPS as they are now,
        from what the build left (monet/derive.py): nothing of the Note is run for it."""
        from . import render
        out = self.out / name
        parsed = notes.parse(source)
        verts, tris, _ = render.load(out / "model.glb")
        geo = json.loads((out / "faces.json").read_text())
        r = dict(r)
        r["tags"], r["motion"] = derive.found({k: parsed[k] for k in ("tags", "joints", "ground", "tips")},
                                              r["fingerprint"]["bbox"], geo, verts, tris)
        r["literals"] = notes.literals_key(source)
        tmp = out / "result.json.new"
        tmp.write_text(json.dumps(r, default=str))
        tmp.replace(out / "result.json")
        return r

    def accept_build(self, name: str, files: dict, version: int | None = None) -> dict:
        """What the agent built of a Note, uploaded: {file name: bytes}. Taken only if it is a build of the files as
        they are here (in the project, or in saved version `version`), with this server's Monet and kernel; each file
        by its name, and nothing else. Answers the report (or, of a saved version, its load check)."""
        self._path(name)
        r = _build_problem(name, files)
        with self.lock, self._building(name):
            if version is None:
                where = self.dir
            else:
                where = self._vpath(int(version))
                if not (where / "meta.json").exists():
                    raise Problem(f"there is no version {version} of {self.name}", 404)
            if not (where / f"{name}.py").exists():
                raise Problem(f"there is no Note {name!r} in {self.name}" + (f" version {version}" if version is not None else ""), 404)
            why = self._stale(where, r)
            if why:
                raise Problem(f"that build of {name} is not of the files here: {why}. Build it again from them "
                              f"(monet.py build fetches them)", 409)
            r["built"] = "agent"
            files = {**files, "result.json": json.dumps(r, default=str).encode()}
            outs = where / "out"
            outs.mkdir(exist_ok=True)
            coming, gone = outs / f".incoming-{name}-{time.time_ns()}", outs / f".gone-{name}-{time.time_ns()}"
            try:
                coming.mkdir()
                for f, data in files.items():
                    (coming / f).write_bytes(data)
                if (outs / name).exists():
                    (outs / name).rename(gone)
                coming.rename(outs / name)      # the new build whole, or the old one as it was
            finally:
                shutil.rmtree(coming, ignore_errors=True)
                shutil.rmtree(gone, ignore_errors=True)
            if version is not None:
                return {"version": int(version), "accepted": True, "load_check": self.load_check(name)}
            if r["ok"]:
                self._took(name, {"seconds": r.get("wall") or r.get("seconds"), "at": now(), "by": "agent", "build": r.get("build_seconds")})
            self.touch()
        return self.report(name)

    def took(self) -> dict:
        """How long the last good build of each Note took on the agent's computer: {seconds, at, by, build (in the
        Note's own build())}."""
        try:
            return json.loads((self.out / ".times.json").read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _took(self, name: str, entry: dict) -> None:
        with _times_guard:
            self.out.mkdir(exist_ok=True)
            times = {**self.took(), name: entry}
            tmp = self.out / ".times.json.new"
            tmp.write_text(json.dumps(times, indent=1))
            tmp.replace(self.out / ".times.json")

    def report(self, name: str, result: dict | None = None) -> dict:
        """Build and checks of one Note: what the agent and the canvas both look at. A Note with no build for its
        source as it is now says so (state "stale": there is an older one; "unbuilt") and what the agent does."""
        if result is None:
            try:
                result = self.result(name)
            except Problem as e:
                if e.status != 409:
                    raise
                return {"note": name, "built": False, "state": "stale" if self.cached(name) else "unbuilt",
                        "green": False, "waiting": str(e), "checks": []}
        r = result
        out = {"note": name, "built": r["ok"], "state": "built" if r["ok"] else "error", "by": r.get("built"), "seconds": r.get("seconds")}
        if r["ok"] and self.took().get(name):
            out["took"] = self.took()[name]
            out["seconds"] = out["took"]["seconds"]
        if not r["ok"]:
            out.update(green=False, error=r.get("error"), checks=[])
            return out
        fp = r["fingerprint"]
        m = feynman.measurements(r)
        out["measure"] = {k: round(m[k], 3) for k in ("volume_cm3", "area_cm2", "size_x", "size_y", "size_z", "min_z", "max_z")}
        out["measure"].update(solids=fp["solids"], faces=fp["faces"], valid=r.get("valid", True))
        if len(r.get("parts") or []) > 1:     # an assembly: what it is made of
            out["parts"] = [{"name": q["name"], "volume_cm3": round(q["volume"] / 1000, 3),
                             "size": [round(q["bbox"][i + 3] - q["bbox"][i], 2) for i in range(3)],
                             "at": [round((q["bbox"][i + 3] + q["bbox"][i]) / 2, 2) for i in range(3)]} for q in r["parts"]]
        out["tags"] = {k: {"resolved": t["resolved"], **({"why": t["why"]} if t.get("why") else {}), "measure": t.get("measure", {})}
                       for k, t in r["tags"].items()}
        rows = [{"id": f"tag-{k}", "what": f"tag.{k}.resolved", "ok": bool(t["resolved"]), "value": bool(t["resolved"]), "expect": "= True",
                 "why": t.get("why") or "every tag must still find its feature", "by": "monet"} for k, t in r["tags"].items()]
        if not r.get("valid", True):
            rows.append({"id": "valid", "what": "valid", "ok": False, "value": False, "expect": "= True", "why": "the solid is not valid geometry", "by": "monet"})
        mo = r.get("motion")
        if mo:
            out["motion"] = mo      # how the parts may move, and what moving them hits: the canvas poses them by it
            rows += [{"id": f"joint-{k}", "what": f"joint.{k}.resolved", "ok": bool(j["resolved"]), "value": bool(j["resolved"]), "expect": "= True",
                      "why": j.get("why") or "every joint must find its parts and its axis", "by": "monet"} for k, j in mo["joints"].items()]
            if mo["problems"]:
                rows.append({"id": "joints", "what": "joints", "ok": False, "value": False, "expect": "= True", "why": "; ".join(mo["problems"]), "by": "monet"})
        out["checks"] = rows + feynman.evaluate(self.checks(name), r, self.printer)
        out["green"] = all(c["ok"] for c in out["checks"])
        return out

    # ---- writing -----------------------------------------------------------------
    def write(self, name: str, source: str, agent: bool = False) -> dict:
        path = self._path(name)
        if len(source) > MAX_SOURCE:
            raise Problem("that is too long for a Note")
        parsed = notes.parse(source)
        with self.lock:
            if agent and path.exists() and self.is_note(name):
                lc = self.load_check(name)
                if lc["status"] == "red" and not lc.get("acknowledged"):
                    raise Problem(f"load check is RED for {name}: the saved part no longer rebuilds to what was saved "
                                  f"({'; '.join(c['what'] for c in lc['changes'][:4])}). Do not edit it. Ask the user to look at it in "
                                  "the canvas and acknowledge; only they can.", 409)
                if lc["status"] == "waiting":
                    raise Problem(f"load check of {name} is waiting: {lc['message']}. Then edit it.", 409)
            path.write_text(source if source.endswith("\n") else source + "\n")
            self.touch()
            if parsed["error"] and "syntax" in parsed["error"]:
                return {"note": name, "built": False, "green": False, "error": parsed["error"], "checks": []}
            if not parsed["is_note"]:
                return {"note": name, "module": True, "green": True,
                        "message": "saved as a helper module (no build() in it); the Notes that import it need building again (monet.py build)"}
            report = self.report(name)
            if parsed["error"]:
                report["warning"] = parsed["error"]
            return report

    def delete(self, name: str) -> None:
        with self.lock:
            self.read(name)
            self._path(name).unlink()
            (self.dir / f"{name}.checks.json").unlink(missing_ok=True)
            shutil.rmtree(self.out / name, ignore_errors=True)
            self.touch()

    def set_tags(self, name: str, tags: dict) -> dict:
        with self.lock:
            return self.write(name, notes.set_tags(self.read(name), tags))

    def set_joints(self, name: str, joints: dict, ground=None) -> dict:
        with self.lock:
            return self.write(name, notes.set_joints(self.read(name), joints, ground))

    def pose(self, name: str, given: dict | None = None, free: dict | None = None) -> dict:
        """What the parts hit with the joints at these values (and free parts where `free` puts them): from the
        build's own mesh. Nothing of the Note is run for it."""
        r = self.result(name)
        if not r["ok"] or not r.get("motion"):
            raise Problem(f"{name} has no joints to move" if r["ok"] else f"{name} does not build", 404)
        mo = r["motion"]
        unknown = [k for k in (given or {}) if k not in mo["joints"]]
        if unknown:
            raise Problem(f"no joint {', '.join(map(repr, unknown))} in {name}; there are: {', '.join(mo['joints'])}")
        shapes = _shapes(self.out / name)
        return {"values": {k: round(v, 4) for k, v in joints.values(mo, given).items()},
                "clashes": joints.pose_clashes(mo, shapes, given, free), "unchecked": mo.get("unchecked", [])}

    # ---- checks (Feynman) --------------------------------------------------------
    def _checks_file(self, name: str) -> Path:
        self._path(name)
        return self.dir / f"{name}.checks.json"

    def checks(self, name: str) -> list:
        return feynman.load(self._checks_file(name))

    def add_check(self, name: str, check: dict, by: str) -> dict:
        with self.lock:
            self.read(name)
            c = feynman.clean(check, by)
            have = self.checks(name)
            if any(x["id"] == c["id"] for x in have):
                raise Problem(f"there is already a check {c['id']!r} on {name}" + (": checks are the user's, an agent can add one but not change one" if by == "agent" else ""), 409)
            feynman.store(self._checks_file(name), have + [c])
            self.touch()
            return c

    def put_check(self, name: str, check_id: str, check: dict | None) -> None:
        """Change or (None) remove a check. The user's door only."""
        with self.lock:
            have = self.checks(name)
            if not any(x["id"] == check_id for x in have):
                raise Problem(f"no check {check_id!r} on {name}", 404)
            new = [] if check is None else [feynman.clean({**check, "id": check_id}, "user")]
            feynman.store(self._checks_file(name), [y for x in have for y in (new if x["id"] == check_id else [x])])
            self.touch()

    # ---- versions ----------------------------------------------------------------
    def versions(self, name: str | None = None) -> list[dict]:
        out = []
        for d in sorted(self.vdir.glob("[0-9][0-9][0-9][0-9]")) if self.vdir.is_dir() else []:
            if not (d / "meta.json").exists():
                continue
            meta = json.loads((d / "meta.json").read_text())
            if name is None or meta["notes"].get(name, {}).get("v") == meta["n"]:
                out.append(meta)
        return out

    def head(self) -> dict | None:
        v = self.versions()
        return v[-1] if v else None

    def _vpath(self, n: int) -> Path:
        return self.vdir / f"{int(n):04d}"

    def saved(self, name: str, version: int | None = None) -> dict | None:
        """{"fingerprint", "tags", "libs", "v"} of a Note as saved (latest when no version is given)."""
        meta = self.head() if version is None else next((m for m in self.versions() if m["n"] == int(version)), None)
        if not meta or name not in meta["notes"]:
            return None
        v = meta["notes"][name]["v"]
        return {**json.loads((self._vpath(v) / f"{name}.fingerprint.json").read_text()), "v": v}

    def save(self, message: str = "", commit: str = "") -> dict:
        """Nothing is saved on red: every Note must be built for its source as it is and pass its checks. Then the
        whole project is one version."""
        with self.lock:
            names = self.note_names()
            if not names:
                raise Problem("there is no Note to save yet")
            reports = {n: self.report(n) for n in names}
            waiting = {n: r["waiting"] for n, r in reports.items() if r.get("waiting")}
            if waiting:
                return {"saved": False, "waiting": waiting,
                        "message": "nothing is saved before every Note is built for its source as it is: monet.py build "
                                   f"{self.name} builds them all, then save again"}
            red = {n: r for n, r in reports.items() if not r["green"]}
            if red:
                why = {n: r.get("error") or [f"{c['id']}: {c['what']} is {c['value']}, must be {c['expect']}" for c in r["checks"] if not c["ok"]]
                       for n, r in red.items()}
                return {"saved": False, "red": why, "message": "nothing is saved on red: fix the geometry (never the checks), then save again"}
            head = self.head()
            if head and not self.status_changed(head):
                return {"saved": True, "version": head["n"], "changed": [], "unchanged": True,
                        "message": "nothing has changed since this version: no new one was made"}
            n = (head["n"] + 1) if head else 1
            # written beside the versions and moved into place whole: a version is there entirely or not at all
            vdir = self.vdir / f".saving-{n:04d}"
            shutil.rmtree(vdir, ignore_errors=True)
            vdir.mkdir(parents=True)
            for f in list(self.dir.glob("*.py")) + list(self.dir.glob("*.checks.json")) + [self.dir / "monet.json"]:
                if f.exists():
                    shutil.copy2(f, vdir / f.name)
            meta = {"n": n, "at": now(), "message": str(message).strip()[:300], "commit": str(commit).strip()[:64], "notes": {}}
            changed = []
            for name in names:
                # what was built of it, kept with the version: its load check, and exports of the version
                (vdir / "out" / name).mkdir(parents=True)
                for f in ("result.json", "model.stl", "model.3mf", "model.step"):
                    if (self.out / name / f).exists():
                        shutil.copy2(self.out / name / f, vdir / "out" / name / f)
                r = self.cached(name)
                fp = {"fingerprint": r["fingerprint"], "tags": {k: {"resolved": t["resolved"], "measure": t.get("measure", {})} for k, t in r["tags"].items()},
                      "libs": r["libs"], "params": r.get("params", {})}
                before = self.saved(name)
                if before and before["fingerprint"] == fp["fingerprint"] and before["tags"] == fp["tags"]:
                    meta["notes"][name] = {"v": before["v"]}
                    continue
                shutil.copy2(self.out / name / "model.glb", vdir / f"{name}.glb")
                (vdir / f"{name}.fingerprint.json").write_text(json.dumps(fp, indent=1))
                meta["notes"][name] = {"v": n}
                changed.append(name)
            (vdir / "meta.json").write_text(json.dumps(meta, indent=1))
            vdir.rename(self._vpath(n))
            # what was just built is what was just saved: the load check of this version starts green
            self._load_cache_write({name: {"status": "green", "tolerance": self.tolerance, "changes": []} for name in names}, n)
            self.touch()
            return {"saved": True, "version": n, "changed": changed, "message": meta["message"]}

    def status_changed(self, head: dict) -> bool:
        """Whether any file a version keeps differs from that version (so a save asked for twice is one save)."""
        src = self._vpath(head["n"])
        now = {f.name: f.read_bytes() for f in list(self.dir.glob("*.py")) + list(self.dir.glob("*.checks.json")) + [self.dir / "monet.json"] if f.exists()}
        then = {f.name: f.read_bytes() for f in list(src.glob("*.py")) + list(src.glob("*.checks.json")) + [src / "monet.json"] if f.exists()}
        return now != then

    def model(self, name: str, version: str | int = "draft", last: bool = False) -> Path:
        """The GLB of the draft or of a saved version. last: the draft's last build even when it is not of the source
        as it is now (the canvas shows it, marked so, while the agent builds)."""
        if str(version) in ("draft", "", "None"):
            if not last:
                self.result(name)
            p = self.out / name / "model.glb"
        else:
            s = self.saved(name, int(version))
            if not s:
                raise Problem(f"{name} is not in version {version}", 404)
            p = self._vpath(s["v"]) / f"{name}.glb"
        if not p.exists():
            raise Problem(f"{name} has no model: it does not build", 404)
        return p

    def export(self, name: str, fmt: str, version: str | int = "draft") -> Path:
        if fmt not in EXPORTS:
            raise Problem(f"export as one of: {', '.join(EXPORTS)}")
        if fmt == "glb":
            return self.model(name, version)
        if str(version) in ("draft", "", "None"):
            r = self.result(name, exports=(fmt,))
            out = self.out / name
        else:
            src = self._vpath(int(version))
            if not (src / f"{name}.py").exists():
                raise Problem(f"{name} is not in version {version}", 404)
            out = src / "out" / name
            if not (out / f"model.{fmt}").exists():
                raise Problem(f"version {version} of {name} was built without {fmt}: your agent builds that version with "
                              f"--export {fmt} (monet.py build {self.name} {name} --version {int(version)} --export {fmt})", 409)
            r = json.loads((out / "result.json").read_text())
        if not r["ok"]:
            raise Problem(f"{name} does not build: {r.get('error')}", 409)
        return out / f"model.{fmt}"

    # ---- load check (Semmelweis) -------------------------------------------------
    def _load_cache(self) -> dict:
        f = self.out / ".loadcheck.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def _load_cache_write(self, entries: dict, n: int) -> None:
        self.out.mkdir(exist_ok=True)
        cache = self._load_cache()
        key = f"{n}|{json.dumps(runner.versions(), sort_keys=True)}"
        cache = {"key": key, "notes": {**(cache.get("notes", {}) if cache.get("key") == key else {}), **entries}}
        (self.out / ".loadcheck.json").write_text(json.dumps(cache))

    def load_check(self, name: str) -> dict:
        """The saved Note built again from its saved source, with the Monet and kernel this server has now, compared
        with what was saved. The build is the agent's (of the version's files, uploaded); until there is one, the
        load check is "waiting"."""
        with self.lock:
            saved = self.saved(name)
            head = self.head()
            if not saved:
                return {"status": "new", "changes": [], "message": "never saved: nothing to compare with"}
            cache = self._load_cache()
            key = f"{head['n']}|{json.dumps(runner.versions(), sort_keys=True)}"
            if cache.get("key") == key and name in cache.get("notes", {}):
                return {**cache["notes"][name], "version": head["n"]}
            src = self._vpath(head["n"])
            try:
                r = json.loads((src / "out" / name / "result.json").read_text())
            except (OSError, ValueError):
                r = None
            if not self._fresh(r, src):
                return {"status": "waiting", "changes": [], "version": head["n"],
                        "message": f"version {head['n']} of {name} has to be built again with this server's Monet and kernel "
                                   f"(monet.py build {self.name} does that first)"}
            if not r["ok"]:
                lc = {"status": "red", "tolerance": self.tolerance, "changes": [{"what": "build", "level": "red", "why": r.get("error")}]}
            else:
                lc = semmelweis.compare(saved, r, self.tolerance)
            if saved["libs"] != r.get("libs"):
                lc["libs"] = {"saved_with": saved["libs"], "now": r.get("libs")}
            self._load_cache_write({name: lc}, head["n"])
            return {**lc, "version": head["n"]}

    def acknowledge(self, name: str) -> dict:
        """The user has looked at a red or yellow load check. Their door only."""
        with self.lock:
            lc = self.load_check(name)
            lc.pop("version", None)
            lc["acknowledged"] = now()
            self._load_cache_write({name: lc}, self.head()["n"])
            self.touch()
            return lc

    # ---- diff --------------------------------------------------------------------
    def state_of(self, name: str, version: str | int) -> dict | None:
        if str(version) == "draft":
            r = self.result(name)
            return {"fingerprint": r["fingerprint"], "tags": r["tags"]} if r["ok"] else None
        return self.saved(name, int(version))

    def diff(self, name: str, a: str | int, b: str | int = "draft", tol: float | None = None) -> dict:
        from . import diff as differ
        tol = float(tol or self.tolerance)
        sa, sb = self.state_of(name, a), self.state_of(name, b)
        if not sa or not sb:
            raise Problem(f"cannot compare {name} {a} with {b}: one of them has no build", 404)
        out = self.out / ".diff" / f"{name}-{a}-{b}-{tol}"
        pa, pb = self.model(name, a), self.model(name, b)
        stamp = f"{_sha(pa)}{_sha(pb)}"
        summary_file = out / "summary.json"
        if summary_file.exists() and json.loads(summary_file.read_text()).get("stamp") == stamp:
            return json.loads(summary_file.read_text())
        out.mkdir(parents=True, exist_ok=True)
        summary = differ.colour_maps(pa, pb, tol, out / "a.glb", out / "b.glb")
        summary.update(note=name, a=str(a), b=str(b), stamp=stamp, numbers=differ.numbers(sa, sb), tags=differ.tag_changes(sa, sb, tol))
        summary_file.write_text(json.dumps(summary))
        return summary

    def diff_model(self, name: str, a, b, side: str, tol: float | None = None) -> Path:
        self.diff(name, a, b, tol)
        return self.out / ".diff" / f"{name}-{a}-{b}-{float(tol or self.tolerance)}" / ("a.glb" if side == "a" else "b.glb")

    # ---- the whole picture -------------------------------------------------------
    def status(self) -> dict:
        head = self.head()
        rows, times = [], self.took()
        sources = {name: self.read(name) for name in self.files()}
        parsed = {name: notes.parse(src) for name, src in sources.items()}
        note_names = {name for name, d in parsed.items() if d["is_note"]}
        for name, src in sources.items():
            if name not in note_names:
                rows.append({"name": name, "kind": "module"})
                continue
            r = self.cached(name)
            fresh = self._fresh(r)
            saved_src = (self._vpath(head["n"]) / f"{name}.py") if head else None
            # an assembly is a Note whose build has several parts; before it was ever built, one that says how its
            # parts move (JOINTS) or imports two or more other Notes is taken for one
            assembly = len(r.get("parts") or []) > 1 if r and r.get("ok") else bool(parsed[name]["joints"]) or len(notes.imports(src) & (note_names - {name})) > 1
            rows.append({
                "name": name, "kind": "assembly" if assembly else "note",
                # stale: the agent has not built it since its files changed; its last build is still there to look at
                "state": ("stale" if r else "unbuilt") if not fresh else "error" if not r["ok"] else "built",
                "saved": bool(head and name in head["notes"]),
                "changed": not (saved_src and saved_src.exists() and saved_src.read_text() == src),
                "seconds": (times.get(name) or {}).get("seconds"),      # of its last good build, on the agent's computer
            })
        return {"project": self.name, "rev": self.rev, "printer": self.settings.get("printer"), "material": self.settings.get("material"),
                "looks": self.settings.get("looks", {}),
                "animations": self.settings.get("animations", {}),
                "version": head["n"] if head else None, "notes": rows}
