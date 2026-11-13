# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=15"]
# ///
"""Monet local: the program that stays running on the person's computer while a project is worked on.

    monet.py local <project> [folder]        (folder: where the project's files are, default the one you are in)

It does two things, for one project in one folder:

1. **The canvas shows the working copy.** A Python file changed in the folder is sent to Monet, built here with
   Monet's builder and uploaded, as `monet.py push` does. A file changed on the server (the person tagged a face in
   the canvas) is written into the folder. A file changed in both since they last agreed is left alone on both sides
   and said: nothing is merged here yet.
2. **A terminal for the canvas.** A websocket on 127.0.0.1 gives the person's own page a terminal in the folder,
   running one of a short list (claude, codex, a shell). The server is not in between and never sees it.

Who may open the terminal: only a page of the Monet this computer is linked to (its Origin), and only with the
token of this computer (~/.config/monet/local.json), which `monet.py local` prints as a link to open once. It listens
on 127.0.0.1 and nowhere else. The page chooses a name from the list; it cannot send a command line.

It asks the server only when something happened here (a file changed, a key was pressed in the terminal, the page
said the person changed something): every call of an agent starts remote control's 15 minutes again, and a program
that only watches must not keep it on.
"""
import asyncio
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import struct
import sys
import termios
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")      # a Note's name, as monet/note.py has it
PORT = 8765
KEEP = 256_000          # bytes of a terminal's output kept, for a page that comes (back) to it
CONFIG = Path(os.environ.get("MONET_CONFIG") or Path.home() / ".config" / "monet")


def script():
    """scripts/monet.py beside this file, as a module: its calls, its building and its uploads."""
    spec = importlib.util.spec_from_file_location("monet_script", HERE / "monet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def say(text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {text}"
    print(line, flush=True)
    LOG.append(line)
    del LOG[:-400]
    for fn in list(LISTENERS):
        fn(line)


LOG: list = []
LISTENERS: set = set()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def whole(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"      # as the server keeps a file


# ---- the working copy ------------------------------------------------------------------------------------------
class Sync:
    """One project, one folder. `known` is each file as both sides last agreed on it (a hash), kept in
    .monet/synced.json so that stopping and starting again forgets nothing."""

    def __init__(self, ms, project: str, folder: Path, prefer: str = ""):
        self.ms, self.project, self.folder, self.prefer = ms, project, folder, prefer
        self.memo = folder / ".monet" / "synced.json"
        self.known = {}
        try:
            kept = json.loads(self.memo.read_text())
            if kept.get("project") == project and kept.get("host") == ms._host():
                self.known = kept.get("files") or {}
        except (OSError, ValueError):
            pass
        self.said: set = set()
        self.seen: dict = {}        # name: (mtime, size) as last looked at

    def once(self, text: str) -> None:
        if text not in self.said:
            self.said.add(text)
            say(text)

    def local(self) -> dict:
        out = {}
        for f in sorted(self.folder.glob("*.py")):
            if NAME_RE.match(f.stem) and f.is_file():
                try:
                    out[f.stem] = whole(f.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    self.once(f"{f.name} cannot be read as text: left alone")
        return out

    def changed(self) -> bool:
        """Did a Python file here change since the last look? By time and size: cheap enough to ask every second."""
        now = {f.stem: (f.stat().st_mtime_ns, f.stat().st_size) for f in self.folder.glob("*.py") if NAME_RE.match(f.stem) and f.is_file()}
        if now == self.seen:
            return False
        self.seen = now
        return True

    def ask(self, tool: str, **args):
        """A call of the script's, which ends the program in words when the server says no: here that is an answer."""
        try:
            return self.ms.call(tool, **args), None
        except SystemExit as e:
            return None, str(e.code)

    def step(self) -> bool:
        """Bring the two sides together once. True when it could ask the server."""
        got, why = self.ask("sources", project=self.project)
        if got is None:
            self.once(why)
            return False
        server = {name[:-3]: whole(text) for name, text in got["files"].items()}
        local = self.local()
        moved = False
        for name in sorted(set(local) | set(server)):
            mine, theirs, k = local.get(name), server.get(name), self.known.get(name)
            if mine == theirs:
                self.known[name] = sha(mine)
                continue
            if mine is None:
                if k == sha(theirs):
                    self.once(f"{name}.py is gone here and still on the server: only the person deletes a Note, in the canvas")
                    continue
                take = "theirs"
            elif theirs is None:
                take = "mine"
            else:
                i_changed, they_changed = sha(mine) != k, sha(theirs) != k
                take = "mine" if i_changed and not they_changed else "theirs" if they_changed and not i_changed else self.prefer
            if not take:
                self.once(f"{name}.py was changed here and on the server since they last agreed: left as it is on both sides. "
                          f"Start again with --mine to send this folder's, or --theirs to take the server's")
                continue
            if take == "theirs":
                (self.folder / f"{name}.py").write_text(theirs, encoding="utf-8")
                self.known[name] = sha(theirs)
                say(f"{name}.py: taken from the server" + (" (it was not here yet)" if mine is None else " (changed in the canvas)"))
            else:
                r, why = self.ask("write_note", project=self.project, note=name, source=mine)
                if r is None:
                    self.once(f"{name}.py not sent: {why}")
                    continue
                self.known[name] = sha(mine)
                say(f"{name}.py: sent" + (f" ({r['error']})" if r.get("error") else ""))
            moved = True
        self.prefer = ""        # --mine and --theirs settle what differed at the start, nothing later
        self.seen = {}
        self.changed()
        self.memo.parent.mkdir(exist_ok=True)
        self.memo.write_text(json.dumps({"project": self.project, "host": self.ms._host(), "files": self.known}, indent=1) + "\n")
        if moved or not self.built:
            self.build()
        return True

    built = False

    def build(self) -> None:
        """Whatever is not built for its source as it is, built here and uploaded."""
        try:
            answers = self.ms.build_all(self.project)
        except SystemExit as e:
            self.once(str(e.code))
            return
        self.built = True
        for name, a in answers.items():
            red = [f"{c['id']}: {c['what']} is {c['value']}, must be {c['expect']}" for c in a.get("checks") or [] if not c.get("ok")]
            say(f"{name}: " + (a["error"] if a.get("error") else "built, checks green" if a.get("green") else "built, " + ("; ".join(red) or "not green")))


# ---- the terminal ----------------------------------------------------------------------------------------------
def runs() -> dict:
    """What a terminal may run, by name. The page picks a name: this list is the whole of what it can start."""
    shell = os.environ.get("SHELL") or "/bin/sh"
    return {"claude": ["claude"], "codex": ["codex"], "shell": [shell, "-l"]}


class Session:
    """One program in a terminal of its own. It lives on when the page goes (a reload, a closed lid) and is found
    again by its name; what it wrote meanwhile is kept, up to KEEP bytes."""

    # the program is started by a fresh process that makes the terminal its own and becomes the program: never by a
    # fork of this one, which has threads (a build runs in one)
    OWN = "import fcntl, os, sys, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); os.execvp(sys.argv[1], sys.argv[1:])"

    def __init__(self, name: str, argv: list, folder: Path, env: dict, cols: int, rows: int, loop):
        import pty
        import subprocess
        self.name, self.loop, self.kept, self.clients, self.code = name, loop, bytearray(), set(), None
        self.fd, slave = pty.openpty()
        self.resize(cols, rows)
        try:
            self.proc = subprocess.Popen([sys.executable, "-c", self.OWN, *argv], stdin=slave, stdout=slave, stderr=slave, cwd=folder, env=env, close_fds=True)
        finally:
            os.close(slave)
        self.pid = self.proc.pid
        os.set_blocking(self.fd, False)
        loop.add_reader(self.fd, self.read)

    def resize(self, cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(2, min(500, rows)), max(2, min(1000, cols)), 0, 0))
        except OSError:
            pass

    def read(self) -> None:
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            return self.ended()
        self.kept += data
        del self.kept[:-KEEP]
        for q in self.clients:
            q.put_nowait(data)

    def write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def ended(self) -> None:
        if self.code is not None:
            return
        self.loop.remove_reader(self.fd)
        os.close(self.fd)
        try:
            self.code = self.proc.wait(5)
        except Exception:      # it shut its terminal and stays: it is told to go, and not waited for
            self.proc.kill()
            self.code = -1
        for q in self.clients:
            q.put_nowait(None)

    def stop(self) -> None:
        if self.code is None:
            try:
                os.killpg(self.pid, signal.SIGHUP)      # it leads a session of its own: whatever it started goes with it
            except (ProcessLookupError, PermissionError):
                pass


class Local:
    def __init__(self, ms, project: str, folder: Path, token: str, port: int, prefer: str = ""):
        self.ms, self.project, self.folder, self.token, self.port = ms, project, folder, token, port
        self.sync = Sync(ms, project, folder, prefer)
        self.sessions: dict = {}
        self.poked = asyncio.Event()
        u = urllib.parse.urlsplit(ms.URL)
        self.origin = f"{u.scheme}://{u.netloc}"

    def origins(self) -> list:
        """The pages that may open a terminal: those of the Monet this computer is linked to. A server on this very
        computer is reached as localhost or as 127.0.0.1, which a browser holds to be two origins."""
        u = urllib.parse.urlsplit(self.origin)
        if u.hostname in ("localhost", "127.0.0.1"):
            port = f":{u.port}" if u.port else ""
            return [f"{u.scheme}://localhost{port}", f"{u.scheme}://127.0.0.1{port}"]
        return [self.origin]

    def env(self) -> dict:
        return {**os.environ, "MONET_URL": self.ms.URL, "MONET_PROJECT": self.project, "TERM": "xterm-256color", "COLORTERM": "truecolor"}

    async def watch(self) -> None:
        """The working copy, looked at every second; the server asked only when something happened here."""
        self.poked.set()
        while True:
            if self.sync.changed():
                self.poked.set()
            if self.poked.is_set():
                self.poked.clear()
                await asyncio.to_thread(self.sync.step)
            await asyncio.sleep(1)

    async def serve(self, ws) -> None:
        """One page. Its first words are the token and what it wants to see; anything else and it is hung up on."""
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            ok = isinstance(hello, dict) and hmac.compare_digest(str(hello.get("token") or ""), self.token)
        except (asyncio.TimeoutError, ValueError, TypeError):
            ok = False
        if not ok:
            return await ws.close(4003, "not this computer's token")
        can = [name for name, argv in runs().items() if shutil.which(argv[0])]
        name = str(hello.get("run") or "")
        about = {"t": "hello", "project": self.project, "folder": str(self.folder).replace(str(Path.home()), "~", 1), "host": self.ms._host(),
                 "runs": can, "running": [n for n, s in self.sessions.items() if s.code is None]}
        if name == "log":
            return await self.log(ws, about)
        if name not in can:
            await ws.send(json.dumps({**about, "run": None}))
            return await ws.close(1000, "nothing asked for that this computer has")
        cols, rows = int(hello.get("cols") or 100), int(hello.get("rows") or 30)
        s = self.sessions.get(name)
        fresh = s is None or s.code is not None
        if fresh:
            s = self.sessions[name] = Session(name, runs()[name], self.folder, self.env(), cols, rows, asyncio.get_running_loop())
            say(f"terminal: {name} started in {about['folder']}")
        else:
            s.resize(cols, rows)
        await ws.send(json.dumps({**about, "run": name, "fresh": fresh}))
        if s.kept:
            await ws.send(bytes(s.kept))
        q: asyncio.Queue = asyncio.Queue()
        s.clients.add(q)

        async def out():
            while True:
                data = await q.get()
                if data is None:
                    await ws.send(json.dumps({"t": "exit", "code": s.code}))
                    return await ws.close(1000, "it ended")
                await ws.send(data)

        async def keys():
            last = 0.0
            async for m in ws:
                if isinstance(m, bytes):
                    s.write(m)
                    if time.time() - last > 3:      # the person is at it: what they did in the canvas may want bringing here
                        last = time.time()
                        self.poked.set()
                    continue
                try:
                    c = json.loads(m)
                except ValueError:
                    continue
                if c.get("t") == "resize":
                    s.resize(int(c.get("cols") or 80), int(c.get("rows") or 24))
                elif c.get("t") == "poke":
                    self.poked.set()
                elif c.get("t") == "end":
                    s.stop()

        tasks = [asyncio.create_task(out()), asyncio.create_task(keys())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            s.clients.discard(q)
            for t in tasks:
                t.cancel()

    async def log(self, ws, about: dict) -> None:
        """What this program did with the files, as it says it: read only."""
        await ws.send(json.dumps({**about, "run": "log"}))
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        tell = lambda line: loop.call_soon_threadsafe(q.put_nowait, line)      # noqa: E731  (said from the building thread too)
        for line in LOG[-200:]:
            q.put_nowait(line)
        LISTENERS.add(tell)

        async def lines():
            while True:
                await ws.send(((await q.get()).replace("\n", "\r\n") + "\r\n").encode())

        async def heard():
            async for m in ws:
                if isinstance(m, str) and '"poke"' in m:
                    self.poked.set()

        tasks = [asyncio.create_task(lines()), asyncio.create_task(heard())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            LISTENERS.discard(tell)
            for t in tasks:
                t.cancel()

    async def run(self) -> None:
        import websockets
        async with websockets.serve(self.serve, "127.0.0.1", self.port, origins=self.origins(), max_size=1_000_000):
            say(f"Monet local: {self.project} in {self.folder}, linked to {self.ms._host()}")
            say(f"the terminal of your canvas: open this once in the browser you use Monet in\n\n    {self.origin}/#local={self.port}.{self.token}\n")
            try:
                await self.watch()
            finally:
                for s in self.sessions.values():
                    s.stop()


def token() -> str:
    """This computer's own, made once: the page keeps it, so the link is opened once and not at every start."""
    f = CONFIG / "local.json"
    try:
        return json.loads(f.read_text())["token"]
    except (OSError, ValueError, KeyError):
        made = secrets.token_urlsafe(24)
        CONFIG.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"token": made}) + "\n")
        f.chmod(0o600)
        return made


def main(argv) -> None:
    flags = [a for a in argv if a.startswith("--")]
    rest = [a for a in argv if not a.startswith("--")]
    port = PORT
    for f in flags:
        if f.startswith("--port="):
            port = int(f.split("=", 1)[1])
        elif f not in ("--mine", "--theirs"):
            sys.exit(__doc__)
    if not rest:
        sys.exit(__doc__)
    ms = script()
    if not ms.URL:
        sys.exit("monet: this computer is not linked: monet.py link https://host/w/<agent key>  (the link is in your canvas, under Connect your agent)")
    folder = Path(rest[1] if len(rest) > 1 else ".").resolve()
    if not folder.is_dir():
        sys.exit(f"monet: there is no folder {folder}")
    prefer = "mine" if "--mine" in flags else "theirs" if "--theirs" in flags else ""
    try:
        asyncio.run(Local(ms, rest[0], folder, token(), port, prefer).run())
    except KeyboardInterrupt:
        pass
    except OSError as e:
        sys.exit(f"monet: cannot listen on 127.0.0.1:{port} ({e.strerror or e}): is Monet local running already? (--port=N for another)")


if __name__ == "__main__":
    main(sys.argv[1:])
