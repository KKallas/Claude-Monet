#!/usr/bin/env python3
"""monet.py: the Monet tools from a shell, and the one way to build. Standard library only (building runs Monet's
builder with uv: https://docs.astral.sh/uv/).

    The agent link: link.txt beside SKILL.md, when the skill was downloaded from the canvas (Connect your agent),
    or else  export MONET_URL=https://host/w/<agent key>

    monet.py status [project]
    monet.py pull <project> [dir]            every Note, with the saved .glb and .fingerprint.json, into dir (default .)
    monet.py push <project> <file.py>...     send Notes, build them and what uses them here, upload; prints each
                                             report, exit 1 if any is red
    monet.py build <project> [note...] [--export stl,3mf,step] [--version N]
                                             build here what is not built for its source as it is (or these Notes),
                                             first any saved version the load check waits for, and upload it
    monet.py look <project> <note> [out.png] [views]
    monet.py pose <project> <note> "j1=30, j2=-10" [out.png]   an assembly moved: what it hits, and its picture
    monet.py save <project> "message"        then: git add -A && git commit
    monet.py export <project> <note> <3mf|stl|step|glb> [out]
    monet.py tool <name> ['{"json": "arguments"}']    any tool, raw
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# the link holds the agent key: MONET_URL if it is set, else the one the skill came with from the canvas
LINK = Path(__file__).resolve().parent.parent / "link.txt"
URL = (os.environ.get("MONET_URL") or (LINK.read_text().strip() if LINK.exists() else "")).rstrip("/")


def call(tool: str, **args):
    req = urllib.request.Request(f"{URL}/agent/{tool}", json.dumps(args).encode(), {"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            sys.exit(f"monet: {json.load(e).get('error')}")
        except json.JSONDecodeError:
            sys.exit(f"monet: HTTP {e.code}")


def fetch(path: str, out: Path) -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/file{path}", timeout=600) as r:
            out.write_bytes(r.read())
        return True
    except urllib.error.HTTPError:
        return False


SKILL = Path(__file__).resolve().parent.parent
FILES = ("result.json", "faces.json", "model.glb", "model.stl", "model.3mf", "model.step")     # what a build leaves


def builder() -> list:
    """How to run Monet's builder here: the one this skill came with (pinned to its server's Monet and kernel), or,
    in Monet's own repository, the repository's."""
    if not shutil.which("uv"):
        sys.exit("monet: building needs uv (https://docs.astral.sh/uv/getting-started/installation/): install it, then run this again")
    if (SKILL / "scripts" / "builder.py").exists():
        return ["uv", "run", "--quiet", "--script", str(SKILL / "scripts" / "builder.py")]
    repo = SKILL.parent.parent
    if (repo / "monet" / "build.py").exists():
        return ["uv", "run", "--quiet", "--project", str(repo), "python", "-m", "monet.build"]
    sys.exit("monet: this skill has no builder: download it again from your canvas (Connect your agent)")


def upload(project: str, note: str, out: Path, version=None) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            if (out / f).is_file():
                z.write(out / f, f)
    url = f"{URL}/upload/{project}/{note}" + (f"?version={version}" if version else "")
    req = urllib.request.Request(url, buf.getvalue(), {"content-type": "application/zip"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return {"note": note, "green": False, "error": json.load(e).get("error")}
        except json.JSONDecodeError:
            return {"note": note, "green": False, "error": f"HTTP {e.code}"}


def build(project: str, notes=None, exports=(), version=None) -> dict:
    """Build Notes here, from the files the server has (of saved version `version`, or as they are now), and upload
    what each build left: {note: the server's answer}. Without notes: every one that is not built for its source."""
    got = call("sources", project=project, version=version or 0)
    if notes is None:
        rows = call("status", project=project)["notes"]
        notes = [n["name"] for n in rows if n.get("kind") != "module" and (version or n.get("state") in ("stale", "unbuilt"))]
    if not notes:
        return {}
    # a folder of its own: the server's files, nothing else (the user's own folder may differ)
    place = Path(os.environ.get("MONET_CACHE") or Path.home() / ".cache" / "monet") / hashlib.sha256(URL.encode()).hexdigest()[:12] / (
        project + (f"-v{version}" if version else ""))
    shutil.rmtree(place, ignore_errors=True)
    (place / "out").mkdir(parents=True)
    for name, text in got["files"].items():
        (place / name).write_bytes(text.encode("utf-8"))      # as the server has it, to the byte: what a build is checked against
    print(f"building {', '.join(notes)}" + (f" of version {version}" if version else "") + " here (the first time, uv fetches the CAD kernel) …",
          file=sys.stderr, flush=True)
    cmd = builder() + [str(place), str(place / "out")] + (["--export", ",".join(exports)] if exports else []) + list(notes)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    done = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    if not done:
        sys.exit(f"monet: the builder did not run: {(proc.stderr or proc.stdout).strip()[-1500:]}")
    answers = {}
    for row in done:
        out = place / "out" / row["note"]
        if (out / "result.json").exists():
            answers[row["note"]] = upload(project, row["note"], out, version)
        else:
            answers[row["note"]] = {"note": row["note"], "green": False, "error": row.get("error")}
        print(f"  {row['note']}: built in {row.get('seconds')} s" if row["ok"] else f"  {row['note']}: {row.get('error')}", file=sys.stderr, flush=True)
    return answers


def build_all(project: str, notes=None, exports=(), version=None) -> dict:
    """As build(); and first, unless a version was asked for: the saved Notes whose load check waits for a build of
    the saved version (as after an update of the server's kernel)."""
    if version is None:
        head = (call("versions", project=project)["versions"] or [{}])[-1].get("version")
        waiting = [n["name"] for n in call("status", project=project)["notes"]
                   if n.get("saved") and call("load_check", project=project, note=n["name"])["status"] == "waiting"]
        if head and waiting:
            for name, a in build(project, waiting, (), head).items():
                print(f"  {name} v{head}: load check {(a.get('load_check') or {}).get('status', a.get('error'))}", file=sys.stderr)
    return build(project, notes, exports, version)


def show(x):
    print(json.dumps(x, indent=1, ensure_ascii=False))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if not URL:
        sys.exit("monet: no agent link: download the skill again from your canvas (Connect your agent), or set MONET_URL to the link (https://host/w/<agent key>)")
    cmd, a = argv[0], argv[1:]
    if cmd == "status":
        show(call("status", project=a[0] if a else ""))
    elif cmd == "pull":
        project, target = a[0], Path(a[1] if len(a) > 1 else ".")
        target.mkdir(parents=True, exist_ok=True)
        versions = call("versions", project=project)["versions"]
        head = versions[-1]["version"] if versions else None
        for n in call("status", project=project)["notes"]:
            name = n["name"]
            (target / f"{name}.py").write_text(call("read_note", project=project, note=name)["source"])
            got = [f"{name}.py"]
            if n.get("saved"):   # what a saved version keeps next to the Note
                for ext, path in (("glb", f"model.glb?v={head}"), ("fingerprint.json", f"fingerprint.json?v={head}")):
                    if fetch(f"/p/{project}/n/{name}/{path}", target / f"{name}.{ext}"):
                        got.append(f"{name}.{ext}")
            print("  ".join(got))
    elif cmd == "push":
        sent = []
        for f in a[1:]:
            r = call("write_note", project=a[0], note=Path(f).stem, source=Path(f).read_text())
            if r.get("module"):
                print(f"  {Path(f).stem}: a helper module", file=sys.stderr)
            else:
                sent.append(Path(f).stem)
        built = build_all(a[0])      # what was sent, and what imports it
        red = False
        for name in sent:
            report = built.get(name) or call("check", project=a[0], note=name)
            show(report)
            red = red or not (report.get("green") or report.get("module"))
        sys.exit(1 if red else 0)
    elif cmd == "build":
        exports, version, notes = (), None, []
        it = iter(a[1:])
        for x in it:
            if x == "--export":
                exports = tuple(e for e in next(it, "").split(",") if e)
            elif x == "--version":
                version = int(next(it, "0")) or None
            else:
                notes.append(x)
        answers = build_all(a[0], notes or None, exports, version)
        if not answers:
            print("everything is built for its source as it is", file=sys.stderr)
        for name, r in answers.items():
            print(json.dumps({"note": name, "green": r.get("green"), "state": r.get("state"), "error": r.get("error"),
                              "load_check": (r.get("load_check") or {}).get("status")}, ensure_ascii=False))
        sys.exit(0 if all(r.get("green") or r.get("accepted") for r in answers.values()) else 1)
    elif cmd == "look":
        out = Path(a[2] if len(a) > 2 else f"{a[1]}.png")
        r = call("look", project=a[0], note=a[1], **({"views": a[3]} if len(a) > 3 else {}))
        with urllib.request.urlopen(r["image"], timeout=600) as img:
            out.write_bytes(img.read())
        print(out)
    elif cmd == "pose":
        out = Path(a[3] if len(a) > 3 else f"{a[1]}-pose.png")
        r = call("pose", project=a[0], note=a[1], values=a[2] if len(a) > 2 else "")
        with urllib.request.urlopen(r.pop("image"), timeout=600) as img:
            out.write_bytes(img.read())
        show(r)
        print(out)
    elif cmd == "save":
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        r = call("save", project=a[0], message=a[1] if len(a) > 1 else "", commit=commit)
        show(r)
        if r.get("saved"):
            print(f'\nnow commit:  git add -A && git commit -m "v{r["version"]}: {r["message"]}"')
        sys.exit(0 if r.get("saved") else 1)
    elif cmd == "export":
        fmt = a[2]
        out = Path(a[3] if len(a) > 3 else f"{a[1]}.{fmt}")
        if not fetch(f"/p/{a[0]}/n/{a[1]}/export.{fmt}", out):
            sys.exit("monet: export failed (does the Note build?)")
        print(out)
    elif cmd == "tool":
        show(call(a[0], **(json.loads(a[1]) if len(a) > 1 else {})))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
