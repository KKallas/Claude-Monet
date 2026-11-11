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
    monet.py animate <project> <note> <keys.json>    keyframes on the timeline: {"fps", "length", "tracks": {joint: [[frame, value], …]}}
                                             ("none" takes the animation away)
    monet.py render-animation <project> <note> [out.gif|out.mp4] [view] [fps]   the timeline as a GIF or MP4, rendered by the server
    monet.py bom <project> <note> [out.csv]  the bill of materials; with out.csv, also as a spreadsheet
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
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# the link holds the agent key: MONET_URL if it is set, else the one the skill came with from the canvas
LINK = Path(__file__).resolve().parent.parent / "link.txt"
URL = (os.environ.get("MONET_URL") or (LINK.read_text().strip() if LINK.exists() else "")).rstrip("/")


# seconds to wait before each try again, when the server cannot be reached
RETRIES = tuple(float(x) for x in (os.environ.get("MONET_RETRIES") or "1,3,9").split(",") if x.strip())
STEP = ["starting"]       # the last thing that was done, for the one line said when the server cannot be reached


def done(what: str) -> None:
    """Say a step finished, as it finishes: a retry after a cut connection then starts from a known place."""
    STEP[0] = what
    print(f"  {what}", file=sys.stderr, flush=True)


def _host() -> str:
    return urllib.parse.urlsplit(URL).netloc or "the server"      # never the path: it holds the agent key


def _open(req, what: str):
    """urlopen, tried again when the server cannot be reached (a timeout, a dropped connection); an answer from the
    server, even an error, is not tried again. In the end one line, never a traceback and never the link."""
    for wait in (*RETRIES, None):
        try:
            return urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            if wait is None:
                sys.exit(f"monet: cannot reach {_host()} ({_why(reason)}) while {what}; nothing after \"{STEP[0]}\" was done: "
                         "run the same command again")
            print(f"  {_host()} did not answer ({_why(reason)}): trying again in {wait} s", file=sys.stderr, flush=True)
            time.sleep(wait)


def _why(reason) -> str:
    text = str(getattr(reason, "strerror", None) or reason)
    return "timed out" if "timed out" in text.lower() else text.replace(URL, _host())[:120]


def _read(req, what: str):
    """The answer's bytes; a connection that drops half way through an answer is tried again too."""
    for wait in (*RETRIES, None):
        r = _open(req, what)
        try:
            with r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if wait is None:
                sys.exit(f"monet: cannot reach {_host()} ({_why(e)}) while {what}; nothing after \"{STEP[0]}\" was done: "
                         "run the same command again")
            time.sleep(wait)


def call(tool: str, **args):
    req = urllib.request.Request(f"{URL}/agent/{tool}", json.dumps(args).encode(), {"content-type": "application/json"})
    try:
        return json.loads(_read(req, f"asking {tool}"))
    except urllib.error.HTTPError as e:
        try:
            sys.exit(f"monet: {json.load(e).get('error')}")
        except json.JSONDecodeError:
            sys.exit(f"monet: HTTP {e.code}")


def fetch(path: str, out: Path) -> bool:
    try:
        out.write_bytes(_read(f"{URL}/file{path}", f"fetching {path.split('?')[0]}"))
        return True
    except urllib.error.HTTPError:
        return False


def get(url: str, out: Path, what: str) -> None:
    """A file an answer pointed at (a picture, an animation)."""
    try:
        out.write_bytes(_read(url, what))
    except urllib.error.HTTPError as e:
        sys.exit(f"monet: HTTP {e.code} while {what}")


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
        return json.loads(_read(req, f"uploading {note}"))
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
    # each Note is uploaded as soon as it is built: a connection lost half way leaves what was done done, and said
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    answers, ran = {}, False
    for line in proc.stdout:
        if not line.startswith("{"):
            continue
        ran, row = True, json.loads(line)
        name, out = row["note"], place / "out" / row["note"]
        what = f"{name}" + (f" v{version}" if version else "")
        if row["ok"]:
            done(f"built {what} in {row.get('seconds')} s")
        else:
            print(f"  {what}: {row.get('error')}", file=sys.stderr, flush=True)
        if (out / "result.json").exists():
            answers[name] = upload(project, name, out, version)
            if answers[name].get("error"):
                print(f"  {what}: upload refused: {answers[name]['error']}", file=sys.stderr, flush=True)
            else:
                done(f"uploaded {what}")
        else:
            answers[name] = {"note": name, "green": False, "error": row.get("error")}
    err = proc.stderr.read()
    proc.wait()
    if not ran:
        sys.exit(f"monet: the builder did not run: {err.strip()[-1500:]}")
    return answers


def summary(project: str) -> None:
    """Where the project stands now, as status(project) has it: what is built, and what still waits for a build."""
    rows = [n for n in call("status", project=project)["notes"] if n.get("kind") != "module"]
    built = [n["name"] for n in rows if n.get("state") == "built"]
    error = [n["name"] for n in rows if n.get("state") == "error"]
    waiting = [n["name"] for n in rows if n.get("state") in ("stale", "unbuilt")]
    print(f"{project}: built {', '.join(built) or 'nothing'}" + (f"; does not build: {', '.join(error)}" if error else "")
          + (f"; still waiting for a build: {', '.join(waiting)} (monet.py build {project})" if waiting else "; nothing waits for a build"),
          file=sys.stderr, flush=True)


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
            done(f"sent {Path(f).name}")
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
        summary(a[0])
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
        summary(a[0])
        sys.exit(0 if all(r.get("green") or r.get("accepted") for r in answers.values()) else 1)
    elif cmd == "look":
        out = Path(a[2] if len(a) > 2 else f"{a[1]}.png")
        r = call("look", project=a[0], note=a[1], **({"views": a[3]} if len(a) > 3 else {}))
        get(r["image"], out, "fetching the picture")
        print(out)
    elif cmd == "pose":
        out = Path(a[3] if len(a) > 3 else f"{a[1]}-pose.png")
        r = call("pose", project=a[0], note=a[1], values=a[2] if len(a) > 2 else "")
        get(r.pop("image"), out, "fetching the picture")
        show(r)
        print(out)
    elif cmd == "animate":
        keys = None if a[2] == "none" else json.loads(Path(a[2]).read_text())
        show(call("animate", project=a[0], note=a[1], animation=keys))
    elif cmd == "render-animation":
        out = Path(a[2] if len(a) > 2 else f"{a[1]}.gif")
        args = dict(project=a[0], note=a[1], format="mp4" if out.suffix.lower() == ".mp4" else "gif",
                    **({"view": a[3]} if len(a) > 3 else {}), **({"fps": float(a[4])} if len(a) > 4 else {}))
        r = call("render_animation", **args)
        while not r.get("url"):      # a big assembly renders apart, for minutes: its progress on one line
            print(f"\r  {r.get('state', 'rendering')} {a[1]}: {r.get('done', 0)}/{r.get('frames', '?')} frames ", end="", file=sys.stderr, flush=True)
            time.sleep(3)
            r = call("render_animation", **args)
        print(file=sys.stderr)
        get(r.pop("url"), out, "fetching the animation")
        show(r)
        print(out)
    elif cmd == "bom":
        r = call("bom", project=a[0], note=a[1])
        csv_url = r.pop("csv")
        show(r)
        if len(a) > 2:
            get(csv_url, Path(a[2]), "fetching the bill of materials")
            print(a[2])
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
