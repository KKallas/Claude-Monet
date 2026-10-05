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
                                    its <note>.glb and <note>.fingerprint.json

History is the user's own git, on their own computer: the agent commits there after
every successful save. A version here is what the viewer needs to compare and export.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import feynman, note as notes, runner, semmelweis

ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
EXPORTS = {"stl": "model/stl", "3mf": "model/3mf", "step": "model/step", "glb": "model/gltf-binary"}
MATERIALS = ("pla", "pom", "aluminium")      # what the canvas can render a part as (canvas/look.js)
BUILD_TIMEOUT = int(os.environ.get("MONET_BUILD_TIMEOUT", "180"))
BUILD_MEMORY_MB = int(os.environ.get("MONET_BUILD_MEMORY_MB", "0"))     # address space, MB; 0 = no such limit
MAX_SOURCE = 200_000

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_running: dict[tuple[str, str], float] = {}      # the builds under way now: (project folder, Note) -> when it began
_times_guard = threading.Lock()


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
    runner.limits(BUILD_TIMEOUT, BUILD_MEMORY_MB)


RUNNER_URL = os.environ.get("MONET_RUNNER_URL", "").rstrip("/")
WORKERS = min(4, os.cpu_count() or 1)      # how many Notes a save builds at once


def run_build(project_dir: Path, name: str, out_dir: Path, exports=()) -> dict:
    """Run one Note and read back what it left: in the runner, where there is one (another container, which has
    the working files and nothing else: no accounts, no session secret), else in a process of its own here."""
    if not RUNNER_URL:
        return run_build_here(project_dir, name, out_dir, exports)
    import httpx
    try:
        r = httpx.post(f"{RUNNER_URL}/build", json={"dir": str(project_dir), "note": name, "out": str(out_dir), "exports": list(exports)},
                       timeout=BUILD_TIMEOUT + 60)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        src = project_dir / f"{name}.py"
        return {"note": name, "ok": False, "error": f"the runner did not answer: {type(e).__name__}", "libs": runner.versions(),
                "deps": {src.name: _sha(src)} if src.exists() else {}}


_forks = None
_forks_guard = threading.Lock()


def forks():
    """Where builds are started from: a fork server that has the CAD kernel loaded already (monet/warm.py), so a
    build begins at once instead of after the seconds it takes to load. None where that cannot be had."""
    global _forks
    with _forks_guard:
        if _forks is None:
            try:
                import multiprocessing
                for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
                    os.environ.setdefault(key, "1")      # one build, one core; and no threads in what gets forked
                ctx = multiprocessing.get_context("forkserver")
                # Every build re-runs the server's main module on its way in. Loaded here once, that costs nothing.
                main = getattr(getattr(sys.modules.get("__main__"), "__spec__", None), "name", None) or "monet.__main__"
                ctx.set_forkserver_preload(["monet.warm"] + ([main] if main.startswith("monet.") else []))
                _forks = ctx
            except (ValueError, ImportError):
                _forks = False
    return _forks or None


def warm() -> None:
    """Start the fork server now, in the background, so the first build does not wait for it."""
    def go():
        ctx = forks()
        if ctx is not None:
            p = ctx.Process(target=print, args=("",), daemon=True)
            p.start()
            p.join(120)
    threading.Thread(target=go, daemon=True).start()


def _failed(project_dir: Path, name: str, out_dir: Path, error: str) -> dict:
    src = project_dir / f"{name}.py"
    result = {"note": name, "ok": False, "error": error, "libs": runner.versions(), "deps": {src.name: _sha(src)} if src.exists() else {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result))
    return result


def run_build_here(project_dir: Path, name: str, out_dir: Path, exports=()) -> dict:
    """Run one Note in a process of its own and read back what it left."""
    result_file = out_dir / "result.json"
    result_file.unlink(missing_ok=True)
    ctx = None if os.environ.get("MONET_COLD") else forks()
    if ctx is None:
        return run_build_cold(project_dir, name, out_dir, exports)
    import signal
    started = time.time()
    proc = ctx.Process(target=runner.child, args=(str(project_dir), name, str(out_dir), tuple(exports), BUILD_TIMEOUT, BUILD_MEMORY_MB))
    try:
        proc.start()
    except (OSError, EOFError, RuntimeError):      # no fork server to be had here: build as before, and stop asking
        global _forks
        _forks = False
        return run_build_cold(project_dir, name, out_dir, exports)
    proc.join(BUILD_TIMEOUT)
    if proc.is_alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)      # and whatever it started
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.join(10)
        return _failed(project_dir, name, out_dir, f"the build took longer than {BUILD_TIMEOUT} s and was stopped")
    if not result_file.exists():
        why = "killed: most likely it ran out of memory or CPU time" if proc.exitcode in (-9, -24, 137) else "it crashed"
        return _failed(project_dir, name, out_dir, f"the build process died (exit {proc.exitcode}): {why}")
    result = json.loads(result_file.read_text())
    result["wall"] = round(time.time() - started, 2)      # start to finish as the server saw it
    return result


def run_build_cold(project_dir: Path, name: str, out_dir: Path, exports=()) -> dict:
    """The same in a process started from nothing: every build loads the kernel again. The fallback."""
    result_file = out_dir / "result.json"
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")   # one build, one core
    try:
        proc = subprocess.run([sys.executable, "-m", "monet.runner", str(project_dir), name, str(out_dir), ",".join(exports)],
                              cwd=project_dir, env={**env, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)},
                              capture_output=True, text=True, timeout=BUILD_TIMEOUT, preexec_fn=_limits)
    except subprocess.TimeoutExpired:
        return _failed(project_dir, name, out_dir, f"the build took longer than {BUILD_TIMEOUT} s and was stopped")
    if not result_file.exists():
        why = "killed: most likely it ran out of memory or CPU time" if proc.returncode in (-9, -24, 137) else \
            (proc.stderr or proc.stdout).strip()[-600:] or "no output"
        return _failed(project_dir, name, out_dir, f"the build process died (exit {proc.returncode}): {why}")
    return json.loads(result_file.read_text())


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
            key, began = (str(self.dir), name), time.time()
            _running[key] = began
            try:
                r = run_build(self.dir, name, self.out / name, exports)
            finally:
                _running.pop(key, None)
            if r["ok"]:
                self._took(name, {"seconds": round(time.time() - began, 2), "at": now(), "kernel": r.get("seconds"), "build": r.get("build_seconds")})
            self.touch()
            return r

    def took(self) -> dict:
        """How long the last good build of each Note took, start to finish as the server saw it: {seconds, at, and
        of that: kernel (in the build process), build (in the Note's own build())}. What the next one is expected
        to take, and what the canvas shows as its progress."""
        try:
            return json.loads((self.out / ".times.json").read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _took(self, name: str, entry: dict) -> None:
        with _times_guard:
            times = {**self.took(), name: entry}
            tmp = self.out / ".times.json.new"
            tmp.write_text(json.dumps(times, indent=1))
            tmp.replace(self.out / ".times.json")

    def building(self) -> list:
        """The builds of this project under way now, with how long each has run and how long it took last time."""
        times, here = self.took(), str(self.dir)
        return [{"note": name, "since": round(time.time() - began, 1), "expect": (times.get(name) or {}).get("seconds")}
                for (folder, name), began in list(_running.items()) if folder == here]

    def report(self, name: str, result: dict | None = None) -> dict:
        """Build and checks of one Note: what the agent and the canvas both look at."""
        r = result or self.result(name)
        out = {"note": name, "built": r["ok"], "seconds": r.get("seconds")}
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
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
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
        rows, times = [], self.took()
        sources = {name: self.read(name) for name in self.files()}
        note_names = {name for name, src in sources.items() if notes.parse(src)["is_note"]}
        for name, src in sources.items():
            if name not in note_names:
                rows.append({"name": name, "kind": "module"})
                continue
            r = self.cached(name)
            fresh = self._fresh(r)
            saved_src = (self._vpath(head["n"]) / f"{name}.py") if head else None
            # an assembly is a Note whose build has several parts; before it was ever built, one that imports
            # two or more other Notes is taken for one
            assembly = len(r.get("parts") or []) > 1 if fresh and r["ok"] else len(notes.imports(src) & (note_names - {name})) > 1
            rows.append({
                "name": name, "kind": "assembly" if assembly else "note",
                "state": "unbuilt" if not fresh else "error" if not r["ok"] else "built",
                "saved": bool(head and name in head["notes"]),
                "changed": not (saved_src and saved_src.exists() and saved_src.read_text() == src),
                "seconds": (times.get(name) or {}).get("seconds"),      # of its last good build
            })
        return {"project": self.name, "rev": self.rev, "printer": self.settings.get("printer"), "material": self.settings.get("material"),
                "looks": self.settings.get("looks", {}),
                "version": head["n"] if head else None, "notes": rows, "building": self.building(), "workers": WORKERS}
