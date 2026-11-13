# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=15"]
# ///
"""Monet local, from nothing, with one line: the line the canvas shows in its Terminal panel.

    uv run https://<host>/start.py https://<host>/w/<agent key> <project> [--pair=<token>] [--mine|--theirs] [--port=N]

It fetches the server's own skill (its script, the builder pinned to the server's CAD kernel) into ~/.cache/monet,
again whenever the server runs another build; keeps the agent link on this computer (~/.config/monet/link, never in
a project's folder); and starts Monet local (scripts/local.py) for the project in ~/monet/<project>. It stays in
the foreground and says what it does; the canvas's Terminal panel shows the same, and finds it by itself (the page
made the token after --pair).
"""
import io
import json
import os
import re
import runpy
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


def fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except OSError as e:
        sys.exit(f"monet: cannot reach {urllib.parse.urlsplit(url).netloc} ({getattr(e, 'reason', e)})")


def skill(origin: str, host: str) -> Path:
    """The server's skill, unpacked: by name, under one folder, nothing the zip says about where."""
    commit = re.sub(r"[^A-Za-z0-9]", "", str(json.loads(fetch(f"{origin}/api/version")).get("commit") or "unknown"))[:40]
    home = Path(os.environ.get("MONET_CACHE") or Path.home() / ".cache" / "monet") / re.sub(r"[^A-Za-z0-9.-]", "_", host) / "skill"
    there = home / commit
    if not (there / "scripts" / "local.py").exists():
        print(f"fetching Monet's tools from {host} …", flush=True)
        coming = home / f"{commit}.coming"
        shutil.rmtree(coming, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(fetch(f"{origin}/skill.zip"))) as z:
            for item in z.infolist():
                m = re.fullmatch(r"monet/((?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+)", item.filename)
                if not m or ".." in item.filename or item.file_size > 5_000_000:
                    continue
                out = coming / m.group(1)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(item))
        if not (coming / "scripts" / "local.py").exists():
            sys.exit(f"monet: {host} runs a Monet without Monet local: it wants a newer one")
        for old in home.iterdir():
            if old != coming:
                shutil.rmtree(old, ignore_errors=True)
        coming.rename(there)
    return there


def main(argv) -> None:
    flags = [a for a in argv if a.startswith("--")]
    rest = [a for a in argv if not a.startswith("--")]
    if len(rest) != 2 or not re.fullmatch(r"https?://[^/\s]+/w/[A-Za-z0-9_-]{16,}/?", rest[0]):
        sys.exit(__doc__)
    if not shutil.which("uv"):
        sys.exit("monet: building needs uv on this computer: https://docs.astral.sh/uv/getting-started/installation/")
    link, project = rest[0].rstrip("/"), rest[1]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", project):
        sys.exit(f"monet: {project!r} is not a project's name")
    u = urllib.parse.urlsplit(link)
    tools = skill(f"{u.scheme}://{u.netloc}", u.netloc)
    kept = Path(os.environ.get("MONET_CONFIG") or Path.home() / ".config" / "monet") / "link"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(link + "\n")
    kept.chmod(0o600)
    os.environ["MONET_URL"] = link
    folder = Path(os.environ.get("MONET_HOME") or Path.home() / "monet") / project
    sys.argv = [str(tools / "scripts" / "local.py"), project, str(folder), *flags]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main(sys.argv[1:])
