#!/usr/bin/env python3
"""monet.py: the Monet tools from a shell, for a harness without MCP. Standard library only.

    export MONET_URL=https://host/w/<agent key>      (the agent link from the canvas: Connect your agent)

    monet.py status [project]
    monet.py pull <project> [dir]            every Note, with the saved .glb and .fingerprint.json, into dir (default .)
    monet.py push <project> <file.py>...     send Notes; prints each report, exit 1 if any is red
    monet.py look <project> <note> [out.png] [views]
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

URL = os.environ.get("MONET_URL", "").rstrip("/")


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
        sys.exit("monet: set MONET_URL to the agent link from your canvas (https://host/w/<agent key>)")
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
