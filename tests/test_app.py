"""The doors: the canvas API, the agent's door over plain HTTP (POST) and over MCP, and the upload of what the
agent built on its own computer."""
import contextlib
import json
import tempfile
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from monet.app import ROOT, create_app
from monet.build import build, zipped


def agent_builds(client, reg, project, note, exports=()):
    """What monet.py build does: the project's files from the agent's door, built here, the build uploaded."""
    files = client.post(f"/w/{reg['id']}/agent/sources", json={"project": project}).json()["files"]
    with tempfile.TemporaryDirectory() as t:
        for name, text in files.items():
            (Path(t) / name).write_text(text)
        build(Path(t), note, Path(t) / "out" / note, exports)
        return client.post(f"/w/{reg['id']}/upload/{project}/{note}", content=zipped(Path(t) / "out" / note),
                           headers={"content-type": "application/zip"}).json()


@contextlib.contextmanager
def browser(app):
    """Another browser at the same server: its own cookies. (The server itself is started once, by `live`.)"""
    yield TestClient(app)


def login(c, card, password="correct horse"):
    """Open a card link the way the login page does: the first time it sets the password."""
    return c.post("/api/login", json={"card": card, "password": password})


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp("monet")
    return create_app(root / "storage", root / "data", max_users=4)


@pytest.fixture(scope="module")
def live(app):
    """The server, started: what MCP needs. Nobody is logged in here."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(app, live):
    """A browser logged in as the built-in admin."""
    with browser(app) as c:
        assert login(c, app.state.admin["card"]).status_code == 200
        yield c


@pytest.fixture(scope="module")
def client(app, admin):
    """A browser logged in as mari, a user the admin let in."""
    made = admin.post("/api/users", json={"username": "mari", "name": "Mari Maasikas"}).json()["user"]
    with browser(app) as c:
        assert login(c, made["card"]).json()["home"] == "/w/mari"
        yield c


@pytest.fixture(scope="module")
def reg(client):
    """Where mari's agent comes in ("id": her agent key), and where she does ("name"). She has remote control on."""
    assert client.put("/w/mari/api/remote", json={"on": True}).json()["on"]
    state = client.get("/w/mari/api/state").json()
    return {"id": state["agent"].rsplit("/", 1)[1], "name": "mari"}


def test_the_api_describes_itself(app):
    with browser(app) as nobody:
        text = nobody.get("/api").text
        assert "agent link" in text and "### write_note" in text and "monet.py build" in text and "/upload/PROJECT/NOTE" in text
        assert "source_b64" not in text and "part=1" not in text and "GET  " not in text and "<" not in text and "register" not in text
        assert nobody.get("/llms.txt").text == text
        v = nobody.get("/api/version").json()
        assert v["license"] == "AGPL-3.0-or-later" and "starter" in v["templates"]
        assert nobody.get("/skill.zip").status_code == 200 and nobody.get("/healthz").json() == {"ok": True}


def test_a_deploy_on_its_way_and_how_long_it_took(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    running = TestClient(create_app(tmp_path / "storage", data)).get("/api/version").json()["commit"]
    # deploy.yml leaves a note as it starts building; until that build runs, the version says it is coming
    (data / "coming.json").write_text(json.dumps({"commit": "f00ba47", "since": time.time() - 30}))
    v = TestClient(create_app(tmp_path / "storage", data)).get("/api/version").json()
    assert v["coming"]["commit"] == "f00ba47" and v["coming"]["expect"] == 240 and v["coming"]["now"] - v["coming"]["since"] >= 30
    # a note nobody followed up is forgotten
    (data / "coming.json").write_text(json.dumps({"commit": "f00ba47", "since": time.time() - 3600}))
    assert TestClient(create_app(tmp_path / "storage", data)).get("/api/version").json()["coming"] is None
    # the build it named comes up: it is not coming any more, and the time it took makes the next estimate
    (data / "coming.json").write_text(json.dumps({"commit": running, "since": time.time() - 200}))
    assert TestClient(create_app(tmp_path / "storage", data)).get("/api/version").json()["coming"] is None
    assert not (data / "coming.json").exists() and json.loads((data / "deploys.json").read_text()) == [200]
    (data / "coming.json").write_text(json.dumps({"commit": "f00ba48", "since": time.time()}))
    assert TestClient(create_app(tmp_path / "storage", data)).get("/api/version").json()["coming"]["expect"] == 200


def test_nothing_of_a_workspace_without_a_login(app, reg):
    with browser(app) as nobody:
        assert nobody.get("/", follow_redirects=False).headers["location"] == "/login"
        assert nobody.get("/w/mari", follow_redirects=False).headers["location"] == "/login?next=/w/mari"
        assert nobody.get("/users", follow_redirects=False).headers["location"] == "/login?next=/users"
        r = nobody.get("/w/mari/api/state")
        assert r.status_code == 401 and r.json()["login"] is True
        assert nobody.get("/w/mari/api/p/starter/n/rod_foot").status_code == 401
        assert nobody.get("/api/users").status_code == 401 and nobody.get("/api/me").json() == {"user": None, "home": None}
        # there is no signing up
        assert nobody.post("/api/start", json={}).status_code == 404 and nobody.get("/api/register").status_code == 404
        # the agent key opens the agent's door, and only that: not the person's
        assert nobody.post(f"/w/{reg['id']}/agent/status", json={}).json()["projects"] == ["mg400_rakis", "starter"]
        assert nobody.get(f"/w/{reg['id']}/agent/status").status_code == 405      # tools are called by POST
        assert nobody.get(f"/w/{reg['id']}/api/state").status_code == 401
        assert nobody.delete(f"/w/{reg['id']}/api/p/starter/n/rod_foot/checks/bed").status_code == 401
        # and a name is not a key
        assert nobody.post("/w/mari/agent/status", json={}).status_code == 404


def test_logging_in_the_card_the_password_and_the_wrong_one(app, admin):
    made = admin.post("/api/users", json={"username": "jaan", "name": "Jaan"}).json()["user"]
    assert made["hasPassword"] is False and made["projects"] == ["mg400_rakis", "starter"]
    with browser(app) as c:
        assert c.get(f"/api/login/card/{made['card']}").json() == {"username": "jaan", "name": "Jaan", "hasPassword": False}
        # a username alone cannot set a first password: knowing a name is not enough to claim the account
        r = c.post("/api/login", json={"username": "jaan", "password": "something long"})
        assert r.status_code == 400 and r.json()["needsCard"] is True
        assert login(c, made["card"], "short").status_code == 400
        assert login(c, made["card"], "a good password").json()["home"] == "/w/jaan"
        assert c.get("/api/me").json()["user"]["username"] == "jaan"
        assert c.get("/", follow_redirects=False).headers["location"] == "/w/jaan"
        assert c.get("/w/jaan").status_code == 200
        # one user is not another: mari's workspace is not there for jaan, and neither are the users
        assert c.get("/w/mari/api/state").status_code == 404 and c.get("/w/mari", follow_redirects=False).headers["location"] == "/w/jaan"
        assert c.get("/api/users").status_code == 403
        c.post("/api/logout")
        assert c.get("/w/jaan/api/state").status_code == 401
        assert c.post("/api/login", json={"username": "jaan", "password": "wrong"}).status_code == 401
        assert c.post("/api/login", json={"username": "jaan", "password": "a good password"}).status_code == 200
        # changing the password ends the other sessions and keeps this one
        assert c.put("/api/me/password", json={"current": "nope", "password": "another good one"}).status_code == 401
        assert c.put("/api/me/password", json={"current": "a good password", "password": "another good one"}).status_code == 200
        assert c.get("/w/jaan/api/state").status_code == 200
    # HTTP Basic, for scripts
    with browser(app) as script:
        assert script.get("/w/jaan/api/state", auth=("jaan", "another good one")).status_code == 200
        assert script.get("/w/jaan/api/state", auth=("jaan", "a good password")).status_code == 401


def test_the_admin_keeps_the_users(app, admin, reg):
    listing = admin.get("/api/users").json()
    assert [u["username"] for u in listing["users"]] == ["admin", "jaan", "mari"] and listing["max"] == 4
    assert all("password" not in u and "key" not in u for u in listing["users"])          # never the hash, never the agent key
    assert any(e["type"] == "user-new" for e in listing["log"])
    jaan = next(u for u in listing["users"] if u["username"] == "jaan")
    assert admin.get(f"/api/users/{jaan['id']}/card.svg").text.startswith("<svg")
    assert admin.get("/users").status_code == 200 and admin.get("/w/mari/api/state").json()["workspace"]["username"] == "mari"     # an admin may look in
    assert admin.post("/api/users", json={"username": "Bad Name"}).status_code == 400
    assert admin.post("/api/users", json={"username": "mari"}).status_code == 409
    # the instance takes so many users and no more
    assert admin.post("/api/users", json={"username": "kati"}).status_code == 200
    full = admin.post("/api/users", json={"username": "peeter"})
    assert full.status_code == 409 and "takes 4 users" in full.json()["error"]
    kati = next(u for u in admin.get("/api/users").json()["users"] if u["username"] == "kati")
    assert admin.put(f"/api/users/{kati['id']}", json={"role": "admin", "name": "Kati K"}).json()["user"]["role"] == "admin"
    assert admin.delete(f"/api/users/{kati['id']}").status_code == 200
    root = app.state.admin
    assert admin.delete(f"/api/users/{root['id']}").status_code == 400 and admin.put(f"/api/users/{root['id']}", json={"role": "user"}).status_code == 400
    # a forgotten password: cleared, signed out everywhere, the card asks for a new one
    with browser(app) as c:
        assert c.post("/api/login", json={"username": "jaan", "password": "another good one"}).status_code == 200
        assert admin.post(f"/api/users/{jaan['id']}/reset").json()["user"]["hasPassword"] is False
        assert c.get("/w/jaan/api/state").status_code == 401
        assert login(c, jaan["card"], "third time lucky").status_code == 200
        # a lost card: the old link stops working
        new = admin.post(f"/api/users/{jaan['id']}/card").json()["user"]["card"]
        assert new != jaan["card"] and c.get(f"/api/login/card/{jaan['card']}").status_code == 404
        # an agent link that got out: a new key, by the user or by the admin, and the old one is dead at once
        old = c.get("/w/jaan/api/state").json()["agent"]
        c.put("/w/jaan/api/remote", json={"on": True})
        mine = c.post("/w/jaan/api/key", json={}).json()["agent"]
        assert mine != old and c.post(old.split("testserver", 1)[1] + "/agent/status", json={}).status_code == 404
        assert c.post(mine.split("testserver", 1)[1] + "/agent/status", json={}).json()["projects"]
        admin.post(f"/api/users/{jaan['id']}/key")
        assert c.post(mine.split("testserver", 1)[1] + "/agent/status", json={}).status_code == 404
    # the folders of the working files are named by user id, never by a name or a key
    names = {q.name for q in app.state.workspaces.storage.iterdir()}
    assert jaan["id"] in names and "mari" not in names and reg["id"] not in names


def test_the_agent_writes_builds_here_and_uploads(client, reg):
    """The server keeps a Note and never runs it: the agent builds it on its own computer from the files the server
    has, and uploads what the build left. Then it is built, measured and checked."""
    agent = f"/w/{reg['id']}/agent"
    assert "write_note" in client.get(agent).json()["tools"]
    source = "from build123d import *\nPARAMS = dict(d=8.0)\nTAGS = {\"pin\": {\"kind\": \"boss\", \"axis\": \"Z\", \"at\": [0, 0], \"diameter\": 8.0}}\ndef build(p=PARAMS):\n    return Cylinder(p[\"d\"] / 2, 20)\n"
    sent = client.post(f"{agent}/write_note", json={"project": "starter", "note": "peg", "source": source}).json()
    assert sent["state"] == "unbuilt" and "monet.py build starter peg" in sent["waiting"]
    r = agent_builds(client, reg, "starter", "peg")
    assert r["green"] and r["by"] == "agent" and r["tags"]["pin"]["measure"]["diameter"] == 8.0
    r = client.post(f"{agent}/add_check", json={"project": "starter", "note": "peg", "what": "tag.pin.diameter", "min": 7.9, "max": 8.1}).json()
    assert r["added"]["min"] == 7.9 and r["report"]["green"]
    client.post(f"{agent}/write_note", json={"project": "starter", "note": "peg", "source": source.replace("8.0", "9.0")})
    r = agent_builds(client, reg, "starter", "peg")
    assert not r["green"] and [c["id"] for c in r["checks"] if not c["ok"]] == ["tag-pin-diameter"]
    client.post(f"{agent}/write_note", json={"project": "starter", "note": "peg", "source": source})
    assert agent_builds(client, reg, "starter", "peg")["green"]
    # an upload is a build of what the server has, by name, or nothing
    up = f"/w/{reg['id']}/upload/starter/peg"
    assert "as a zip" in client.post(up, json={}).json()["error"]
    assert "not a zip" in client.post(up, content=b"nope", headers={"content-type": "application/zip"}).json()["error"]
    assert client.post(f"/w/{reg['name']}/upload/starter/peg", content=b"", headers={"content-type": "application/zip"}).status_code == 404
    # no Note by GET, in parts or as base64 any more
    assert client.get(f"{agent}/write_note", params={"project": "starter", "note": "peg", "source": source}).status_code == 405
    assert client.post(f"{agent}/write_note", json={"project": "starter", "note": "peg", "source_b64": "eA"}).status_code == 400


def test_a_mistake_has_its_status(client, reg):
    agent = f"/w/{reg['id']}/agent"
    r = client.post(f"{agent}/check", json={"project": "nope", "note": "x"})
    assert r.status_code == 404 and "no project" in r.json()["error"]
    assert client.post(f"{agent}/check", json={}).status_code == 400
    assert client.post(f"{agent}/nonsense", json={}).status_code == 404


def test_look_gives_the_address_of_a_picture(client, reg):
    r = client.post(f"/w/{reg['id']}/agent/look", json={"project": "starter", "note": "rod_foot", "views": "iso"}).json()
    path = r["image"].split("testserver", 1)[1]
    img = client.get(path)
    assert img.headers["content-type"] == "image/png" and img.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_person_points_and_tags_and_the_agent_sees_it(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    n = f"{h}/api/p/starter/n/rod_foot"
    faces = client.get(f"{n}/faces.json").json()["faces"]
    top = next(f for f in faces if f["type"] == "plane" and f["normal"][2] > 0.99 and abs(f["center"][2] - 22.4) < 0.01)
    assert not client.post(f"{w}/agent/selection", json={"project": "starter"}).json()["selected"]
    client.post(f"{h}/api/p/starter/selection", json={"note": "rod_foot", "face": top, "point": top["center"], "tags": []})
    sel = client.post(f"{w}/agent/selection", json={"project": "starter"}).json()
    assert sel["selected"] and sel["selector"] == {"kind": "planar_face", "normal": "+Z", "at": 22.4}
    report = client.post(f"{n}/tags", json={"name": "clamp_face", "role": "the clamp presses here", "face": top}).json()
    assert report["green"] and report["tags"]["clamp_face"]["resolved"]
    note = client.get(n).json()
    assert note["tags"]["clamp_face"] == {"kind": "planar_face", "normal": "+Z", "at": 22.4, "role": "the clamp presses here"}
    assert note["tag_faces"]["clamp_face"] == [top["i"]] and note["load_check"]["status"] == "new"
    assert client.delete(f"{n}/tags/clamp_face").json()["green"]
    assert "clamp_face" not in client.get(n).json()["tags"]


def test_pointing_at_a_part_of_an_assembly(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    described = client.get(f"{h}/api/p/mg400_rakis/n/rakis/faces.json").json()
    assert len(described["parts"]) == 14
    part = next(p for p in described["parts"] if p["name"] == "L_back_pos")
    face = described["faces"][part["faces"][0]]
    client.post(f"{h}/api/p/mg400_rakis/selection", json={"note": "rakis", "face": face, "point": face["center"], "tags": [], "part": part["name"]})
    assert client.post(f"{w}/agent/selection", json={"project": "mg400_rakis"}).json()["part"] == "L_back_pos"
    notes = {n["name"]: n["kind"] for n in client.get(f"{h}/api/p/mg400_rakis").json()["notes"]}
    assert notes["rakis"] == "assembly"
    assert len(client.post(f"{w}/agent/check", json={"project": "mg400_rakis", "note": "rakis"}).json()["parts"]) == 14


def test_the_agent_sees_a_selection_of_many_things(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    d = client.get(f"{h}/api/p/starter/n/rod_foot/faces.json").json()
    face = {k: v for k, v in d["faces"][0].items() if k != "tris"}
    edge = {k: v for k, v in d["edges"][0].items() if k not in ("segs", "p")}
    items = [{"kind": "face", **face}, {"kind": "edge", **edge}, {"kind": "vertex", "at": d["points"][0]["at"]}, {"kind": "part", "name": "rod_foot"}]
    client.post(f"{h}/api/p/starter/selection", json={"note": "rod_foot", "mode": "edge", "count": 4, "items": items, "measure": {"length, mm": 45}})
    sel = client.post(f"{w}/agent/selection", json={"project": "starter"}).json()
    assert sel["selected"] and sel["mode"] == "edge" and sel["count"] == 4 and sel["measure"] == {"length, mm": 45}
    assert [i["kind"] for i in sel["items"]] == ["face", "edge", "vertex", "part"]
    assert [i["selector"]["kind"] for i in sel["items"]] == ["planar_face", "edge", "point", "object"]      # how each would be found again
    assert sel["items"][1]["type"] == "line" and sel["items"][2]["at"] == d["points"][0]["at"]
    client.post(f"{h}/api/p/starter/selection", json={})               # cleared in the canvas
    assert not client.post(f"{w}/agent/selection", json={"project": "starter"}).json()["selected"]


def test_a_tag_of_several_things_and_a_check_on_what_lies_between(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    n = f"{h}/api/p/starter/n/rod_foot"
    d = client.get(f"{n}/faces.json").json()
    flat = lambda z, up: next({k: v for k, v in f.items() if k != "tris"} for f in d["faces"]
                              if f["type"] == "plane" and f["normal"][2] * up > 0.99 and abs(f["center"][2] - z) < 0.01)
    report = client.post(f"{n}/tags", json={"name": "height", "role": "overall height",
                                           "items": [{"kind": "face", **flat(0, -1)}, {"kind": "face", **flat(22.4, 1)}]}).json()
    assert report["green"] and report["tags"]["height"]["measure"] == {"count": 2, "area": 2016.0, "distance": 22.4}
    note = client.get(n).json()
    assert note["tags"]["height"] == {"kind": "group", "role": "overall height", "of": [
        {"kind": "planar_face", "normal": "-Z", "at": 0.0}, {"kind": "planar_face", "normal": "+Z", "at": 22.4}]}
    assert len(note["tag_hits"]["height"]["faces"]) == 2
    # the dimension has a name now: a check holds it
    assert client.post(f"{n}/checks", json={"what": "tag.height.distance", "min": 22.3, "max": 22.5, "why": "fits under the shelf"}).json()["report"]["green"]
    edge = {k: v for k, v in d["edges"][0].items() if k not in ("segs", "p")}
    mixed = client.post(f"{n}/tags", json={"name": "corner_edge", "items": [{"kind": "edge", **edge}, {"kind": "vertex", "at": d["points"][0]["at"]}]}).json()
    assert mixed["green"] and client.get(n).json()["tag_hits"]["corner_edge"] == {"faces": [], "edges": [0], "points": [0], "parts": [], "curves": []}
    assert client.post(f"{n}/tags", json={"name": "nothing", "items": []}).status_code == 400
    for name in ("height", "corner_edge"):
        client.delete(f"{n}/tags/{name}")
    client.delete(f"{n}/checks/tag-height-distance")


def test_a_sketch_becomes_a_tag_on_its_face(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    n = f"{h}/api/p/starter/n/rod_foot"
    top = next({k: v for k, v in f.items() if k != "tris"} for f in client.get(f"{n}/faces.json").json()["faces"]
               if f["type"] == "plane" and f["normal"][2] > 0.99 and abs(f["center"][2] - 22.4) < 0.01)
    drawing = {"plane": {"origin": [0, 0, 22.4], "normal": [0, 0, 1], "x": [1, 0, 0]},
               "curves": [{"type": "rect", "at": [-9, -3], "size": [15, 7]}, {"type": "circle", "center": [13, 0], "r": 3}]}
    report = client.post(f"{n}/tags", json={"name": "pocket", "role": "cut 3 deep", "sketch": drawing, "face": top}).json()
    assert report["green"] and report["tags"]["pocket"] == {"resolved": True, "measure": {"curves": 2, "closed": 2}}
    tag = client.get(n).json()["tags"]["pocket"]
    assert tag["kind"] == "sketch" and tag["on"] == {"kind": "planar_face", "normal": "+Z", "at": 22.4} and tag["role"] == "cut 3 deep"
    assert tag["curves"][0] == {"type": "rect", "at": [-9.0, -3.0], "size": [15.0, 7.0]}
    assert client.post(f"{n}/tags", json={"name": "bad", "sketch": {"plane": {}, "curves": []}}).status_code == 400
    # the agent reads the drawing where it reads everything else
    assert "pocket" in client.post(f"{w}/agent/read_note", json={"project": "starter", "note": "rod_foot"}).json()["source"]
    client.delete(f"{n}/tags/pocket")


def test_a_plane_on_a_face_and_a_sketch_on_that_plane(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    n = f"{h}/api/p/starter/n/rod_foot"
    top = next({k: v for k, v in f.items() if k != "tris"} for f in client.get(f"{n}/faces.json").json()["faces"]
               if f["type"] == "plane" and f["normal"][2] > 0.99 and abs(f["center"][2] - 22.4) < 0.01)
    frame = {"origin": [0, 0, 27.4], "normal": [0, 0, 1], "x": [1, 0, 0]}
    report = client.post(f"{n}/tags", json={"name": "label_plane", "plane": {"plane": frame, "offset": 5}, "face": top}).json()
    assert report["green"] and report["tags"]["label_plane"] == {"resolved": True, "measure": {"offset": 5.0}}
    tag = client.get(n).json()["tags"]["label_plane"]
    assert tag["kind"] == "plane" and tag["offset"] == 5.0 and tag["on"] == {"kind": "planar_face", "normal": "+Z", "at": 22.4}
    drawing = {"plane": tag["plane"], "plane_name": "label_plane", "on": tag["on"], "curves": [{"type": "rect", "at": [-5, -2], "size": [9, 5]}]}
    assert client.post(f"{n}/tags", json={"name": "label", "sketch": drawing}).json()["green"]
    label = client.get(n).json()["tags"]["label"]
    assert label["plane_name"] == "label_plane" and label["on"] == tag["on"] and label["plane"]["origin"] == [0.0, 0.0, 27.4]
    assert client.post(f"{n}/tags", json={"name": "bad", "plane": {"plane": {"origin": [0, 0, 0]}}}).status_code == 400
    # the distance of the plane off its face, changed afterwards: what was drawn on it goes with it
    moved = client.put(f"{n}/planes/label_plane", json={"offset": 8}).json()
    assert moved["green"] and moved["tags"]["label_plane"]["measure"] == {"offset": 8.0}
    after = client.get(n).json()["tags"]
    assert after["label_plane"]["plane"]["origin"] == [0.0, 0.0, 30.4] and after["label"]["plane"]["origin"] == [0.0, 0.0, 30.4]
    assert after["label"]["curves"] == label["curves"]
    assert client.put(f"{n}/planes/nope", json={"offset": 1}).status_code == 404 and client.put(f"{n}/planes/label_plane", json={"offset": "far"}).status_code == 400
    # a plane like Top, a distance off it: no face under it
    copy = client.post(f"{n}/tags", json={"name": "top_1", "plane": {"plane": {"origin": [0, 0, 10], "normal": [0, 0, 1], "x": [1, 0, 0]}, "offset": 10, "base": "top"}}).json()
    assert copy["green"] and client.get(n).json()["tags"]["top_1"] == {"kind": "plane", "plane": {"origin": [0.0, 0.0, 10.0], "normal": [0.0, 0.0, 1.0], "x": [1.0, 0.0, 0.0]}, "offset": 10.0, "base": "top"}
    # one line of the sketch, named by itself, and seen by the agent as something selected
    one = client.post(f"{n}/tags", json={"name": "label_edge", "role": "engrave along it", "items": [{"kind": "curve", "sketch": "label", "index": 0, "curve": label["curves"][0]}]}).json()
    assert one["green"] and one["tags"]["label_edge"] == {"resolved": True, "measure": {"length": 28.0, "closed": True}}
    assert client.get(n).json()["tag_hits"]["label_edge"]["curves"] == ["label:0"]
    client.post(f"{h}/api/p/starter/selection", json={"note": "rod_foot", "mode": "edge", "items": [{"kind": "curve", "sketch": "label", "index": 0, "curve": label["curves"][0], "role": ""}]})
    item = client.post(f"{w}/agent/selection", json={"project": "starter"}).json()["items"][0]
    assert item["kind"] == "curve" and item["selector"]["kind"] == "sketch_curve" and item["selector"]["sketch"] == "label"
    client.post(f"{h}/api/p/starter/selection", json={})
    for name in ("label_edge", "label", "label_plane", "top_1"):
        client.delete(f"{n}/tags/{name}")


def test_what_a_part_is_made_of(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    looks = client.put(f"{h}/api/p/starter/looks", json={"names": ["rod_foot"], "material": "aluminium", "color": "#AA3311"}).json()["looks"]
    assert looks == {"rod_foot": {"material": "aluminium", "color": "#aa3311"}}
    assert client.put(f"{h}/api/p/starter/looks", json={"names": ["rod_foot"], "color": None}).json()["looks"] == {"rod_foot": {"material": "aluminium"}}
    assert client.get(f"{h}/api/p/starter").json()["looks"] == {"rod_foot": {"material": "aluminium"}}
    assert client.put(f"{h}/api/p/starter/looks", json={"names": ["rod_foot"], "material": "gold"}).status_code == 400
    assert client.put(f"{h}/api/p/starter/looks", json={"names": ["rod_foot"], "color": "red"}).status_code == 400
    # the sample comes with its pipes in aluminium
    assert client.get(f"{h}/api/p/mg400_rakis").json()["looks"]["pipe_long_pos"] == {"material": "aluminium"}


def test_checks_are_the_persons_to_change(client, reg):
    n = f"/w/{reg['name']}/api/p/starter/n/rod_foot"
    assert client.post(f"{n}/checks", json={"what": "size_x", "max": 40, "why": "fits the drawer"}).json()["report"]["green"] is False
    assert client.put(f"{n}/checks/size-x", json={"what": "size_x", "max": 50}).json()["report"]["green"]
    assert client.delete(f"{n}/checks/size-x").json()["report"]["green"]
    assert client.delete(f"{n}/checks/size-x").status_code == 404
    # the agent's door has no such tools
    assert set(client.get(f"/w/{reg['id']}/agent").json()["tools"]) & {"delete_check", "put_check", "acknowledge", "delete_note"} == set()


def test_save_versions_export_over_http(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    saved = client.post(f"{w}/agent/save", json={"project": "starter", "message": "first"}).json()
    assert saved["saved"] and saved["version"] == 1
    assert client.post(f"{w}/agent/versions", json={"project": "starter"}).json()["versions"][0]["message"] == "first"
    assert "--export stl" in client.post(f"{w}/agent/export", json={"project": "starter", "note": "rod_foot", "format": "stl"}).json()["error"]
    agent_builds(client, reg, "starter", "rod_foot", exports=("stl",))
    url = client.post(f"{w}/agent/export", json={"project": "starter", "note": "rod_foot", "format": "stl"}).json()["url"]
    stl = client.get(url.split("testserver", 1)[1])
    assert stl.status_code == 200 and "rod_foot.stl" in stl.headers["content-disposition"]
    assert client.get(f"{h}/api/p/starter/n/rod_foot/fingerprint.json").json()["fingerprint"]["solids"] == 1
    assert client.get(f"{h}/api/p/starter").json()["version"] == 1


def test_what_agents_change_is_written_down(app, admin, client, reg):
    client.post(f"/w/{reg['id']}/agent/save", json={"project": "starter", "message": "again"})
    log = admin.get("/api/users").json()["log"]
    assert any(e["type"] == "agent" and e["user"] == "mari" and e["tool"] == "write_note" and e["note"] == "peg" for e in log)
    assert not any(e["type"] == "agent" and e.get("tool") in ("status", "look", "check") for e in log)      # looking is not written down
    assert next(u for u in admin.get("/api/users").json()["users"] if u["username"] == "mari")["lastAgent"]


def test_projects_are_archived_uploaded_and_deleted_by_the_person_only(app, admin, client, reg):
    rows = {p["name"]: p for p in client.get("/w/mari/api/projects").json()["projects"]}
    assert set(rows) == {"mg400_rakis", "starter"} and rows["starter"]["version"] >= 1 and rows["mg400_rakis"]["notes"] == 10
    got = client.get("/w/mari/api/p/starter/archive.zip")
    assert got.headers["content-type"] == "application/zip" and 'filename="starter.zip"' in got.headers["content-disposition"]
    zipped = {"content": got.content, "headers": {"content-type": "application/zip"}}
    assert client.post("/w/mari/api/projects/upload?name=copy", **zipped).json() == {"project": "copy", "left_out": 0}
    assert client.get("/w/mari/api/p/copy").json()["version"] == rows["starter"]["version"]
    assert client.post("/w/mari/api/projects/upload?name=copy", **zipped).status_code == 409
    assert "lowercase" in client.post("/w/mari/api/projects/upload", **zipped).json()["error"]
    assert "as the body" in client.post("/w/mari/api/projects/upload?name=other", json={}).json()["error"]
    assert "not a zip" in client.post("/w/mari/api/projects/upload?name=other", content=b"nothing", headers={"content-type": "application/zip"}).json()["error"]
    # none of it through the agent's door: the key opens no route of the canvas, and there is no such tool
    agent = f"/w/{reg['id']}"
    with browser(app) as nobody:
        assert nobody.delete(f"{agent}/api/p/copy").status_code == 401 and nobody.get(f"{agent}/api/p/copy/archive.zip").status_code == 401
        assert nobody.post(f"{agent}/api/projects/upload?name=theirs", **zipped).status_code == 401
        assert nobody.delete("/w/mari/api/p/copy").status_code == 401
        for tool in ("delete_project", "upload_project", "archive"):
            assert nobody.post(f"{agent}/agent/{tool}", json={"project": "copy"}).status_code == 404
    assert client.delete(f"{agent}/api/p/copy").status_code == 404 and "copy" in client.get("/w/mari/api/state").json()["projects"]
    assert client.delete("/w/mari/api/p/copy").json() == {"deleted": "copy", "projects": ["mg400_rakis", "starter"]}
    assert client.delete("/w/mari/api/p/copy").status_code == 404 and client.get("/w/mari/api/p/copy").status_code == 404
    log = admin.get("/api/users").json()["log"]
    assert [e["project"] for e in log if e["type"] in ("project-upload", "project-delete") and e["user"] == "mari"] == ["copy", "copy"]


def test_mcp_door(live, client, reg):
    def rpc(method, params, wid=reg["id"]):
        return live.post(f"/w/{wid}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                           headers={"accept": "application/json, text/event-stream"})
    tools = {t["name"] for t in rpc("tools/list", {}).json()["result"]["tools"]}
    assert {"guide", "write_note", "look", "save", "selection"} <= tools
    r = rpc("tools/call", {"name": "status", "arguments": {"project": "starter"}}).json()["result"]
    assert json.loads(r["content"][0]["text"])["project"] == "starter"
    r = rpc("tools/call", {"name": "look", "arguments": {"project": "starter", "note": "rod_foot", "views": "iso"}}).json()["result"]
    assert [c["type"] for c in r["content"]] == ["text", "image"]
    r = rpc("tools/call", {"name": "check", "arguments": {"project": "nope", "note": "x"}}).json()["result"]
    assert r["isError"] and "no project 'nope'" in r["content"][0]["text"]       # the reason reaches the model
    assert "Rules" in json.loads(rpc("tools/call", {"name": "guide", "arguments": {}}).json()["result"]["content"][0]["text"])["guide"]
    assert rpc("tools/list", {}, wid="A" * 32).status_code == 404 and rpc("tools/list", {}, wid=reg["name"]).status_code == 404


def test_skill_zip(client):
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(client.get("/skill.zip").content)).namelist()
    assert "monet/SKILL.md" in names and "monet/scripts/monet.py" in names and "monet/references/tags-and-checks.md" in names
    assert "monet/link.txt" not in names       # the public one carries nobody's key
    # the builder the agent builds with: this server's own Monet, and its kernel pinned to the version here
    z = zipfile.ZipFile(io.BytesIO(client.get("/skill.zip").content))
    assert {f"monet/lib/monet/{m}.py" for m in ("runner", "build", "derive", "note", "__init__")} <= set(names)
    assert z.read("monet/lib/monet/runner.py") == (ROOT / "monet" / "runner.py").read_bytes()
    from importlib.metadata import version
    assert f'"build123d=={version("build123d")}"' in z.read("monet/scripts/builder.py").decode()


def test_the_persons_skill_carries_their_link(admin, client, reg, tmp_path, monkeypatch):
    import importlib.util, io, zipfile
    got = client.get("/w/mari/api/skill.zip")
    assert got.headers["content-type"] == "application/zip" and got.headers["cache-control"] == "no-store"
    zipfile.ZipFile(io.BytesIO(got.content)).extractall(tmp_path)
    link = client.get("/w/mari/api/state").json()["agent"]
    assert (tmp_path / "monet" / "link.txt").read_text().strip() == link and (tmp_path / "monet" / "SKILL.md").exists()
    # its script finds the link by itself; MONET_URL, when set, goes first
    monkeypatch.delenv("MONET_URL", raising=False)
    spec = importlib.util.spec_from_file_location("monet_skill_script", tmp_path / "monet" / "scripts" / "monet.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.URL == link
    # it holds the key: only for the person, never for an admin looking in, nor through the agent's door
    assert admin.get("/w/mari/api/skill.zip").status_code == 403
    assert TestClient(client.app).get("/w/mari/api/skill.zip").status_code == 401
    assert client.get(f"/w/{reg['id']}/api/skill.zip").status_code == 404


LIDBOX = '''"""A box with a lid on a hinge pin, behind the box's back wall."""
from build123d import *

TAGS = {}


def build():
    base = Pos(3, 0, 0) * Box(34, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    lid = Pos(0, 0, 10) * Box(40, 40, 4, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(-15, 0, 12) * Rot(90, 0, 0) * Cylinder(1, 40)
    base.label, lid.label = "base", "lid"
    return Compound(children=[base, lid])
'''


def test_a_joint_made_in_the_canvas_and_a_pose_for_the_agent(client, reg):
    """The person picks the hinge's hole in Motion: the hole is tagged and the joint turns about it, in one write.
    What a pose hits is the canvas's to ask and the agent's to look at."""
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    assert client.post(f"{w}/agent/write_note", json={"project": "starter", "note": "lidbox", "source": LIDBOX}).json()["state"] == "unbuilt"
    assert agent_builds(client, reg, "starter", "lidbox")["green"]
    n = f"{h}/api/p/starter/n/lidbox"
    hole = next(f for f in client.get(f"{n}/faces.json").json()["faces"] if f["type"] == "cylinder" and f["concave"])
    report = client.put(f"{n}/joints/hinge", json={"kind": "revolute", "moves": "lid", "on": "base", "face": hole, "range": [0, 120]}).json()
    assert report["green"], [c for c in report["checks"] if not c["ok"]]
    hinge = report["motion"]["joints"]["hinge"]
    assert hinge["resolved"] and abs(hinge["dir"][1]) == 1.0 and hinge["origin"][0] == -15.0 and hinge["origin"][2] == 12.0
    note = client.get(n).json()
    assert note["joints"]["hinge"]["axis"] == "hinge_axis" and note["tags"]["hinge_axis"]["kind"] == "round_hole"
    assert client.put(f"{n}/ground", json={"ground": "base"}).json()["motion"]["ground"] == ["base"]
    assert "GROUND = \"base\"" in client.get(n).json()["source"]

    # one way the lid lifts off its box, the other it goes into it
    one, other = (client.post(f"{n}/pose", json={"values": {"hinge": a}}).json()["clashes"] for a in (30, -30))
    assert sorted([one, other], key=len)[0] == [] and [p[:2] for p in sorted([one, other], key=len)[1]] == [["base", "lid"]]
    assert client.post(f"{n}/pose", json={"values": {"nope": 1}}).status_code == 400

    # the agent sees the same, with a picture
    seen = client.post(f"{w}/agent/pose", json={"project": "starter", "note": "lidbox", "values": "hinge=30"}).json()
    assert seen["values"]["hinge"] == 30 and "pose=hinge%3D30" in seen["image"]
    png = client.get(seen["image"].split("testserver", 1)[1])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.post(f"{w}/agent/check", json={"project": "starter", "note": "lidbox"}).json()["motion"]["sweeps"]["hinge"]["clash_mm3"] >= 0

    # and the person takes it away again
    assert "hinge" not in client.delete(f"{n}/joints/hinge").json()["motion"]["joints"]
    assert client.put(f"{n}/joints/bad name", json={"kind": "rigid", "moves": "lid", "on": "base"}).status_code == 400


def test_the_agent_leads_the_nose_and_sees_the_arm_there(client, reg):
    w = f"/w/{reg['id']}"
    r = client.post(f"{w}/agent/reach", json={"project": "mg400_rakis", "note": "mg400_blocks", "x": 250, "y": 120, "z": 200}).json()
    assert r["reached"] and r["off"] < 0.05 and r["tip"] == pytest.approx([250, 120, 200], abs=0.05), r
    assert r["clashes"] == [] and set(r["values"]) == {"j1", "j2", "j3", "j4"}
    png = client.get(r["image"].split("testserver", 1)[1])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    far = client.post(f"{w}/agent/reach", json={"project": "mg400_rakis", "note": "mg400_blocks", "x": 900, "y": 0, "z": 0}).json()
    assert not far["reached"] and far["off"] > 100
    assert "no tips" in client.post(f"{w}/agent/reach", json={"project": "mg400_rakis", "note": "rakis", "x": 0, "y": 0, "z": 0}).json()["error"]
