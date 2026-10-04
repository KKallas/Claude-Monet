"""The rules of the house, on a real build: nothing is saved on red, checks are the user's, a red load check
stops the agent, and there are only so many workspaces."""
import json

import pytest

from monet.workspace import Problem, Workspaces
from monet.app import ROOT

SOURCE = (ROOT / "notes/starter/rod_foot.py").read_text()


@pytest.fixture(scope="module")
def project(ws):
    return ws.create_project("flow", "starter")


def test_report_measures_and_checks(project):
    r = project.report("rod_foot")
    assert r["built"] and r["green"]
    assert r["measure"]["size_x"] == 45.0 and r["measure"]["volume_cm3"] == pytest.approx(10.476)
    assert r["tags"]["rod_bore"]["measure"] == {"width": 16.4, "height": 16.4, "at": [0.0, 11.2], "length": 45.0, "through": True}
    assert {c["id"] for c in r["checks"]} >= {"tag-rod_bore", "tag-base", "bore-width", "bore-through", "bed"}


def test_agent_adds_checks_but_cannot_change_them(project):
    added = project.add_check("rod_foot", {"what": "size_x", "max": 100, "why": "fits the drawer"}, by="agent")
    assert added["by"] == "agent"
    with pytest.raises(Problem, match="an agent can add one but not change one"):
        project.add_check("rod_foot", {"id": "bore-width", "what": "tag.rod_bore.width", "min": 1, "max": 99}, by="agent")
    assert [c for c in project.checks("rod_foot") if c["id"] == "bore-width"][0]["max"] == 16.4


def test_save_then_nothing_is_saved_on_red(project):
    first = project.save("first")
    assert first == {"saved": True, "version": 1, "changed": ["rod_foot"], "message": "first"}
    assert project.save("again")["unchanged"]                       # asked twice, saved once
    red = project.write("rod_foot", SOURCE.replace("clearance=0.2", "clearance=0.6"), agent=True)
    assert red["built"] and not red["green"]
    assert [c["id"] for c in red["checks"] if not c["ok"]] == ["bore-width"]
    refused = project.save("bigger bore")
    assert not refused["saved"] and "bore-width" in refused["red"]["rod_foot"][0]
    assert len(project.versions()) == 1
    assert project.write("rod_foot", SOURCE.replace("length=45.0", "length=60.0"), agent=True)["green"]
    second = project.save("longer", commit="abc1234")
    assert second["saved"] and second["version"] == 2 and project.versions()[-1]["commit"] == "abc1234"


def test_a_version_keeps_the_glb_and_fingerprint_next_to_the_note(project):
    v = project.vdir / "0002"
    assert (v / "rod_foot.py").exists() and (v / "rod_foot.checks.json").exists()
    assert (v / "rod_foot.glb").stat().st_size > 500
    fp = json.loads((v / "rod_foot.fingerprint.json").read_text())
    assert fp["fingerprint"]["volume"] == pytest.approx(13968.0) and fp["tags"]["rod_bore"]["resolved"] and fp["libs"]["build123d"]


def test_diff_says_what_changed_in_words(project):
    d = project.diff("rod_foot", 1, 2)
    assert not d["same"] and d["added"]["max_mm"] == pytest.approx(7.5, abs=0.2)
    assert {"tag": "rod_bore", "change": "length: 45.0 -> 60.0 (+15.000)"} in d["tags"]
    assert project.diff("rod_foot", 2, "draft")["same"]
    assert project.diff_model("rod_foot", 1, 2, "a").stat().st_size > 500


def test_exports_of_the_draft_and_of_an_old_version(project):
    for fmt in ("stl", "3mf", "step", "glb"):
        assert project.export("rod_foot", fmt).stat().st_size > 500
    assert project.export("rod_foot", "stl", 1).stat().st_size > 500
    with pytest.raises(Problem):
        project.export("rod_foot", "dxf")


def test_load_check_red_stops_the_agent_until_the_user_has_looked(project):
    assert project.load_check("rod_foot")["status"] == "green"
    # the saved fingerprint no longer matches what the saved Note builds: a library changed, or someone edited the files
    f = project.vdir / "0002" / "rod_foot.fingerprint.json"
    fp = json.loads(f.read_text())
    fp["fingerprint"]["volume"] *= 1.2
    f.write_text(json.dumps(fp))
    (project.out / ".loadcheck.json").unlink()
    lc = project.load_check("rod_foot")
    assert lc["status"] == "red" and lc["changes"][0]["what"] == "volume"
    with pytest.raises(Problem, match="load check is RED"):
        project.write("rod_foot", SOURCE, agent=True)
    assert "length=60.0" in project.read("rod_foot")                  # nothing was written
    project.acknowledge("rod_foot")                                   # the user's door
    assert project.write("rod_foot", SOURCE.replace("length=45.0", "length=60.0"), agent=True)["green"]


def test_errors_are_reports_not_crashes(project):
    assert "syntax error" in project.write("oops", "def build(:\n", agent=True)["error"]
    r = project.write("oops", "from build123d import *\ndef build():\n    return Box(1, 1, 1) + nothing\n", agent=True)
    assert not r["green"] and "NameError" in r["error"] and "line 3" in r["error"]
    assert "must return a build123d shape" in project.write("oops", "def build():\n    return 42\n", agent=True)["error"]
    assert not project.save("with a broken Note")["saved"]
    project.delete("oops")
    assert project.write("helper", "SIZE = 3\n", agent=True)["module"]
    for bad in ("../x", "Has Space", "1abc", ""):
        with pytest.raises(Problem):
            project.write(bad, "x = 1\n")


def test_a_note_cannot_run_for_ever(project, monkeypatch):
    monkeypatch.setattr("monet.workspace.BUILD_TIMEOUT", 3)
    r = project.write("forever", "def build():\n    while True:\n        pass\n", agent=True)
    assert not r["green"] and ("stopped" in r["error"] or "died" in r["error"])
    project.delete("forever")


def test_max_users(tmp_path):
    all_ = Workspaces(tmp_path, ROOT / "notes", ROOT / "profiles", max_users=2)
    a, b = all_.create("a"), all_.create("b")
    assert a.id != b.id and len(a.id) == 16 and set(a.projects()) == {"mg400_rakis", "starter"}
    with pytest.raises(Problem, match="all 2 workspaces"):
        all_.create("c")
    assert all_.get(a.id).meta["name"] == "a" and all_.get("nope") is None and all_.get("../" + a.id) is None
    assert not (a.dir / "mg400_rakis" / "_verify.py").exists()        # the port's own script is not part of the template
