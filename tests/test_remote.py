"""The agent's door and its line to the canvas (monet/remote.py): the agent key alone opens the door (the switch that
stood before it, remote control, was taken out on 2026-11-13), a new key closes it, and the agent sees and drives the
canvas the person has open. A canvas here is a websocket answered by a thread."""
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


def test_the_key_alone_opens_the_agents_door(app, live, mari):
    c, link = mari
    view = c.get("/w/mari/api/state").json()["remote"]
    assert "on" not in view and view["tabs"] == 0 and view["recent"] == []      # no switch, no clock
    nobody = TestClient(app)        # not logged in, nothing switched on: the key is what opens it
    s = nobody.post(f"{link}/agent/status", json={}).json()
    assert s["projects"] == ["mg400_rakis", "starter"] and s["pages"] == [] and "remote" not in s
    assert nobody.get(f"{link}/file/p/starter/n/rod_foot/render.png").status_code == 200
    assert rpc(live, link, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}).status_code == 200
    tools = {t["name"] for t in rpc(live, link, "tools/list").json()["result"]["tools"]}
    assert {"screen", "goto", "view", "status"} <= tools and "page" not in tools      # no code of the agent's runs in the canvas
    assert json.loads(rpc(live, link, "tools/call", {"name": "status", "arguments": {}}).json()["result"]["content"][0]["text"])["pages"] == []
    assert rpc(live, "/w/" + "A" * 32, "tools/list").status_code == 404        # a key that is nobody's opens nothing
    assert nobody.post("/w/" + "A" * 32 + "/agent/status", json={}).status_code == 404
    # no canvas open: the tools that ask one say so, the others work
    assert "no canvas of Mari is open" in c.post(f"{link}/agent/screen", json={}).json()["error"]
    assert c.post(f"{link}/agent/view", json={}).status_code == 503
    # there is nothing to switch any more
    assert c.put("/w/mari/api/remote", json={"on": False}).status_code == 405
    assert nobody.post(f"{link}/agent/status", json={}).status_code == 200


def test_the_agent_sees_the_open_canvas_and_takes_it_somewhere(app, live, admin, mari):
    c, link = mari

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
        assert until(lambda: c.post(f"{link}/agent/status", json={}).json()["pages"])
        assert c.post(f"{link}/agent/status", json={}).json()["pages"] == [{"project": "starter", "note": "rod_foot", "room": "part", "on_screen": True}]
        assert c.get("/w/mari/api/remote").json()["tabs"] == 1
        assert c.post(f"{link}/agent/screen", json={}).json()["panel"].startswith("Part 45")
        assert c.post(f"{link}/agent/goto", json={"project": "mg400_rakis", "note": "rakis", "room": "assembly"}).json()["note"] == "rakis"
        assert "room is sketch" in c.post(f"{link}/agent/goto", json={"room": "kitchen"}).json()["error"]       # not asked at all
        assert "no project 'nope'" in c.post(f"{link}/agent/goto", json={"project": "nope"}).json()["error"]
        refused = c.post(f"{link}/agent/goto", json={"note": "gone"})
        assert refused.status_code == 422 and "no Note" in refused.json()["error"]
        r = rpc(live, link, "tools/call", {"name": "goto", "arguments": {"room": "motion"}}).json()["result"]
        assert not r["isError"] and json.loads(r["content"][0]["text"])["room"] == "motion"
        # there is no tool that runs code in the page, by any door
        assert "no tool 'page'" in c.post(f"{link}/agent/page", json={"code": "monet.S.note"}).json()["error"]
        assert rpc(live, link, "tools/call", {"name": "page", "arguments": {"code": "1"}}).json()["result"]["isError"]
        # a picture of the canvas as it is on the screen: its address by HTTP, the picture itself by MCP
        seen = c.post(f"{link}/agent/view", json={}).json()
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
    assert until(lambda: c.post(f"{link}/agent/status", json={}).json()["pages"] == [])      # the tab closed


def test_it_stays_open_over_a_logout_and_a_new_key_closes_it(app, admin):
    c, link = person(app, admin, "toomas")
    assert c.post(f"{link}/agent/status", json={}).json()["projects"]
    assert c.get("/w/toomas/api/remote").json()["seen"]                       # when the agent was last here
    assert "agent" not in owner(app, "toomas")                                 # no switch kept with the account
    c.post("/api/logout")
    assert TestClient(app).post(f"{link}/agent/status", json={}).status_code == 200      # the agent works on while they are away
    made = admin.post(f"/api/users/{owner(app, 'toomas')['id']}/key").json()
    assert made and TestClient(app).post(f"{link}/agent/status", json={}).status_code == 404   # a new key: the old link is dead at once


def test_only_their_own_page_dials(app, admin, mari):
    c, _link = mari
    # an admin may look into mari's workspace, but not see what her agent did, nor offer their page to her agent
    assert admin.get("/w/mari/api/remote").status_code == 403
    assert admin.get("/w/mari/api/state").json()["remote"] is None
    for who, headers in ((admin, {}), (TestClient(app), {}), (c, {"origin": "https://elsewhere.example"})):
        with pytest.raises(WebSocketDisconnect):
            with who.websocket_connect("/w/mari/api/remote/tab", headers=headers) as ws:
                ws.receive_json()
    with c.websocket_connect("/w/mari/api/remote/tab") as ws:      # her own page, with nothing switched on
        ws.send_json({"t": "state", "project": "starter"})
        assert until(lambda: c.get("/w/mari/api/remote").json()["tabs"] == 1)
