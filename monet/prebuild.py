"""Monet's own templates, built before anyone opens them: a new workspace's projects open built.

    python -m monet.prebuild [templates dir]       (default: notes/)

Run when the image is made (Dockerfile) and, on your own computer, once after changing a template. It builds only
the Notes whose out/<note>/ is not of their files as they are (monet/build.py), each in a process of its own. This
is Monet's own code, from this repository: no workspace's Note is ever built on the server.
"""
import json
import sys
from pathlib import Path

from . import note as notes, runner
from .build import build

ROOT = Path(__file__).resolve().parent.parent


def current(project_dir: Path, name: str) -> bool:
    try:
        r = json.loads((project_dir / "out" / name / "result.json").read_text())
    except (OSError, ValueError):
        return False
    return r.get("libs") == runner.versions() and bool(r.get("deps")) and all(
        (project_dir / f).exists() and notes.dep_key(f, (project_dir / f).read_bytes(), name) == h for f, h in r["deps"].items())


def stale(templates: Path) -> list[tuple[Path, str]]:
    """(template folder, Note) for every template Note that has no build of its files as they are."""
    out = []
    for project in sorted(p for p in templates.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for f in sorted(project.glob("*.py")):
            if notes.NAME_RE.match(f.stem) and notes.parse(f.read_text())["is_note"] and not current(project, f.stem):
                out.append((project, f.stem))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    templates = Path(argv[0]) if argv else ROOT / "notes"
    failed = []
    for project, name in stale(templates):
        r = build(project, name, project / "out" / name)
        if r["ok"]:
            r["built"] = "monet"
            (project / "out" / name / "result.json").write_text(json.dumps(r, default=str))
        print(f"{project.name}/{name}: {'built' if r['ok'] else r.get('error')} ({r.get('wall', '?')} s)", flush=True)
        if not r["ok"]:
            failed.append(f"{project.name}/{name}")
    if failed:
        sys.exit(f"did not build: {', '.join(failed)}")


if __name__ == "__main__":
    main()
