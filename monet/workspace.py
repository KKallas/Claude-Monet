"""Workspaces and projects: the working files, in a folder on the server.

No accounts. A workspace is an unguessable id; whoever holds its link is its user, in a
browser (/w/<id>) or through their own agent (/w/<id>/mcp). The only limit is how many
workspaces there may be.

    <storage>/<workspace id>/workspace.json
    <storage>/<workspace id>/<project>/
        monet.json                  printer, material
        <note>.py                   the Notes, as last sent
        <note>.checks.json          the checks (the user's)
        out/<note>/                 the current build: result.json, model.glb, faces.json, exports
        versions/0001/              a save: every source file, and for each Note that changed
                                    its <note>.glb and <note>.fingerprint.json

History is the user's own git, on their own computer: the agent commits there after
every successful save. A version here is what the viewer needs to compare and export.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import feynman, note as notes, runner, semmelweis

ID_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
EXPORTS = {"stl": "model/stl", "3mf": "model/3mf", "step": "model/step", "glb": "model/gltf-binary"}
BUILD_TIMEOUT = int(os.environ.get("MONET_BUILD_TIMEOUT", "180"))
BUILD_MEMORY_MB = int(os.environ.get("MONET_BUILD_MEMORY_MB", "3000"))
MAX_SOURCE = 200_000

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


class Problem(Exception):
    """Something the caller did that cannot be done. The message is for them."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _limits():
    """In the build process: a Note may not run for ever or eat the machine."""
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (BUILD_TIMEOUT, BUILD_TIMEOUT + 5))
    if sys.platform.startswith("linux"):
        cap = BUILD_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    os.setsid()


def run_build(project_dir: Path, name: str, out_dir: Path, exports=()) -> dict:
    """Run one Note in its own process and read back what it left."""
    result_file = out_dir / "result.json"
    result_file.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    error = None
    try:
        proc = subprocess.run([sys.executable, "-m", "monet.runner", str(project_dir), name, str(out_dir), ",".join(exports)],
                              cwd=project_dir, env={**env, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)},
                              capture_output=True, text=True, timeout=BUILD_TIMEOUT, preexec_fn=_limits)
        if not result_file.exists():
            error = f"the build process died (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[-600:] or 'no output'}"
    except subprocess.TimeoutExpired:
        error = f"the build took longer than {BUILD_TIMEOUT} s and was stopped"
    if error:
        src = project_dir / f"{name}.py"
        result = {"note": name, "ok": False, "error": error, "libs": runner.versions(),
                  "deps": {src.name: _sha(src)} if src.exists() else {}}
        out_dir.mkdir(parents=True, exist_ok=True)
        result_file.write_text(json.dumps(result))
        return result
    return json.loads(result_file.read_text())


class Workspaces:
    def __init__(self, storage: str | Path, templates: str | Path, profiles: str | Path, max_users: int = 20):
        self.storage = Path(storage).resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.templates = Path(templates)
        self.profiles = Path(profiles)
        self.max_users = max_users
        self._guard = threading.Lock()

    def ids(self) -> list[str]:
        return [p.name for p in self.storage.iterdir() if p.is_dir() and ID_RE.match(p.name)]

    def count(self) -> int:
        return len(self.ids())

    def create(self, name: str = "") -> "Workspace":
        with self._guard:
            if self.count() >= self.max_users:
                raise Problem(f"all {self.max_users} workspaces of this instance are in use", 503)
            wid = secrets.token_urlsafe(12)
            (self.storage / wid).mkdir()
            ws = Workspace(self, wid)
            ws.write_meta({"name": str(name or "").strip()[:60], "createdAt": now()})
        for template in self.template_names():
            ws.create_project(template, template)
        return ws

    def get(self, wid: str) -> "Workspace | None":
        if not ID_RE.match(wid or "") or not (self.storage / wid).is_dir():
            return None
        return Workspace(self, wid)

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
            shutil.copytree(self.all.templates / template, target,
                            ignore=shutil.ignore_patterns("_*", "out", "versions", "__pycache__", ".*"))
        else:
            target.mkdir()
        if not (target / "monet.json").exists():
            (target / "monet.json").write_text(json.dumps({"printer": "bambu_x1c", "material": "pla"}, indent=1) + "\n")
        return Project(self, name)


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

    def note_names(self) -> list[str]:
        return [n for n in self.files() if self.is_note(n)]

    # ---- building ----------------------------------------------------------------
    def _building(self, name: str) -> threading.RLock:
        with _locks_guard:
            return _locks.setdefault(f"{self.dir}/{name}", threading.RLock())

    def _fresh(self, result: dict | None) -> bool:
        if not result or not result.get("deps") or result.get("libs") != runner.versions():
            return False
        return all((self.dir / f).exists() and _sha(self.dir / f) == h for f, h in result["deps"].items())

    def cached(self, name: str) -> dict | None:
        f = self.out / name / "result.json"
        try:
            return json.loads(f.read_text()) if f.exists() else None
        except json.JSONDecodeError:
            return None

    def result(self, name: str, exports=()) -> dict:
        """The build of a Note as its files are now: from the cache when nothing it read has changed."""
        self.read(name)
        with self._building(name):   # per Note, so a save can build several at once while it holds the project
            r = self.cached(name)
            have = all((self.out / name / f"model.{e}").exists() for e in exports)
            if self._fresh(r) and (have or not r["ok"]):
                return r
            r = run_build(self.dir, name, self.out / name, exports)
            self.touch()
            return r

    def report(self, name: str, result: dict | None = None) -> dict:
        """Build and checks of one Note: what the agent and the canvas both look at."""
        r = result or self.result(name)
        out = {"note": name, "built": r["ok"], "seconds": r.get("seconds")}
        if not r["ok"]:
            out.update(green=False, error=r.get("error"), checks=[])
            return out
        fp = r["fingerprint"]
        m = feynman.measurements(r)
        out["measure"] = {k: round(m[k], 3) for k in ("volume_cm3", "area_cm2", "size_x", "size_y", "size_z", "min_z", "max_z")}
        out["measure"].update(solids=fp["solids"], faces=fp["faces"], valid=r.get("valid", True))
        out["tags"] = {k: {"resolved": t["resolved"], **({"why": t["why"]} if t.get("why") else {}), "measure": t.get("measure", {})}
                       for k, t in r["tags"].items()}
        rows = [{"id": f"tag-{k}", "what": f"tag.{k}.resolved", "ok": bool(t["resolved"]), "value": bool(t["resolved"]), "expect": "= True",
                 "why": t.get("why") or "every tag must still find its feature", "by": "monet"} for k, t in r["tags"].items()]
        if not r.get("valid", True):
            rows.append({"id": "valid", "what": "valid", "ok": False, "value": False, "expect": "= True", "why": "the solid is not valid geometry", "by": "monet"})
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
            path.write_text(source if source.endswith("\n") else source + "\n")
            self.touch()
            if parsed["error"] and "syntax" in parsed["error"]:
                return {"note": name, "built": False, "green": False, "error": parsed["error"], "checks": []}
            if not parsed["is_note"]:
                return {"note": name, "module": True, "green": True,
                        "message": "saved as a helper module (no build() in it); Notes that import it rebuild on their next check"}
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
        """Nothing is saved on red: every Note must build and pass its checks. Then the whole project is one version."""
        with self.lock:
            names = self.note_names()
            if not names:
                raise Problem("there is no Note to save yet")
            with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
                reports = dict(zip(names, pool.map(self.report, names)))
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

    def model(self, name: str, version: str | int = "draft") -> Path:
        """The GLB of the draft or of a saved version."""
        if str(version) in ("draft", "", "None"):
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
            with self.lock:
                r = json.loads((out / "result.json").read_text()) if (out / f"model.{fmt}").exists() else run_build(src, name, out, (fmt,))
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
        """Rebuild the saved Note from its saved source, here and now, and compare with what was saved."""
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
            r = run_build(src, name, src / "out" / name)
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
        rows = []
        for name in self.files():
            src = self.read(name)
            if not notes.parse(src)["is_note"]:
                rows.append({"name": name, "kind": "module"})
                continue
            r = self.cached(name)
            fresh = self._fresh(r)
            saved_src = (self._vpath(head["n"]) / f"{name}.py") if head else None
            rows.append({
                "name": name, "kind": "note",
                "state": "unbuilt" if not fresh else "error" if not r["ok"] else "built",
                "saved": bool(head and name in head["notes"]),
                "changed": not (saved_src and saved_src.exists() and saved_src.read_text() == src),
            })
        return {"project": self.name, "rev": self.rev, "printer": self.settings.get("printer"), "material": self.settings.get("material"),
                "version": head["n"] if head else None, "notes": rows}
