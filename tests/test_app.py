"""The doors: the canvas API, the agent's door over plain HTTP (GET and POST) and over MCP."""
import base64
import json

import pytest
from starlette.testclient import TestClient

from monet.app import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with TestClient(create_app(tmp_path_factory.mktemp("storage"), max_users=2)) as c:
        yield c


@pytest.fixture(scope="module")
def reg(client):
    return client.get("/api/register", params={"name": "web llm"}).json()


def test_the_api_describes_itself(client):
    text = client.get("/api").text
    assert "/api/register?name=" in text and "### write_note" in text and "source_b64" in text
    assert client.get("/llms.txt").text == text
    v = client.get("/api/version").json()
    assert v["license"] == "AGPL-3.0-or-later" and v["max"] == 2 and "starter" in v["templates"]


def test_register_gives_everything_needed(client, reg):
    assert len(reg["id"]) == 16 and reg["api"].endswith(f"/w/{reg['id']}/agent") and reg["mcp"].endswith("/mcp")
    assert set(reg["projects"]) == {"mg400_rakis", "starter"}
    assert client.get(f"/w/{reg['id']}").status_code == 200
    assert client.get("/w/AAAAAAAAAAAAAAAA", follow_redirects=False).status_code == 302
    assert client.get("/w/AAAAAAAAAAAAAAAA/api/state").status_code == 404


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
    w = f"/w/{reg['id']}"
    n = f"{w}/api/p/starter/n/rod_foot"
    faces = client.get(f"{n}/faces.json").json()["faces"]
    top = next(f for f in faces if f["type"] == "plane" and f["normal"][2] > 0.99 and abs(f["center"][2] - 22.4) < 0.01)
    assert not client.get(f"{w}/agent/selection", params={"project": "starter"}).json()["selected"]
    client.post(f"{w}/api/p/starter/selection", json={"note": "rod_foot", "face": top, "point": top["center"], "tags": []})
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
    w = f"/w/{reg['id']}"
    described = client.get(f"{w}/api/p/mg400_rakis/n/rakis/faces.json").json()
    assert len(described["parts"]) == 14
    part = next(p for p in described["parts"] if p["name"] == "L_back_pos")
    face = described["faces"][part["faces"][0]]
    client.post(f"{w}/api/p/mg400_rakis/selection", json={"note": "rakis", "face": face, "point": face["center"], "tags": [], "part": part["name"]})
    assert client.get(f"{w}/agent/selection", params={"project": "mg400_rakis"}).json()["part"] == "L_back_pos"
    notes = {n["name"]: n["kind"] for n in client.get(f"{w}/api/p/mg400_rakis").json()["notes"]}
    assert notes["rakis"] == "assembly"
    assert len(client.get(f"{w}/agent/check", params={"project": "mg400_rakis", "note": "rakis"}).json()["parts"]) == 14


def test_the_agent_sees_a_selection_of_many_things(client, reg):
    w = f"/w/{reg['id']}"
    d = client.get(f"{w}/api/p/starter/n/rod_foot/faces.json").json()
    face = {k: v for k, v in d["faces"][0].items() if k != "tris"}
    edge = {k: v for k, v in d["edges"][0].items() if k not in ("segs", "p")}
    items = [{"kind": "face", **face}, {"kind": "edge", **edge}, {"kind": "vertex", "at": d["points"][0]["at"]}, {"kind": "part", "name": "rod_foot"}]
    client.post(f"{w}/api/p/starter/selection", json={"note": "rod_foot", "mode": "edge", "count": 4, "items": items, "measure": {"length, mm": 45}})
    sel = client.get(f"{w}/agent/selection", params={"project": "starter"}).json()
    assert sel["selected"] and sel["mode"] == "edge" and sel["count"] == 4 and sel["measure"] == {"length, mm": 45}
    assert [i["kind"] for i in sel["items"]] == ["face", "edge", "vertex", "part"]
    assert sel["items"][0]["selector"]["kind"] == "planar_face" and "selector" not in sel["items"][1]
    assert sel["items"][1]["type"] == "line" and sel["items"][2]["at"] == d["points"][0]["at"]
    client.post(f"{w}/api/p/starter/selection", json={})               # cleared in the canvas
    assert not client.get(f"{w}/agent/selection", params={"project": "starter"}).json()["selected"]


def test_a_tag_of_several_things_and_a_check_on_what_lies_between(client, reg):
    w = f"/w/{reg['id']}"
    n = f"{w}/api/p/starter/n/rod_foot"
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
    assert mixed["green"] and client.get(n).json()["tag_hits"]["corner_edge"] == {"faces": [], "edges": [0], "points": [0], "parts": []}
    assert client.post(f"{n}/tags", json={"name": "nothing", "items": []}).status_code == 400
    for name in ("height", "corner_edge"):
        client.delete(f"{n}/tags/{name}")
    client.delete(f"{n}/checks/tag-height-distance")


def test_a_sketch_becomes_a_tag_on_its_face(client, reg):
    w = f"/w/{reg['id']}"
    n = f"{w}/api/p/starter/n/rod_foot"
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
    w = f"/w/{reg['id']}"
    n = f"{w}/api/p/starter/n/rod_foot"
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
    for name in ("label", "label_plane"):
        client.delete(f"{n}/tags/{name}")


def test_what_a_part_is_made_of(client, reg):
    w = f"/w/{reg['id']}"
    looks = client.put(f"{w}/api/p/starter/looks", json={"names": ["rod_foot"], "material": "aluminium", "color": "#AA3311"}).json()["looks"]
    assert looks == {"rod_foot": {"material": "aluminium", "color": "#aa3311"}}
    assert client.put(f"{w}/api/p/starter/looks", json={"names": ["rod_foot"], "color": None}).json()["looks"] == {"rod_foot": {"material": "aluminium"}}
    assert client.get(f"{w}/api/p/starter").json()["looks"] == {"rod_foot": {"material": "aluminium"}}
    assert client.put(f"{w}/api/p/starter/looks", json={"names": ["rod_foot"], "material": "gold"}).status_code == 400
    assert client.put(f"{w}/api/p/starter/looks", json={"names": ["rod_foot"], "color": "red"}).status_code == 400
    # the sample comes with its pipes in aluminium
    assert client.get(f"{w}/api/p/mg400_rakis").json()["looks"]["pipe_long_pos"] == {"material": "aluminium"}


def test_checks_are_the_persons_to_change(client, reg):
    n = f"/w/{reg['id']}/api/p/starter/n/rod_foot"
    assert client.post(f"{n}/checks", json={"what": "size_x", "max": 40, "why": "fits the drawer"}).json()["report"]["green"] is False
    assert client.put(f"{n}/checks/size-x", json={"what": "size_x", "max": 50}).json()["report"]["green"]
    assert client.delete(f"{n}/checks/size-x").json()["report"]["green"]
    assert client.delete(f"{n}/checks/size-x").status_code == 404
    # the agent's door has no such tools
    assert set(client.get(f"/w/{reg['id']}/agent").json()["tools"]) & {"delete_check", "put_check", "acknowledge", "delete_note"} == set()


def test_save_versions_export_over_http(client, reg):
    w = f"/w/{reg['id']}"
    saved = client.get(f"{w}/agent/save", params={"project": "starter", "message": "first"}).json()
    assert saved["saved"] and saved["version"] == 1
    assert client.get(f"{w}/agent/versions", params={"project": "starter"}).json()["versions"][0]["message"] == "first"
    url = client.get(f"{w}/agent/export", params={"project": "starter", "note": "rod_foot", "format": "stl"}).json()["url"]
    stl = client.get(url.split("testserver", 1)[1])
    assert stl.status_code == 200 and "rod_foot.stl" in stl.headers["content-disposition"]
    assert client.get(f"{w}/api/p/starter/n/rod_foot/fingerprint.json").json()["fingerprint"]["solids"] == 1
    assert client.get(f"{w}/api/p/starter").json()["version"] == 1


def test_mcp_door(client, reg):
    def rpc(method, params, wid=reg["id"]):
        return client.post(f"/w/{wid}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
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
    assert rpc("tools/list", {}, wid="AAAAAAAAAAAAAAAA").status_code == 404


def test_the_instance_fills_up(client, reg):
    assert client.post("/api/start", json={"name": "second"}).status_code == 200
    full = client.post("/api/start", json={})
    assert full.status_code == 503 and "all 2 workspaces" in full.json()["error"]
    by_get = client.get("/api/register")
    assert by_get.status_code == 200 and by_get.json()["status"] == 503


def test_skill_zip(client):
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(client.get("/skill.zip").content)).namelist()
    assert "monet/SKILL.md" in names and "monet/scripts/monet.py" in names and "monet/references/tags-and-checks.md" in names
