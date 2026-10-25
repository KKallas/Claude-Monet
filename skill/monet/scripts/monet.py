#!/usr/bin/env python3
"""monet.py: the Monet tools from a shell, for a harness without MCP. Standard library only.

    The agent link: link.txt beside SKILL.md, when the skill was downloaded from the canvas (Connect your agent),
    or else  export MONET_URL=https://host/w/<agent key>

    monet.py status [project]
    monet.py pull <project> [dir]            every Note, with the saved .glb and .fingerprint.json, into dir (default .)
    monet.py push <project> <file.py>...     send Notes; prints each report, exit 1 if any is red
    monet.py look <project> <note> [out.png] [views]
    monet.py pose <project> <note> "j1=30, j2=-10" [out.png]   an assembly moved: what it hits, and its picture
    monet.py save <project> "message"        then: git add -A && git commit
    monet.py export <project> <note> <3mf|stl|step|glb> [out]
    monet.py tool <name> ['{"json": "arguments"}']    any tool, raw
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
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
        red = False
        for f in a[1:]:
            report = call("write_note", project=a[0], note=Path(f).stem, source=Path(f).read_text())
            show(report)
            red = red or not report.get("green")
        sys.exit(1 if red else 0)
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
