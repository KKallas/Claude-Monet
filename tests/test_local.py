"""Monet local (skill/monet/scripts/local.py): the working copy brought together with the server's files, and the
terminal it gives the canvas: to a page of the linked Monet with this computer's token, and to nobody else."""
import asyncio
import importlib.util
import json

import pytest
import websockets

from monet.app import ROOT

spec = importlib.util.spec_from_file_location("monet_local", ROOT / "skill/monet/scripts/local.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

NOTE = '"""A block."""\nPARAMS = dict(a=1)\n\ndef build(p=PARAMS):\n    return None\n'


class Server:
    """The script's side of a server, as Monet local uses it: the files it has, what was sent, what was built."""
    URL = "https://monet.example/w/KEY"

    def __init__(self, files=None, off=False):
        self.files, self.sent, self.builds, self.off = dict(files or {}), [], 0, off

    def _host(self):
        return "monet.example"

    def call(self, tool, **a):
        if self.off:
            raise SystemExit("monet: remote control is off")
        if tool == "sources":
            return {"files": {f"{n}.py": t for n, t in self.files.items()}}
        if tool == "write_note":
            self.files[a["note"]] = a["source"]
            self.sent.append(a["note"])
            return {"note": a["note"]}
        raise AssertionError(tool)

    def build_all(self, project):
        self.builds += 1
        return {}


def sync(tmp_path, server, prefer=""):
    return local.Sync(server, "p", tmp_path, prefer)


def test_a_note_written_here_is_sent_and_one_made_there_is_taken(tmp_path):
    server = Server({"theirs": NOTE})
    (tmp_path / "mine.py").write_text(NOTE)
    (tmp_path / "Not_A_Note.py").write_text("x = 1\n")
    s = sync(tmp_path, server)
    assert s.step()
    assert server.sent == ["mine"] and (tmp_path / "theirs.py").read_text() == NOTE
    assert server.builds == 1
    assert s.step() and server.sent == ["mine"] and server.builds == 1      # agreed: nothing more to do


def test_the_side_that_changed_since_they_agreed_wins_and_two_are_left_alone(tmp_path):
    server = Server({"a": NOTE, "b": NOTE, "c": NOTE})
    s = sync(tmp_path, server)
    s.step()
    (tmp_path / "a.py").write_text(NOTE + "# mine\n")                 # changed here
    server.files["b"] = NOTE + "# tagged in the canvas\n"             # changed there
    (tmp_path / "c.py").write_text(NOTE + "# mine\n")                 # changed on both sides
    server.files["c"] = NOTE + "# theirs\n"
    s.step()
    assert server.files["a"].endswith("# mine\n")
    assert (tmp_path / "b.py").read_text().endswith("# tagged in the canvas\n")
    assert (tmp_path / "c.py").read_text().endswith("# mine\n") and server.files["c"].endswith("# theirs\n")
    assert any("c.py was changed here and on the server" in line for line in local.LOG)
    # what they agreed on is remembered over a restart; --theirs settles what differs
    again = sync(tmp_path, server, "theirs")
    again.step()
    assert (tmp_path / "c.py").read_text().endswith("# theirs\n")


def test_a_note_deleted_here_is_not_taken_back_and_not_deleted_there(tmp_path):
    server = Server({"a": NOTE})
    s = sync(tmp_path, server)
    s.step()
    (tmp_path / "a.py").unlink()
    s.step()
    assert not (tmp_path / "a.py").exists() and "a" in server.files


def test_a_server_that_says_no_is_said_once_and_nothing_is_lost(tmp_path):
    server = Server(off=True)
    (tmp_path / "mine.py").write_text(NOTE)
    s = sync(tmp_path, server)
    assert not s.step() and not s.step()
    assert sum("remote control is off" in line for line in local.LOG) == 1
    server.off = False
    assert s.step() and server.sent == ["mine"]


@pytest.fixture
async def running(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "runs", lambda: {"shell": ["/bin/sh"], "codex": ["no-such-program-here"]})
    it = local.Local(Server(), "p", tmp_path, "the-token-of-this-computer", 0)
    async with websockets.serve(it.serve, "127.0.0.1", 0, origins=it.origins()) as server:
        yield it, f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        for s in it.sessions.values():
            s.stop()


async def test_only_a_page_of_the_linked_monet_with_this_computers_token(running):
    it, url = running
    for origin in ("https://evil.example", "http://monet.example", None):
        with pytest.raises(websockets.InvalidStatus):
            async with websockets.connect(url, origin=origin):
                pass
    async with websockets.connect(url, origin="https://monet.example") as ws:
        await ws.send(json.dumps({"token": "guessed", "run": "shell"}))
        with pytest.raises(websockets.ConnectionClosed) as e:
            await ws.recv()
        assert e.value.rcvd.code == 4003
    assert not it.sessions


async def test_the_page_picks_a_name_from_the_list_never_a_command(running):
    it, url = running
    for name in ("rm -rf ~", "codex", "/bin/sh", ""):      # not on the list; on it but not installed; a path; nothing
        async with websockets.connect(url, origin="https://monet.example") as ws:
            await ws.send(json.dumps({"token": "the-token-of-this-computer", "run": name}))
            hello = json.loads(await ws.recv())
            assert hello["run"] is None and hello["runs"] == ["shell"]
    assert not it.sessions


async def read_until(ws, word: bytes, seconds: float = 10) -> bytes:
    got = b""
    async with asyncio.timeout(seconds):
        while word not in got:
            m = await ws.recv()
            if isinstance(m, bytes):
                got += m
    return got


async def test_a_terminal_in_the_folder_that_lives_on_when_the_page_goes(running, tmp_path):
    it, url = running
    hello = {"token": "the-token-of-this-computer", "run": "shell", "cols": 80, "rows": 24}
    async with websockets.connect(url, origin="https://monet.example") as ws:
        await ws.send(json.dumps(hello))
        first = json.loads(await ws.recv())
        assert first["run"] == "shell" and first["fresh"] and first["project"] == "p"
        await ws.send(b"echo $MONET_PROJECT-$((6*7)); basename \"$PWD\"; echo $MONET_URL\n")
        got = await read_until(ws, tmp_path.name.encode())
        assert b"p-42" in got and b"https://monet.example/w/KEY" in await read_until(ws, b"KEY") + got
    # the page went (a reload): the program runs on, and a page that comes back is shown what was written
    async with websockets.connect(url, origin="https://monet.example") as ws:
        await ws.send(json.dumps(hello))
        again = json.loads(await ws.recv())
        assert not again["fresh"] and again["running"] == ["shell"]
        assert b"p-42" in await read_until(ws, b"p-42")
        await ws.send(b"exit 3\n")
        async with asyncio.timeout(10):
            while True:
                m = await ws.recv()
                if isinstance(m, str) and json.loads(m).get("t") == "exit":
                    assert json.loads(m)["code"] == 3
                    break


def test_the_tokens_it_answers_its_own_and_those_a_canvas_made(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "CONFIG", tmp_path / "config")
    own = local.tokens()
    assert len(own) == 1 and local.tokens() == own                      # made once, kept
    assert local.tokens("a-token-the-canvas-made-0001") == [own[0], "a-token-the-canvas-made-0001"]
    for i in range(12):
        local.tokens(f"a-token-the-canvas-made-1{i:03d}")
    kept = local.tokens()
    assert kept[0] == own[0] and len(kept) == 9 and kept[-1].endswith("1011")      # the newest few
    assert oct((tmp_path / "config" / "local.json").stat().st_mode & 0o777) == "0o600"


async def test_a_page_with_a_token_the_canvas_made_gets_in(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "runs", lambda: {"shell": ["/bin/sh"]})
    it = local.Local(Server(), "p", tmp_path, ["this-computers-own", "the-one-in-the-line"], 0)
    async with websockets.serve(it.serve, "127.0.0.1", 0, origins=it.origins()) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        for token in ("this-computers-own", "the-one-in-the-line"):
            async with websockets.connect(url, origin="https://monet.example") as ws:
                await ws.send(json.dumps({"token": token, "run": "log"}))
                assert json.loads(await ws.recv())["run"] == "log"


async def test_a_port_another_program_has_is_passed_over(tmp_path, monkeypatch):
    import socket
    with socket.socket() as taken, socket.socket() as free:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        free.bind(("127.0.0.1", 0))
        ports = (taken.getsockname()[1], free.getsockname()[1])
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", ports[0]))
        taken.listen()
        monkeypatch.setattr(local, "PORTS", ports)
        it = local.Local(Server(off=True), "p", tmp_path, "t", 0, quiet=True)
        task = asyncio.create_task(it.run())
        async with asyncio.timeout(5):
            while it.port != ports[1]:
                await asyncio.sleep(0.05)
        task.cancel()
