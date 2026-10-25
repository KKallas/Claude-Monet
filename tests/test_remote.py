"""Remote control (monet/remote.py): the agent link opens only while the person has it on, it ends by itself, and while
it is on the agent sees and drives the canvas they have open. A canvas here is a websocket answered by a thread."""
import base64
import contextlib
import json
import threading
import time

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from monet.app import create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def login(c, card, password="correct horse"):
    return c.post("/api/login", json={"card": card, "password": password})


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp("remote")
    return create_app(root / "storage", root / "data", max_users=6)


@pytest.fixture(scope="module")
def live(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(app, live):
    c = TestClient(app)
    assert login(c, app.state.admin["card"]).status_code == 200
    return c


def person(app, admin, username):
    made = admin.post("/api/users", json={"username": username, "name": username.title()}).json()["user"]
    c = TestClient(app)
    assert login(c, made["card"]).status_code == 200
    return c, c.get(f"/w/{username}/api/state").json()["agent"].split("testserver", 1)[1]


@pytest.fixture(scope="module")
def mari(app, admin):
    return person(app, admin, "mari")


def owner(app, username):
    return next(u for u in app.state.store.users.values() if u["username"] == username)


@contextlib.contextmanager
def canvas(browser, username, answer, shows=None):
    """An open canvas of `username`: it says what it shows, and a thread answers what is asked as answer(ask) does."""
    asked = []
    with browser.websocket_connect(f"/w/{username}/api/remote/tab") as ws:
        ws.send_json({"t": "state", "project": "starter", "note": "rod_foot", "room": "part", "hidden": False, **(shows or {})})

        def run():
            with contextlib.suppress(Exception):
                while True:
                    m = ws.receive_json()
                    if m.get("t") == "ask":
                        asked.append(m)
                        ok, value = answer(m)
                        ws.send_json({"t": "result", "id": m["id"], "ok": ok, "json": json.dumps(value)})
        threading.Thread(target=run, daemon=True).start()
        yield ws, asked


def until(fn, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


def rpc(live, link, method, params=None):
    return live.post(f"{link}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                     headers={"accept": "application/json, text/event-stream"})


def test_the_link_opens_nothing_until_the_person_switches_it_on(app, live, mari):
    c, link = mari
    assert c.get("/w/mari/api/state").json()["remote"]["on"] is False
    with contextlib.nullcontext(TestClient(app)) as nobody:      # (not entered: the server is started once, by `live`)
        off = nobody.get(f"{link}/agent/status").json()
        assert off["status"] == 404 and "remote control is off" in off["error"]
        assert nobody.post(f"{link}/agent/status", json={}).status_code == 404
        assert nobody.get(f"{link}/file/p/starter/n/rod_foot/render.png").status_code == 200       # a GET says why inside a 200
        assert "error" in nobody.get(f"{link}/file/p/starter/n/rod_foot/render.png").json()
    # MCP stays connected while it is off: it lists its tools, and every call says, in words, that it is off
    assert rpc(live, link, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).status_code == 200
    tools = {t["name"] for t in rpc(live, link, "tools/list").json()["result"]["tools"]}
    assert {"screen", "goto", "view", "status"} <= tools and "page" not in tools      # no code of the agent's runs in the canvas
    r = rpc(live, link, "tools/call", {"name": "status", "arguments": {}}).json()["result"]
    assert r["isError"] and "remote control is off" in r["content"][0]["text"]
    assert rpc(live, "/w/" + "A" * 32, "tools/list").status_code == 404        # a key that is nobody's is gone, as before

    view = c.put("/w/mari/api/remote", json={"on": True}).json()
    assert view["on"] and 14 * 60_000 < view["left"] <= 15 * 60_000 and view["tabs"] == 0
    s = c.get(f"{link}/agent/status").json()
    assert s["projects"] == ["mg400_rakis", "starter"] and s["remote"]["minutes_left"] == 15 and s["pages"] == []
    assert json.loads(rpc(live, link, "tools/call", {"name": "status", "arguments": {}}).json()["result"]["content"][0]["text"])["pages"] == []
    # no canvas open: the tools that ask one say so, the others work
    assert "no canvas of Mari is open" in c.get(f"{link}/agent/screen").json()["error"]
    assert c.get(f"{link}/agent/view").json()["status"] == 503
    assert c.put("/w/mari/api/remote", json={"on": False}).json()["on"] is False
    assert c.get(f"{link}/agent/status").json()["status"] == 404
    assert c.put("/w/mari/api/remote", json={"on": True}).json()["on"]        # the same link works again
    assert c.get(f"{link}/agent/status").json()["projects"]


def test_the_agent_sees_the_open_canvas_and_takes_it_somewhere(app, live, admin, mari):
    c, link = mari
    c.put("/w/mari/api/remote", json={"on": True})

    def answer(m):
        if m["what"] == "screen":
            return True, {"project": "starter", "note": "rod_foot", "room": "part", "panel": "Part 45 × 22.4 × 22.4 mm"}
        if m["what"] == "goto":
            if m["args"]["note"] == "gone":
                return False, "Error: there is no Note \"gone\" in starter"
            return True, {"project": m["args"]["project"] or "starter", "note": m["args"]["note"] or "rod_foot", "room": m["args"]["room"] or "part"}
        if m["what"] == "view":
            return True, {"project": "starter", "note": "rod_foot", "room": "part", "png": "data:image/png;base64," + base64.b64encode(PNG).decode()}
        return False, f'the canvas does not know "{m["what"]}"'

    with canvas(c, "mari", answer) as (_ws, asked):
        assert until(lambda: c.get(f"{link}/agent/status").json()["pages"])
        assert c.get(f"{link}/agent/status").json()["pages"] == [{"project": "starter", "note": "rod_foot", "room": "part", "on_screen": True}]
        assert c.get("/w/mari/api/remote").json()["tabs"] == 1
        assert c.get(f"{link}/agent/screen").json()["panel"].startswith("Part 45")
        assert c.get(f"{link}/agent/goto", params={"project": "mg400_rakis", "note": "rakis", "room": "assembly"}).json()["note"] == "rakis"
        assert "room is sketch" in c.get(f"{link}/agent/goto", params={"room": "kitchen"}).json()["error"]       # not asked at all
        assert "no project 'nope'" in c.get(f"{link}/agent/goto", params={"project": "nope"}).json()["error"]
        refused = c.get(f"{link}/agent/goto", params={"note": "gone"}).json()
        assert refused["status"] == 422 and "no Note" in refused["error"]
        r = rpc(live, link, "tools/call", {"name": "goto", "arguments": {"room": "motion"}}).json()["result"]
        assert not r["isError"] and json.loads(r["content"][0]["text"])["room"] == "motion"
        # there is no tool that runs code in the page, by any door
        assert "no tool 'page'" in c.get(f"{link}/agent/page", params={"code": "monet.S.note"}).json()["error"]
        assert rpc(live, link, "tools/call", {"name": "page", "arguments": {"code": "1"}}).json()["result"]["isError"]
        # a picture of the canvas as it is on the screen: its address by HTTP, the picture itself by MCP
        seen = c.get(f"{link}/agent/view").json()
        assert seen["bytes"] == len(PNG) and "png" not in seen
        assert c.get(seen["image"].split("testserver", 1)[1]).content == PNG
        r = rpc(live, link, "tools/call", {"name": "view", "arguments": {}}).json()["result"]
        assert [x["type"] for x in r["content"]] == ["text", "image"]
        assert [a["what"] for a in asked] == ["screen", "goto", "goto", "goto", "view", "view"]
    # the person sees where it took the page, and the audit log keeps it
    recent = [r["what"] for r in c.get("/w/mari/api/remote").json()["recent"]]
    assert "goto mg400_rakis/rakis (assembly)" in recent and "goto here (motion)" in recent and "goto gone" in recent
    assert not any(w.startswith(("screen", "view", "status")) for w in recent)      # looking is not written down
    log = admin.get("/api/users").json()["log"]
    assert any(e["type"] == "agent" and e["tool"] == "goto" and e.get("project") is None and e.get("note") is None for e in log)      # by MCP too
    assert until(lambda: c.get(f"{link}/agent/status").json()["pages"] == [])      # the tab closed


def test_it_ends_by_itself_and_hangs_up_on_the_page(app, admin):
    c, link = person(app, admin, "toomas")
    c.put("/w/toomas/api/remote", json={"on": True})
    u = owner(app, "toomas")
    # every call of the agent starts the 15 minutes again; so does the person doing something in the canvas
    u["agent"]["until"] = time.time() + 60
    c.get(f"{link}/agent/status")
    assert u["agent"]["until"] > time.time() + 14 * 60
    with canvas(c, "toomas", lambda m: (True, None)) as (ws, _asked):
        u["agent"]["until"] = time.time() + 60
        ws.send_json({"t": "alive"})
        assert until(lambda: u["agent"]["until"] > time.time() + 14 * 60)
        u["agent"]["until"] = time.time() + 60
        ws.send_json({"t": "state", "project": "starter", "note": "rod_foot", "room": "part", "hidden": False})     # a heartbeat is not that
        time.sleep(0.1)
        assert u["agent"]["until"] < time.time() + 61
    # 15 minutes of nothing: off, and it says why
    u["agent"]["until"] = time.time() - 1
    assert "remote control is off" in c.get(f"{link}/agent/status").json()["error"]
    view = c.get("/w/toomas/api/remote").json()
    assert view["on"] is False and view["off"]["why"] == "idle" and view["recent"] == []
    # switched off: the page is hung up on
    c.put("/w/toomas/api/remote", json={"on": True})
    with c.websocket_connect("/w/toomas/api/remote/tab") as ws:
        ws.send_json({"t": "state", "project": "starter"})
        c.put("/w/toomas/api/remote", json={"on": False})
        with pytest.raises(WebSocketDisconnect) as gone:
            while True:
                ws.receive_json()
        assert gone.value.code == 4001
    # a new password ends it, and so does logging out
    c.put("/w/toomas/api/remote", json={"on": True})
    assert c.put("/api/me/password", json={"current": "correct horse", "password": "another good one"}).status_code == 200
    assert c.get(f"{link}/agent/status").json()["status"] == 404 and c.get("/w/toomas/api/remote").json()["off"]["why"] == "login"
    c.put("/w/toomas/api/remote", json={"on": True})
    assert c.get(f"{link}/agent/status").json()["projects"]
    c.post("/api/logout")
    assert c.get(f"{link}/agent/status").json()["status"] == 404
    assert u["agent"]["off"]["why"] == "logout"
    log = [e for e in admin.get("/api/users").json()["log"] if e.get("user") == "toomas" and e["type"].startswith("remote")]
    assert [e.get("why") for e in log if e["type"] == "remote-off"] == ["logout", "login", "you", "idle"]      # newest first


def test_only_the_person_switches_it_and_only_their_own_page_dials(app, admin, mari):
    c, _link = mari
    c.put("/w/mari/api/remote", json={"on": True})
    # an admin may look into mari's workspace, but not switch her remote control, nor offer their page to her agent
    assert admin.put("/w/mari/api/remote", json={"on": False}).status_code == 403
    assert admin.get("/w/mari/api/state").json()["remote"] is None
    for who, headers in ((admin, {}), (TestClient(app), {}), (c, {"origin": "https://elsewhere.example"})):
        with pytest.raises(WebSocketDisconnect):
            with who.websocket_connect("/w/mari/api/remote/tab", headers=headers) as ws:
                ws.receive_json()
    c.put("/w/mari/api/remote", json={"on": False})
    with pytest.raises(WebSocketDisconnect):       # off: no page dials in
        with c.websocket_connect("/w/mari/api/remote/tab") as ws:
            ws.receive_json()
