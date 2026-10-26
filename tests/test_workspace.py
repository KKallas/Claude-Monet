"""The rules of the house, on a real build: nothing is saved on red, checks are the user's, a red load check
stops the agent, nothing is built on the server (the agent builds and uploads), and there are only so many
workspaces."""
import json

import pytest

from conftest import agent_builds, built_files
from monet.workspace import Problem, Workspaces
from monet.app import ROOT

SOURCE = (ROOT / "notes/starter/rod_foot.py").read_text()


@pytest.fixture(scope="module")
def project(ws):
    return ws.create_project("flow", "starter")


def written(project, name, source):
    """The agent sends a Note, builds it on its own computer and uploads it: the report."""
    r = project.write(name, source, agent=True)
    if r.get("module") or r.get("error") or r["state"] == "built":      # the same source as the build: it is current
        return r
    assert r["state"] in ("stale", "unbuilt")                           # the server built nothing
    return agent_builds(project, name)


def test_report_measures_and_checks(project):
    r = project.report("rod_foot")
    assert r["built"] and r["green"] and r["by"] == "monet"      # the template, built when the image was made
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
    sent = project.write("rod_foot", SOURCE.replace("clearance=0.2", "clearance=0.6"), agent=True)
    assert sent["state"] == "stale" and "monet.py build flow rod_foot" in sent["waiting"]
    waiting = project.save("not built")
    assert not waiting["saved"] and "rod_foot" in waiting["waiting"]
    red = agent_builds(project, "rod_foot")
    assert red["built"] and not red["green"] and red["by"] == "agent"
    assert [c["id"] for c in red["checks"] if not c["ok"]] == ["bore-width"]
    refused = project.save("bigger bore")
    assert not refused["saved"] and "bore-width" in refused["red"]["rod_foot"][0]
    assert len(project.versions()) == 1
    assert written(project, "rod_foot", SOURCE.replace("length=45.0", "length=60.0"))["green"]
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
    with pytest.raises(Problem, match="--export stl"):
        project.export("rod_foot", "stl")                              # the agent built it without
    agent_builds(project, "rod_foot", exports=("stl", "3mf", "step"))
    for fmt in ("stl", "3mf", "step", "glb"):
        assert project.export("rod_foot", fmt).stat().st_size > 500
    with pytest.raises(Problem, match="--version 1 --export stl"):
        project.export("rod_foot", "stl", 1)
    assert agent_builds(project, "rod_foot", exports=("stl",), version=1)["accepted"]       # built from version 1's files
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
    assert written(project, "rod_foot", SOURCE.replace("length=45.0", "length=60.0"))["green"]


def test_load_check_waits_for_the_agent_to_build_the_saved_version(project):
    """The saved Note built again with the kernel the server has now: made by the agent, compared here."""
    f = project.vdir / "0002" / "rod_foot.fingerprint.json"          # as saved, before the test above spoilt it
    fp = json.loads(f.read_text())
    fp["fingerprint"]["volume"] /= 1.2
    f.write_text(json.dumps(fp))
    (project.vdir / "0002" / "out" / "rod_foot" / "result.json").unlink()      # as after a library update: no build of it yet
    (project.out / ".loadcheck.json").unlink()
    lc = project.load_check("rod_foot")
    assert lc["status"] == "waiting" and "monet.py build flow" in lc["message"]
    with pytest.raises(Problem, match="waiting"):
        project.write("rod_foot", SOURCE, agent=True)
    got = agent_builds(project, "rod_foot", version=2)
    assert got["load_check"]["status"] == "green" and project.load_check("rod_foot")["status"] == "green"


def test_errors_are_reports_not_crashes(project):
    assert "syntax error" in project.write("oops", "def build(:\n", agent=True)["error"]
    r = written(project, "oops", "from build123d import *\ndef build():\n    return Box(1, 1, 1) + nothing\n")
    assert not r["green"] and r["state"] == "error" and "NameError" in r["error"] and "line 3" in r["error"]
    assert "must return a build123d shape" in written(project, "oops", "def build():\n    return 42\n")["error"]
    assert not project.save("with a broken Note")["saved"]
    project.delete("oops")
    assert written(project, "helper", "SIZE = 3\n")["module"]
    for bad in ("../x", "Has Space", "1abc", ""):
        with pytest.raises(Problem):
            project.write(bad, "x = 1\n")


def test_a_note_cannot_run_for_ever(project, tmp_path):
    """On the agent's computer: the builder stops it; there is nothing to upload."""
    from monet.build import build
    project.write("forever", "def build():\n    while True:\n        pass\n", agent=True)
    r = build(project.dir, "forever", tmp_path / "forever", timeout=3)
    assert not r["ok"] and "stopped" in r["error"]
    project.delete("forever")


def test_a_workspace_is_made_the_first_time_it_is_asked_for(tmp_path):
    import uuid
    all_ = Workspaces(tmp_path, ROOT / "notes", ROOT / "profiles")
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    assert all_.get(one) is None
    a = all_.of(one, "a")
    assert a.id == one and set(a.projects()) == {"mg400_rakis", "starter"} and all_.get(one).meta["name"] == "a"
    assert {n["state"] for n in a.project("mg400_rakis").status()["notes"] if n["kind"] != "module"} == {"built"}      # open built
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
    assert not back.out.exists() and back.load_check("rod_foot")["status"] == "waiting"    # built again by the agent …
    assert agent_builds(back, "rod_foot", version=1)["load_check"]["status"] == "green"     # … and the same part
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


def test_a_project_is_deleted_whole(ws):
    for name in ("unpacked", "loose", "packed"):
        ws.delete_project(name)
    assert not {"packed", "unpacked", "loose"} & set(ws.projects()) and not [d.name for d in ws.dir.iterdir() if d.name.startswith(".")]
    with pytest.raises(Problem, match="no project 'packed'"):
        ws.delete_project("packed")


def test_an_upload_is_taken_only_if_it_is_a_build_of_these_files(project, monkeypatch):
    """What the agent sends is a claim: taken if it is a build of the files here, with this server's Monet and
    kernel, of the names a build has and in the shapes the server reads; else refused, and nothing changes."""
    import io
    import zipfile
    import monet.workspace as w
    from monet.build import zipped
    files = built_files(project.dir, "rod_foot")
    before = (project.out / "rod_foot" / "result.json").read_bytes()

    def bad(change, why, **kw):
        got = {**files}
        change(got)
        with pytest.raises(Problem, match=why):
            project.accept_build(kw.get("name", "rod_foot"), got)
        assert (project.out / "rod_foot" / "result.json").read_bytes() == before

    def result(edit):
        def go(got):
            r = json.loads(got["result.json"])
            edit(r)
            got["result.json"] = json.dumps(r).encode()
        return go
    bad(result(lambda r: r.update(libs={**r["libs"], "build123d": "0.1"})), "built with")
    bad(result(lambda r: r["deps"].update({"rod_foot.py": "0" * 64})), "rod_foot.py is not as it was")
    bad(result(lambda r: r["deps"].update({"../etc.py": "0" * 64})), "does not say what the build read")
    bad(result(lambda r: r.pop("fingerprint")), "missing what a build has")
    bad(lambda got: got.update({"model.glb": b"not a glb"}), "not a GLB")
    bad(lambda got: got.update({"notes.txt": b"hi"}), "not part of a build")
    bad(lambda got: None, "not of a build of other", name="other")
    with pytest.raises(Problem, match="does not say what the build read"):      # nothing.py is not what it read
        project.accept_build("nothing", {**files, "result.json": files["result.json"].replace(b'"note": "rod_foot"', b'"note": "nothing"')})
    # the source changed after it was built: that build is of other files
    real = project.read("rod_foot")
    project.write("rod_foot", real.replace("length=", "length= ") + "# layout and comments are not the shape\n", agent=True)
    assert project.report("rod_foot")["state"] == "built"
    project.write("rod_foot", real.replace("wall=3.0", "wall=3.5"), agent=True)
    assert project.report("rod_foot")["state"] == "stale"
    with pytest.raises(Problem, match="rod_foot.py is not as it was"):
        project.accept_build("rod_foot", files)
    project.write("rod_foot", real, agent=True)
    assert project.report("rod_foot")["green"]                         # the same files again: the same build is current
    # as a zip: by name, and never a path the zip gives
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../result.json", "{}")
    with pytest.raises(Problem, match="not part of a build"):
        w.build_files(buf.getvalue())
    with pytest.raises(Problem, match="not a zip"):
        w.build_files(b"nope")
    out = project.dir / "zipped"
    out.mkdir()
    (out / "result.json").write_bytes(files["result.json"])
    (out / "stray.py").write_text("x = 1")
    assert set(w.build_files(zipped(out))) == {"result.json"}
    monkeypatch.setattr(w, "MAX_ARCHIVE", 10)
    with pytest.raises(Problem, match="more than"):
        w.build_files(zipped(out))
    import shutil
    shutil.rmtree(out)


def test_a_tag_made_in_the_canvas_is_found_without_a_build(project):
    """Tagging a face changes TAGS only: the server finds the new tag in what the agent built, and runs nothing."""
    glb = project.out / "rod_foot" / "model.glb"
    stamp = glb.stat().st_mtime_ns
    from monet.note import parse
    tags = {**parse(project.read("rod_foot"))["tags"], "top": {"kind": "planar_face", "normal": "+Z", "role": "the top"}}
    r = project.set_tags("rod_foot", tags)
    assert r["green"] and r["tags"]["top"]["resolved"] and r["tags"]["top"]["measure"]["at"] == pytest.approx(22.4)
    assert r["tags"]["rod_bore"]["measure"]["through"] is True          # asked of the mesh, here as on the agent's computer
    assert glb.stat().st_mtime_ns == stamp and [n["state"] for n in project.status()["notes"] if n["name"] == "rod_foot"] == ["built"]
    # one whose build() reads TAGS (a sketch it cuts, say): a change to it changes the shape, and waits for the agent
    reads = "from build123d import *\nTAGS = {}\n\ndef build():\n    return Box(10, 10, 10 + len(TAGS))\n"
    assert written(project, "reads", reads)["green"]
    assert project.set_tags("reads", {"top": {"kind": "planar_face", "normal": "+Z"}})["state"] == "stale"
    project.delete("reads")


def test_an_animation_is_kept_in_the_project_and_checked(project):
    """The timeline's keyframes: frames whole and in the length, the latest key at a frame wins, None takes it away."""
    got = project.set_animation("rod_foot", {"fps": 24, "length": 48, "tracks": {"j1": [[24, 90], [0, 0.5], [24, 45.0]], "j2": []}})
    assert got["rod_foot"] == {"fps": 24, "length": 48, "tracks": {"j1": [[0, 0.5], [24, 45.0]]}}
    assert project.status()["animations"]["rod_foot"]["tracks"]["j1"][1] == [24, 45.0]
    for bad in ({"length": 0}, {"fps": 1.5}, {"length": 48, "tracks": {"j1": [[49, 1]]}}, {"tracks": {"j1": [[1.5, 1]]}}, {"tracks": {"j 1": [[1, 1]]}},
                {"tracks": {"j1": [[1, float("nan")]]}}, {"tracks": {"j1": [[1, True]]}}):
        with pytest.raises(Problem):
            project.set_animation("rod_foot", bad)
    with pytest.raises(Problem):
        project.set_animation("../x", None)
    assert "rod_foot" not in project.set_animation("rod_foot", None)
