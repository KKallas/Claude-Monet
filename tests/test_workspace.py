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


def test_a_workspace_is_made_the_first_time_it_is_asked_for(tmp_path):
    import uuid
    all_ = Workspaces(tmp_path, ROOT / "notes", ROOT / "profiles")
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    assert all_.get(one) is None
    a = all_.of(one, "a")
    assert a.id == one and set(a.projects()) == {"mg400_rakis", "starter"} and all_.get(one).meta["name"] == "a"
    a.project("starter").write("mine", "X = 1\n")
    assert "mine" in all_.of(one).project("starter").files()             # asked for again, it is the same one
    assert "mine" not in all_.of(two, "b").project("starter").files()
    for bad in ("nope", "../" + one, ""):
        assert all_.get(bad) is None
        with pytest.raises(Problem):
            all_.of(bad)
    assert not (a.dir / "mg400_rakis" / "_verify.py").exists()        # the port's own script is not part of the template


def test_a_project_goes_out_and_comes_back_as_an_archive(ws, monkeypatch):
    """The Notes, their checks, the settings and the saved versions travel; the builds are made again where they land."""
    import io
    import zipfile
    import monet.workspace as w

    def zipped(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, text in files.items():
                z.writestr(name, text)
        return buf.getvalue()
    p = ws.create_project("packed", "starter")
    assert p.save("first")["saved"]
    data = p.archive()
    held = {n: zipfile.ZipFile(io.BytesIO(data)).read(n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()}
    assert {"packed/rod_foot.py", "packed/rod_foot.checks.json", "packed/monet.json", "packed/versions/0001/meta.json",
            "packed/versions/0001/rod_foot.glb", "packed/versions/0001/rod_foot.fingerprint.json"} <= set(held)
    assert not any("/out/" in n for n in held)
    back, left_out = ws.import_project("unpacked", data)
    assert left_out == 0 and back.files() == p.files() and back.versions() == p.versions() and back.checks("rod_foot") == p.checks("rod_foot")
    assert not back.out.exists() and back.load_check("rod_foot")["status"] == "green"      # rebuilt here, and the same part
    assert {"name": "unpacked", "notes": 1, "version": 1, "saved": p.head()["at"]} in ws.listing()
    with pytest.raises(Problem, match="already a project"):
        ws.import_project("unpacked", data)
    # a zip does not say where its files go: what is not of a project is left out, wherever it points
    loose, left_out = ws.import_project("loose", zipped({"rod_foot.py": SOURCE, "../escape.py": "x = 1", "/tmp/abs.py": "x = 1", "sub/deep.py": "x = 1",
                                                         "out/rod_foot/result.json": "{}", ".env": "SECRET=1", "__MACOSX/._rod_foot.py": "x"}))
    assert left_out == 5 and sorted(f.name for f in loose.dir.rglob("*")) == ["monet.json", "rod_foot.py"]
    assert not (ws.dir / "escape.py").exists() and not (ws.dir.parent / "escape.py").exists()
    for bad, why in ((b"not a zip", "not a zip"), (zipped({"README.md": "hello"}), "nothing of a project"), (zipped({"monet.json": "[]"}), "not what Monet writes"),
                     (zipped({k: v for k, v in held.items() if not k.endswith(".glb")}), "version 1 in that archive is not whole"),
                     (zipped({**held, "packed/versions/0002/rod_foot.py": SOURCE}), "version 2 in that archive is not whole")):
        with pytest.raises(Problem, match=why):
            ws.import_project("bad", bad)
    monkeypatch.setattr(w, "MAX_ARCHIVE", 1000)
    with pytest.raises(Problem, match="more than a project may be"):
        ws.import_project("bad", data)
    with pytest.raises(Problem, match="lowercase"):
        ws.import_project("../bad", data)
    assert "bad" not in ws.projects() and not [d.name for d in ws.dir.iterdir() if d.name.startswith(".")]      # nothing half-made is left


def test_a_project_is_deleted_whole_but_not_while_it_builds(ws):
    import time
    import monet.workspace as w
    for name in ("unpacked", "loose"):
        ws.delete_project(name)
    p = ws.project("packed")
    w._running[(str(p.dir), "rod_foot")] = time.time()
    with pytest.raises(Problem, match="being built"):
        ws.delete_project("packed")
    w._running.clear()
    ws.delete_project("packed")
    assert not {"packed", "unpacked", "loose"} & set(ws.projects()) and not [d.name for d in ws.dir.iterdir() if d.name.startswith(".")]
    with pytest.raises(Problem, match="no project 'packed'"):
        ws.delete_project("packed")


def test_notes_can_be_built_by_a_runner_elsewhere(project, monkeypatch):
    """Online the web app does not run Notes: it asks the runner (monet/buildd.py), which has the working files only."""
    from starlette.testclient import TestClient
    import monet.buildd as buildd
    import monet.workspace as w
    monkeypatch.setattr(buildd, "STORAGE", project.ws.all.storage)
    runner = TestClient(buildd.app)

    class Wire:      # httpx, as far as run_build uses it, going to the runner in this process
        HTTPError = OSError
        @staticmethod
        def post(url, json, timeout):
            return runner.post(url.replace("http://runner", ""), json=json)
    monkeypatch.setattr(w, "RUNNER_URL", "http://runner")
    monkeypatch.setitem(__import__("sys").modules, "httpx", Wire)
    r = w.run_build(project.dir, "rod_foot", project.out / "rod_foot")
    assert r["ok"] and r["fingerprint"]["solids"] == 1
    # the runner builds Notes of the storage, and nothing else
    assert runner.post("/build", json={"dir": "/etc", "note": "passwd", "out": "/tmp/x"}).status_code == 400
    assert runner.post("/build", json={"dir": str(project.dir), "note": "../x", "out": str(project.out / "x")}).status_code == 400
    assert runner.post("/build", json={"dir": str(project.dir), "note": "rod_foot", "out": "/tmp/elsewhere"}).status_code == 400


def test_a_build_is_timed_and_seen_while_it_runs(project, monkeypatch):
    """What the canvas makes its progress bar of: how long the last good build took, and what is building now."""
    import threading
    import monet.workspace as w
    project.write("timed", SOURCE)
    took = project.took()["timed"]
    assert took["seconds"] >= took["kernel"] >= took["build"] >= 0 and took["at"].endswith("Z")
    assert project.report("timed")["took"] == took and project.report("timed")["seconds"] == took["seconds"]
    row = [n for n in project.status()["notes"] if n["name"] == "timed"][0]
    assert row["seconds"] == took["seconds"] and project.status()["building"] == []
    # while it builds, it is listed with what to expect; a build that fails leaves the last good time as it was
    real, going, seen = w.run_build, threading.Event(), []

    def slow(*a, **k):
        going.set()
        seen.append(project.building())
        return real(*a, **k)
    monkeypatch.setattr(w, "run_build", slow)
    assert not project.write("timed", SOURCE + "\nraise ValueError('no')\n")["built"]
    assert [(b["note"], b["expect"]) for b in seen[0]] == [("timed", took["seconds"])] and project.building() == []
    assert project.took()["timed"] == took
    # a build kept from before times were: what it said of itself is the estimate
    (project.out / ".times.json").unlink()
    kept = project.cached("rod_foot")["seconds"]
    assert [n["seconds"] for n in project.status()["notes"] if n["name"] == "rod_foot"] == [kept] and project.expected("nothing") is None
    project.delete("timed")


def test_a_build_starts_warm_or_cold_and_is_the_same_build(project, monkeypatch):
    """Builds are forked from a process that has the kernel loaded (monet/warm.py); started from nothing they are
    the same build, only later."""
    import monet.workspace as w
    warm = w.run_build_here(project.dir, "rod_foot", project.out / ".warm")
    monkeypatch.setenv("MONET_COLD", "1")
    cold = w.run_build_here(project.dir, "rod_foot", project.out / ".cold")
    assert warm["ok"] and cold["ok"] and "wall" in warm and "wall" not in cold
    assert warm["fingerprint"] == cold["fingerprint"] and warm["tags"] == cold["tags"] and warm["libs"] == cold["libs"]
    assert (project.out / ".warm" / "model.glb").read_bytes() == (project.out / ".cold" / "model.glb").read_bytes()
