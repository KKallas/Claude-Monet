"""Building Notes: on the agent's computer, never on the server.

The server keeps the Notes and what was built of them; whoever builds is the person's own agent, here, with the
same Monet and the same CAD kernel as the server (the skill carries both, pinned). A build runs the Note in a
process of its own (monet/runner.py) and leaves out/<note>/ as the server wants it: result.json, faces.json,
model.glb and any exports. Monet's own templates are built this way when its image is made (monet/prebuild.py).

    python -m monet.build <project dir> <out dir> [--export stl,3mf,step] <note> [<note> …]

prints one line of JSON per Note: {"note", "ok", "error", "seconds"}.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# what a build leaves and an upload carries
FILES = ("result.json", "faces.json", "model.glb", "model.stl", "model.3mf", "model.step")


def build(project_dir: Path, note: str, out_dir: Path, exports=(), timeout: float | None = None) -> dict:
    """Run one Note in a process started for it, and read back what it left."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        (out_dir / f).unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, "-m", "monet.runner", str(project_dir), note, str(out_dir), ",".join(exports)],
                              cwd=project_dir, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"note": note, "ok": False, "error": f"the build took longer than {timeout} s and was stopped"}
    result_file = out_dir / "result.json"
    if not result_file.exists():
        why = (proc.stderr or proc.stdout).strip()[-600:] or "no output"
        return {"note": note, "ok": False, "error": f"the build process died (exit {proc.returncode}): {why}"}
    result = json.loads(result_file.read_text())
    result["wall"] = round(time.time() - started, 2)
    return result


def zipped(out_dir: Path) -> bytes:
    """What a build left, as the zip an upload carries: by name, nothing else."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            if (out_dir / f).is_file():
                z.write(out_dir / f, f)
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="monet.build", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir")
    ap.add_argument("out_dir")
    ap.add_argument("notes", nargs="+")
    ap.add_argument("--export", default="", help="comma separated: stl, 3mf, step")
    args = ap.parse_args(argv)
    exports = tuple(e for e in args.export.split(",") if e)
    for note in args.notes:
        r = build(Path(args.project_dir).resolve(), note, Path(args.out_dir).resolve() / note, exports)
        print(json.dumps({"note": note, "ok": r["ok"], "error": r.get("error"), "seconds": r.get("wall")}), flush=True)


if __name__ == "__main__":
    main()
