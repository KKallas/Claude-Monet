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


def test_the_key_alone_opens_the_agents_door(app, live, mari):
    c, link = mari
    assert c.get("/w/mari/api/state").json()["mine"] is True and "remote" not in c.get("/w/mari/api/state").json()      # no switch, no clock
    nobody = TestClient(app)        # not logged in, nothing switched on: the key is what opens it
    s = nobody.post(f"{link}/agent/status", json={}).json()
    assert s["projects"] == ["mg400_rakis", "starter"] and s["pages"] == [] and "remote" not in s
    assert nobody.get(f"{link}/file/p/starter/n/rod_foot/render.png").status_code == 200
    tools = set(nobody.get(f"{link}/agent").json()["tools"])
    assert {"screen", "goto", "view", "status"} <= tools and "page" not in tools      # no code of the agent's runs in the canvas
    assert nobody.post(f"{link}/mcp", json={}).status_code == 404               # and no MCP door (taken out, 2026-11-14)
    assert nobody.post("/w/" + "A" * 32 + "/agent/status", json={}).status_code == 404
    # no canvas open: the tools that ask one say so, the others work
    assert "no canvas of Mari is open" in c.post(f"{link}/agent/screen", json={}).json()["error"]
    assert c.post(f"{link}/agent/view", json={}).status_code == 503
    # there is nothing to switch any more
    assert c.put("/w/mari/api/remote", json={"on": False}).status_code == 404
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
        assert c.post(f"{link}/agent/screen", json={}).json()["panel"].startswith("Part 45")
        assert c.post(f"{link}/agent/goto", json={"project": "mg400_rakis", "note": "rakis", "room": "assembly"}).json()["note"] == "rakis"
        assert "room is sketch" in c.post(f"{link}/agent/goto", json={"room": "kitchen"}).json()["error"]       # not asked at all
        assert "no project 'nope'" in c.post(f"{link}/agent/goto", json={"project": "nope"}).json()["error"]
        refused = c.post(f"{link}/agent/goto", json={"note": "gone"})
        assert refused.status_code == 422 and "no Note" in refused.json()["error"]
        assert c.post(f"{link}/agent/goto", json={"room": "motion"}).json()["room"] == "motion"
        # there is no tool that runs code in the page
        assert "no tool 'page'" in c.post(f"{link}/agent/page", json={"code": "monet.S.note"}).json()["error"]
        # a picture of the canvas as it is on the screen: its address
        seen = c.post(f"{link}/agent/view", json={}).json()
        assert seen["bytes"] == len(PNG) and "png" not in seen
        assert c.get(seen["image"].split("testserver", 1)[1]).content == PNG
        assert [a["what"] for a in asked] == ["screen", "goto", "goto", "goto", "view"]
    # where it took the page is kept in the audit log; looking is not written down
    log = [e for e in admin.get("/api/users").json()["log"] if e["type"] == "agent" and e["user"] == "mari"]
    assert {("goto", "mg400_rakis", "rakis"), ("goto", None, "gone"), ("goto", None, None)} <= {(e["tool"], e.get("project"), e.get("note")) for e in log}
    assert not any(e["tool"] in ("screen", "view", "status") for e in log)
    assert until(lambda: c.post(f"{link}/agent/status", json={}).json()["pages"] == [])      # the tab closed


def test_it_stays_open_over_a_logout_and_a_new_key_closes_it(app, admin):
    c, link = person(app, admin, "toomas")
    assert c.post(f"{link}/agent/status", json={}).json()["projects"]
    assert owner(app, "toomas")["lastAgent"]                                   # when the agent was last here
    assert "agent" not in owner(app, "toomas")                                 # no switch kept with the account
    c.post("/api/logout")
    assert TestClient(app).post(f"{link}/agent/status", json={}).status_code == 200      # the agent works on while they are away
    made = admin.post(f"/api/users/{owner(app, 'toomas')['id']}/key").json()
    assert made and TestClient(app).post(f"{link}/agent/status", json={}).status_code == 404   # a new key: the old link is dead at once


def test_only_their_own_page_dials(app, admin, mari):
    c, _link = mari
    # an admin may look into mari's workspace, but not offer their page to her agent
    assert admin.get("/w/mari/api/state").json()["mine"] is False
    for who, headers in ((admin, {}), (TestClient(app), {}), (c, {"origin": "https://elsewhere.example"})):
        with pytest.raises(WebSocketDisconnect):
            with who.websocket_connect("/w/mari/api/remote/tab", headers=headers) as ws:
                ws.receive_json()
    with c.websocket_connect("/w/mari/api/remote/tab") as ws:      # her own page, with nothing switched on
        ws.send_json({"t": "state", "project": "starter"})
        assert until(lambda: len(c.post(f"{_link}/agent/status", json={}).json()["pages"]) == 1)
