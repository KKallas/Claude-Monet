# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=15"]
# ///
"""Monet local: the program that stays running on the person's computer while a project is worked on.

    monet.py local <project> [folder] [--for=2h]   (folder: where the project's files are, default the one you are in)

or, with nothing set up, the one line the canvas gives (its Terminal panel): uv run https://<host>/start.py <agent
link> <project>, which fetches this and starts it in ~/monet/<project> (scripts/start.py).

It does four things, for one project in one folder:

0. **The folder is the whole project.** Beside the Notes it holds the brief (PROJECT.md), each Note's checks
   (<note>.checks.json) and the settings (monet.json: printer, material, looks, animations), written here as the
   person changes them in the canvas. So a git repository of the folder can be cloned on another computer and worked
   on there: where the server has no such project yet it is made, and the folder's checks are added to it (added
   only: a check is never changed or removed from here; that is the person's, in the canvas).
1. **The canvas shows the working copy.** A Python file changed in the folder is sent to Monet, built here with
   Monet's builder and uploaded, as `monet.py push` does. A file changed on the server (the person tagged a face in
   the canvas) is written into the folder. A file changed in both since they last agreed is left alone on both sides
   and said: nothing is merged here yet.
2. **A terminal for the canvas.** A websocket on 127.0.0.1 gives the person's own page a terminal in the folder,
   running one of a short list (claude, codex, a shell). The server is not in between and never sees it.

3. **The brief, and how long.** PROJECT.md (the project in words: what it is, where its repository and issues are,
   what is done, what comes next) is kept in step with the server like a Note. With `--for=90m` or `--for=2h` the
   sitting has an end: the agent in the terminal is told when (MONET_UNTIL), and this says so ten minutes before, so
   that the brief is brought up to date for whoever works on it next. Nothing is stopped: it is said.

Who may open the terminal: only a page of the Monet this computer is linked to (its Origin), and only with the
token of this computer (~/.config/monet/local.json), which `monet.py local` prints as a link to open once. It listens
on 127.0.0.1 and nowhere else. The page chooses a name from the list; it cannot send a command line.

It looks at the folder every second and asks the server every few (and at once when a file changed here or the page
says the person changed something), so what is done on either side shows on the other within seconds.
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
PORTS = (47821, 47822, 47823, 47824)      # where it listens: the first that is free; the canvas tries the same ones (terminal.js)
EVERY = 4               # seconds between two looks at the server, when nothing happened here
BRIEF = "PROJECT.md"    # the project in words, for whoever works on it next: kept in step with the server, as the Notes are
KEPT_RE = re.compile(r"^(?:[a-z][a-z0-9_]{0,47}\.checks\.json|monet\.json)$")      # what a project keeps beside those: checks, settings
KEEP = 256_000          # bytes of a terminal's output kept, for a page that comes (back) to it
CONFIG = Path(os.environ.get("MONET_CONFIG") or Path.home() / ".config" / "monet")


def script():
    """scripts/monet.py beside this file, as a module: its calls, its building and its uploads."""
    spec = importlib.util.spec_from_file_location("monet_script", HERE / "monet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIM, GREEN, AMBER, RED, BOLD, OFF = "\x1b[2m", "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[1m", "\x1b[0m"
TONES = ((RED, ("does not build", "died", "refused", "cannot", "not sent", "RED")),
         (AMBER, ("left as it is", "must be", "not green", "waiting", "gone here", "trying again", "this sitting", "left here", "left there")),
         (GREEN, ("checks green", "built ", "uploaded", "sent", "taken from", "started", "linked to")))


def say(text: str) -> None:
    """One line of what is going on: on this terminal, and in the canvas's panel (its Activity tab), the same words."""
    tone = next((c for c, words in TONES if any(w in text for w in words)), "")
    stamp = time.strftime("%H:%M:%S")
    line = f"{DIM}{stamp}{OFF}  {tone}{text}{OFF if tone else ''}"
    print(line if sys.stdout.isatty() else re.sub(r"\x1b\[[0-9;]*m", "", f"{stamp}  {text}"), flush=True)
    LOG.append(line)
    del LOG[:-400]
    for fn in list(LISTENERS):
        fn(line)


class Said:
    """What the script's building prints for a person (its progress, on stderr), said here line by line instead."""

    def __init__(self):
        self.rest = ""

    def write(self, text: str) -> int:
        *lines, self.rest = (self.rest + text).split("\n")
        for line in lines:
            if line.strip():
                say(line.strip())
        return len(text)

    def flush(self) -> None:
        pass


LOG: list = []
LISTENERS: set = set()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def whole(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"      # as the server keeps a file


def meaning(text: str) -> str:
    """What a kept file says, whoever wrote it down and however: its checks in the order of their names and without
    who added them, its numbers as numbers (1 is 1.0). Two files that mean the same are the same here."""
    def canon(x):
        if isinstance(x, bool) or x is None or isinstance(x, str):
            return x
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, dict):
            return {k: canon(v) for k, v in sorted(x.items())}
        return [canon(v) for v in x]
    try:
        doc = json.loads(text)
        if isinstance(doc, dict) and isinstance(doc.get("checks"), list):
            doc = {"checks": sorted(({k: v for k, v in c.items() if k != "by"} for c in doc["checks"] if isinstance(c, dict)), key=lambda c: str(c.get("id")))}
        return json.dumps(canon(doc), sort_keys=True)
    except (TypeError, ValueError):
        return text


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
        self.sent: dict = {}        # a kept file that was offered to the server as it stands: (what it means here, there)

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
        """Did a Python file here (or the brief) change since the last look? By time and size: cheap enough to ask every second."""
        now = {f.stem: (f.stat().st_mtime_ns, f.stat().st_size) for f in self.folder.glob("*.py") if NAME_RE.match(f.stem) and f.is_file()}
        for f in [self.folder / BRIEF, *self.folder.glob("*.json")]:
            if f.is_file() and (f.name == BRIEF or KEPT_RE.match(f.name)):
                now[f.name] = (f.stat().st_mtime_ns, f.stat().st_size)
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
        if got is None and "no project" in why and self.local():
            # a folder that is a project (a repository just cloned) and none by that name on the server yet: made
            made, why = self.ask("new_project", name=self.project)
            if made is not None:
                say(f"{self.project}: there was no such project on the server yet; made, from this folder")
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
        self.brief()
        self.keeping()
        self.prefer = ""        # --mine and --theirs settle what differed at the start, nothing later
        self.seen = {}
        self.changed()
        self.memo.parent.mkdir(exist_ok=True)
        self.memo.write_text(json.dumps({"project": self.project, "host": self.ms._host(), "files": self.known}, indent=1) + "\n")
        if moved or not self.built:
            self.build()
        return True

    def brief(self) -> None:
        """PROJECT.md, the project in words for whoever works on it next: kept the same on both sides, as the Notes
        are. It is no Note: nothing is built from it."""
        got, why = self.ask("brief", project=self.project)
        if got is None:
            return      # a server from before there were briefs: nothing to keep
        f = self.folder / BRIEF
        try:
            mine = whole(f.read_text(encoding="utf-8")) if f.is_file() else None
        except (OSError, UnicodeDecodeError):
            self.once(f"{BRIEF} cannot be read as text: left alone")
            return
        mine = mine if mine and mine.strip() else None
        theirs, k = got.get("text") or None, self.known.get(BRIEF)
        if mine == theirs:
            if mine is None:
                self.once(f"no {BRIEF} yet (the project in words, for whoever works on it next): the first to work here writes it")
            else:
                self.known[BRIEF] = sha(mine)
            return
        if mine is None:
            if k == sha(theirs):
                self.once(f"{BRIEF} is gone here and still on the server: left there")
                return
            take = "theirs"
        elif theirs is None:
            if k == sha(mine):
                self.once(f"{BRIEF} was emptied in the canvas and is still here: left here")
                return
            take = "mine"
        else:
            i_changed, they_changed = sha(mine) != k, sha(theirs) != k
            take = "mine" if i_changed and not they_changed else "theirs" if they_changed and not i_changed else self.prefer
        if not take:
            self.once(f"{BRIEF} was changed here and on the server since they last agreed: left as it is on both sides. "
                      f"Start again with --mine to send this folder's, or --theirs to take the server's")
        elif take == "theirs":
            f.write_text(theirs, encoding="utf-8")
            self.known[BRIEF] = sha(theirs)
            say(f"{BRIEF}: taken from the server" + (" (it was not here yet)" if mine is None else " (changed in the canvas)"))
        else:
            r, why = self.ask("write_brief", project=self.project, text=mine)
            if r is None:
                self.once(f"{BRIEF} not sent: {why}")
                return
            self.known[BRIEF] = sha(mine)
            say(f"{BRIEF}: sent")

    def keeping(self) -> None:
        """What the project keeps beside its Notes (each Note's checks, and monet.json: printer, material, looks,
        animations), in the folder too: so the folder is the whole project, and a git repository of it can be worked
        on anywhere. What the person changes in the canvas is written here. What comes with the folder (a clone, a
        pull) is brought in as far as an agent may: a check the server lacks is added, never one changed or removed."""
        got, why = self.ask("kept", project=self.project)
        if got is None:
            return      # a server from before: nothing to keep
        server, local = got["files"], {}
        for f in self.folder.glob("*.json"):
            if f.is_file() and KEPT_RE.match(f.name):
                try:
                    local[f.name] = f.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    self.once(f"{f.name} cannot be read as text: left alone")
        send = {}
        for name in sorted(set(server) | set(local)):
            mine, theirs, k = local.get(name), server.get(name), self.known.get(name)
            a, b = (meaning(mine) if mine is not None else None), (meaning(theirs) if theirs is not None else None)
            if a == b:
                self.known[name] = sha(a)
                continue
            if mine is None:
                take = "theirs"
            elif theirs is None:
                take = "mine"
            else:
                i_changed, they_changed = sha(a) != k, sha(b) != k
                take = "mine" if i_changed and not they_changed else "theirs" if they_changed and not i_changed else self.prefer
            if not take:
                self.once(f"{name} was changed here and on the server since they last agreed: left as it is on both sides. "
                          f"Start again with --mine to bring this folder's in, or --theirs to take the server's")
            elif take == "theirs":
                (self.folder / name).write_text(theirs, encoding="utf-8")
                self.known[name] = sha(b)
                say(f"{name}: taken from the server" + (" (it was not here yet)" if mine is None else " (changed in the canvas)"))
            elif self.sent.get(name) != (a, b):      # asked once for what stands: not again every few seconds
                send[name] = mine
                self.sent[name] = (a, b)
        if not send:
            return
        r, why = self.ask("keep", project=self.project, files=send)
        if r is None:
            self.once(f"checks and settings not brought in: {why}")
            for name in send:
                self.sent.pop(name, None)      # not heard: asked again at the next look
            return
        for note, ids in r.get("added", {}).items():
            say(f"{note}: {len(ids)} check{'' if len(ids) == 1 else 's'} of the folder's added on the server ({', '.join(ids[:6])}{'…' if len(ids) > 6 else ''})")
        for what in r.get("set", []):
            say(f"{what}: set on the server as the folder has it")
        for name, reasons in r.get("left", {}).items():
            for reason in reasons:
                self.once(f"{name}: {reason}")
        for name, text in send.items():
            if name not in r.get("left", {}):
                self.known[name] = sha(meaning(text))

    built = False

    def build(self) -> None:
        """Whatever is not built for its source as it is, built here and uploaded."""
        import contextlib
        try:
            with contextlib.redirect_stderr(Said()):
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
    def __init__(self, ms, project: str, folder: Path, token, port: int, prefer: str = "", quiet: bool = False, until: float = 0):
        self.ms, self.project, self.folder, self.port, self.quiet = ms, project, folder, port, quiet
        self.until, self.warned = until, set()      # when this sitting ends (--for), and what was said of it already
        self.tokens = [token] if isinstance(token, str) else list(token)
        self.token = self.tokens[0]
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
        """What a program in the terminal is told: where Monet is, which project, and when the sitting ends."""
        ends = {"MONET_UNTIL": time.strftime("%Y-%m-%dT%H:%M", time.localtime(self.until))} if self.until else {}
        return {**os.environ, "MONET_URL": self.ms.URL, "MONET_PROJECT": self.project, "TERM": "xterm-256color", "COLORTERM": "truecolor", **ends}

    def clock(self) -> None:
        """A sitting with an end (--for): said ten minutes before it and when it is over. Nothing is stopped."""
        left = self.until - time.time() if self.until else None
        if left is None:
            return
        if left <= 0 and "over" not in self.warned:
            self.warned.add("over")
            say(f"the time of this sitting is over: {BRIEF} should say now what was done and what comes next")
        elif 0 < left <= 600 and "soon" not in self.warned:
            self.warned.add("soon")
            say(f"{max(1, round(left / 60))} minutes of this sitting are left: time to bring {BRIEF} up to date (State, Next, the Log)")

    async def watch(self) -> None:
        """The working copy, looked at every second; the server every EVERY seconds, and at once when something
        happened here (a file changed, the page poked)."""
        self.poked.set()
        asked = 0.0
        while True:
            self.clock()
            if self.sync.changed() or time.time() - asked >= EVERY:
                self.poked.set()
            if self.poked.is_set():
                self.poked.clear()
                asked = time.time()
                await asyncio.to_thread(self.sync.step)
            await asyncio.sleep(1)

    async def serve(self, ws) -> None:
        """One page. Its first words are the token and what it wants to see; anything else and it is hung up on."""
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            given = str(hello.get("token") or "") if isinstance(hello, dict) else ""
            ok = any(hmac.compare_digest(given, t) for t in self.tokens)
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
            async for m in ws:
                if isinstance(m, bytes):
                    s.write(m)
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
        server = None
        for port in ([self.port] if self.port else PORTS):      # another program may have one of them: the next, then
            try:
                server = await websockets.serve(self.serve, "127.0.0.1", port, origins=self.origins(), max_size=1_000_000)
                self.port = port
                break
            except OSError as e:
                busy = e
        if server is None:
            raise busy
        async with server:
            home = str(self.folder).replace(str(Path.home()), "~", 1)
            say(f"{BOLD}Monet local{OFF}: {self.project} in {home}, linked to {self.ms._host()}")
            if self.quiet:      # started by the canvas's one line: the page knows the token already
                say("the Terminal panel of your canvas finds this by itself. Leave this running; Ctrl+C ends it")
            else:
                say(f"the terminal of your canvas: open this once in the browser you use Monet in\n\n    {self.origin}/#local={self.port}.{self.token}\n")
            if self.until:
                say(f"this sitting ends at {time.strftime('%H:%M', time.localtime(self.until))}: the agent is told (MONET_UNTIL) and leaves {BRIEF} up to date before then")
            try:
                await self.watch()
            finally:
                for s in self.sessions.values():
                    s.stop()


def tokens(more: str = "") -> list:
    """Whom this computer's terminal answers: its own token, made once, and those a canvas made for the line it gave
    the person to start this with (--pair; the newest few are kept, so each browser of theirs keeps working)."""
    f = CONFIG / "local.json"
    try:
        kept = json.loads(f.read_text())
    except (OSError, ValueError):
        kept = {}
    own = kept.get("token") or secrets.token_urlsafe(24)
    paired = [t for t in kept.get("paired") or [] if isinstance(t, str) and t != more]
    if more:
        paired.append(more)
    now = {"token": own, "paired": paired[-8:]}
    if now != kept:
        CONFIG.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(now) + "\n")
        f.chmod(0o600)
    return [own, *now["paired"]]


def main(argv) -> None:
    flags = [a for a in argv if a.startswith("--")]
    rest = [a for a in argv if not a.startswith("--")]
    port, pair, until = 0, "", 0.0
    for f in flags:
        if f.startswith("--port="):
            port = int(f.split("=", 1)[1])
        elif m := re.fullmatch(r"--for=(\d{1,4})(m|h)", f):      # how long this sitting is: --for=90m, --for=2h
            until = time.time() + int(m.group(1)) * (3600 if m.group(2) == "h" else 60)
        elif re.fullmatch(r"--pair=[A-Za-z0-9_-]{24,64}", f):
            pair = f.split("=", 1)[1]
        elif f not in ("--mine", "--theirs"):
            sys.exit(__doc__)
    if not rest:
        sys.exit(__doc__)
    ms = script()
    if not ms.URL:
        sys.exit("monet: this computer is not linked: monet.py link https://host/w/<agent key>  (the link is in the one line your canvas shows under Terminal)")
    folder = Path(rest[1] if len(rest) > 1 else ".").expanduser().resolve()
    if len(rest) > 1:
        folder.mkdir(parents=True, exist_ok=True)      # a folder named for the project is made when it is not there
    if not folder.is_dir():
        sys.exit(f"monet: there is no folder {folder}")
    prefer = "mine" if "--mine" in flags else "theirs" if "--theirs" in flags else ""
    try:
        asyncio.run(Local(ms, rest[0], folder, tokens(pair), port, prefer, quiet=bool(pair), until=until).run())
    except KeyboardInterrupt:
        pass
    except OSError as e:
        sys.exit(f"monet: cannot listen on 127.0.0.1 ({e.strerror or e}): is Monet local running already, four times over? "
                 f"(ports {PORTS[0]} to {PORTS[-1]}; --port=N for another)")


if __name__ == "__main__":
    main(sys.argv[1:])
