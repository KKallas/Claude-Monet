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
