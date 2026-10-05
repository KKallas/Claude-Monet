"""The doors: the canvas API, the agent's door over plain HTTP (GET and POST) and over MCP."""
import base64
import contextlib
import json

import pytest
from starlette.testclient import TestClient

from monet.app import create_app


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
    """Where mari's agent comes in ("id": her agent key), and where she does ("name")."""
    state = client.get("/w/mari/api/state").json()
    return {"id": state["agent"].rsplit("/", 1)[1], "name": "mari"}


def test_the_api_describes_itself(app):
    with browser(app) as nobody:
        text = nobody.get("/api").text
        assert "agent link" in text and "### write_note" in text and "source_b64" in text and "register" not in text
        assert nobody.get("/llms.txt").text == text
        v = nobody.get("/api/version").json()
        assert v["license"] == "AGPL-3.0-or-later" and "starter" in v["templates"]
        assert nobody.get("/skill.zip").status_code == 200 and nobody.get("/healthz").json() == {"ok": True}


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
        assert nobody.get(f"/w/{reg['id']}/agent/status").json()["projects"] == ["mg400_rakis", "starter"]
        assert nobody.get(f"/w/{reg['id']}/api/state").status_code == 401
        assert nobody.delete(f"/w/{reg['id']}/api/p/starter/n/rod_foot/checks/bed").status_code == 401
        # and a name is not a key
        assert nobody.get("/w/mari/agent/status").json()["status"] == 404
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
        mine = c.post("/w/jaan/api/key", json={}).json()["agent"]
        assert mine != old and c.get(old.split("testserver", 1)[1] + "/agent/status").json()["status"] == 404
        assert c.get(mine.split("testserver", 1)[1] + "/agent/status").json()["projects"]
        admin.post(f"/api/users/{jaan['id']}/key")
        assert c.get(mine.split("testserver", 1)[1] + "/agent/status").json()["status"] == 404
    # the folders of the working files are named by user id, never by a name or a key
    names = {q.name for q in app.state.workspaces.storage.iterdir()}
    assert jaan["id"] in names and "mari" not in names and reg["id"] not in names


def test_tools_by_get_with_a_query_string(client, reg):
    agent = f"/w/{reg['id']}/agent"
    assert "write_note" in client.get(agent).json()["tools"]
    assert client.get(f"{agent}/status").json()["projects"] == ["mg400_rakis", "starter"]
    source = "from build123d import *\nPARAMS = dict(d=8.0)\nTAGS = {\"pin\": {\"kind\": \"boss\", \"axis\": \"Z\", \"at\": [0, 0], \"diameter\": 8.0}}\ndef build(p=PARAMS):\n    return Cylinder(p[\"d\"] / 2, 20)\n"
    r = client.get(f"{agent}/write_note", params={"project": "starter", "note": "peg", "source": source}).json()
    assert r["green"] and r["tags"]["pin"]["measure"]["diameter"] == 8.0
    r = client.get(f"{agent}/add_check", params={"project": "starter", "note": "peg", "what": "tag.pin.diameter", "min": "7.9", "max": "8.1"}).json()
    assert r["added"]["min"] == 7.9 and r["report"]["green"]
    r = client.get(f"{agent}/add_check", params={"project": "starter", "note": "peg", "what": "solids", "equals": "1"}).json()
    assert r["added"]["equals"] == 1.0 and r["report"]["green"]
    b64 = base64.urlsafe_b64encode(source.replace("8.0", "9.0").encode()).decode().rstrip("=")
    r = client.get(f"{agent}/write_note", params={"project": "starter", "note": "peg", "source_b64": b64}).json()
    assert not r["green"] and [c["id"] for c in r["checks"] if not c["ok"]] == ["tag-pin-diameter"]
    r = client.post(f"{agent}/write_note", params={"project": "starter", "note": "peg"}, content=source, headers={"content-type": "text/plain"}).json()
    assert r["green"]


def test_a_mistake_by_get_is_readable_and_by_post_has_its_status(client, reg):
    agent = f"/w/{reg['id']}/agent"
    r = client.get(f"{agent}/check", params={"project": "nope", "note": "x"})
    assert r.status_code == 200 and r.json()["status"] == 404 and "no project" in r.json()["error"]
    assert client.get(f"{agent}/check").json()["status"] == 400
    assert client.get(f"{agent}/nonsense").json()["status"] == 404
    assert client.post(f"{agent}/check", json={"project": "nope", "note": "x"}).status_code == 404


def test_look_gives_the_address_of_a_picture(client, reg):
    r = client.get(f"/w/{reg['id']}/agent/look", params={"project": "starter", "note": "rod_foot", "views": "iso"}).json()
    path = r["image"].split("testserver", 1)[1]
    img = client.get(path)
    assert img.headers["content-type"] == "image/png" and img.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_person_points_and_tags_and_the_agent_sees_it(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    n = f"{h}/api/p/starter/n/rod_foot"
    faces = client.get(f"{n}/faces.json").json()["faces"]
    top = next(f for f in faces if f["type"] == "plane" and f["normal"][2] > 0.99 and abs(f["center"][2] - 22.4) < 0.01)
    assert not client.get(f"{w}/agent/selection", params={"project": "starter"}).json()["selected"]
    client.post(f"{h}/api/p/starter/selection", json={"note": "rod_foot", "face": top, "point": top["center"], "tags": []})
    sel = client.get(f"{w}/agent/selection", params={"project": "starter"}).json()
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
    assert client.get(f"{w}/agent/selection", params={"project": "mg400_rakis"}).json()["part"] == "L_back_pos"
    notes = {n["name"]: n["kind"] for n in client.get(f"{h}/api/p/mg400_rakis").json()["notes"]}
    assert notes["rakis"] == "assembly"
    assert len(client.get(f"{w}/agent/check", params={"project": "mg400_rakis", "note": "rakis"}).json()["parts"]) == 14


def test_the_agent_sees_a_selection_of_many_things(client, reg):
    w, h = f"/w/{reg['id']}", f"/w/{reg['name']}"
    d = client.get(f"{h}/api/p/starter/n/rod_foot/faces.json").json()
    face = {k: v for k, v in d["faces"][0].items() if k != "tris"}
    edge = {k: v for k, v in d["edges"][0].items() if k not in ("segs", "p")}
    items = [{"kind": "face", **face}, {"kind": "edge", **edge}, {"kind": "vertex", "at": d["points"][0]["at"]}, {"kind": "part", "name": "rod_foot"}]
    client.post(f"{h}/api/p/starter/selection", json={"note": "rod_foot", "mode": "edge", "count": 4, "items": items, "measure": {"length, mm": 45}})
    sel = client.get(f"{w}/agent/selection", params={"project": "starter"}).json()
    assert sel["selected"] and sel["mode"] == "edge" and sel["count"] == 4 and sel["measure"] == {"length, mm": 45}
    assert [i["kind"] for i in sel["items"]] == ["face", "edge", "vertex", "part"]
    assert [i["selector"]["kind"] for i in sel["items"]] == ["planar_face", "edge", "point", "object"]      # how each would be found again
    assert sel["items"][1]["type"] == "line" and sel["items"][2]["at"] == d["points"][0]["at"]
    client.post(f"{h}/api/p/starter/selection", json={})               # cleared in the canvas
    assert not client.get(f"{w}/agent/selection", params={"project": "starter"}).json()["selected"]


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
    assert "pocket" in client.get(f"{w}/agent/read_note", params={"project": "starter", "note": "rod_foot"}).json()["source"]
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
    item = client.get(f"{w}/agent/selection", params={"project": "starter"}).json()["items"][0]
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
    saved = client.get(f"{w}/agent/save", params={"project": "starter", "message": "first"}).json()
    assert saved["saved"] and saved["version"] == 1
    assert client.get(f"{w}/agent/versions", params={"project": "starter"}).json()["versions"][0]["message"] == "first"
    url = client.get(f"{w}/agent/export", params={"project": "starter", "note": "rod_foot", "format": "stl"}).json()["url"]
    stl = client.get(url.split("testserver", 1)[1])
    assert stl.status_code == 200 and "rod_foot.stl" in stl.headers["content-disposition"]
    assert client.get(f"{h}/api/p/starter/n/rod_foot/fingerprint.json").json()["fingerprint"]["solids"] == 1
    assert client.get(f"{h}/api/p/starter").json()["version"] == 1


def test_what_agents_change_is_written_down(app, admin, client, reg):
    client.get(f"/w/{reg['id']}/agent/save", params={"project": "starter", "message": "again"})
    log = admin.get("/api/users").json()["log"]
    assert any(e["type"] == "agent" and e["user"] == "mari" and e["tool"] == "write_note" and e["note"] == "peg" for e in log)
    assert not any(e["type"] == "agent" and e.get("tool") in ("status", "look", "check") for e in log)      # looking is not written down
    assert next(u for u in admin.get("/api/users").json()["users"] if u["username"] == "mari")["lastAgent"]


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
