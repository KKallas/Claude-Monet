"""What the living-room lamp asked for (issues #2 to #7), on a small lamp of its own: materials and mass, keep-outs and
named poses, the torque gravity asks of a joint, a bill of materials, parts printed in pieces, an animation."""
import io
import json
import math
import zipfile

import pytest

from conftest import agent_builds
from monet import agent, joints
from monet.workspace import Problem

LEAF = '''"""A leaf of the lamp: a plate that swings open in front of the projector.

Rules
- PETG: it sits by the projector's exhaust
"""
from build123d import *

PARAMS = dict(w=98.0, t=6.0, h=80.0)
MATERIAL = "petg"
TAGS = {}


def build(p=PARAMS):
    return Box(p["w"], p["t"], p["h"], align=(Align.MIN, Align.MIN, Align.MIN))
'''

VERTEBRA = '''"""A vertebra of the lamp's spine: a disc."""
from build123d import *

PARAMS = dict(r=20.0, h=10.0)
TAGS = {}


def build(p=PARAMS):
    return Cylinder(p["r"], p["h"], align=(Align.CENTER, Align.CENTER, Align.MIN))
'''

STRIP = '''"""A strip of the 480 mm sphere: 457 mm tall, printed in two pieces with dowels."""
import math

from build123d import *
from monet.split import split

PARAMS = dict(r=240.0, t=8.0, h=457.0, angle=20.0)
TAGS = {}


def build(p=PARAMS):
    a = math.radians(p["angle"] / 2)
    with BuildPart() as wedge:
        with BuildSketch(Plane.XY.offset(-p["h"] / 2)):
            Polygon((0, 0), (2 * p["r"] * math.cos(a), -2 * p["r"] * math.sin(a)), (2 * p["r"] * math.cos(a), 2 * p["r"] * math.sin(a)), align=None)
        extrude(amount=p["h"])
    return (Sphere(p["r"]) - Sphere(p["r"] - p["t"])) & wedge.part


def pieces(p=PARAMS):
    return split(build(p), planes=[Plane.XY], dowel=(4, 12))
'''

LAMP = '''"""The lamp: a projector between two leaves that open, on an aluminium frame.

Rules
- with the leaves open, the beam passes clear
"""
from build123d import *
import leaf
import vertebra

PARAMS = dict(drop=3)
TAGS = {}
GROUND = "base"
JOINTS = {
    "leaf_left": {"kind": "revolute", "moves": "leaf_left", "on": "base", "axis": {"origin": [-100, 153, 0], "dir": "Z"}, "range": [0, 90]},
    "leaf_right": {"kind": "revolute", "moves": "leaf_right", "on": "base", "axis": {"origin": [100, 153, 0], "dir": "Z"}, "range": [-90, 0]},
    "arm": {"kind": "revolute", "moves": "arm", "on": "base", "axis": {"origin": [0, 0, 300], "dir": "X"}, "range": [0, 90]},
}
POSES = {"projecting": {"leaf_left": 90, "leaf_right": -90}, "ajar": {"leaf_left": 20, "leaf_right": -20}}
KEEPOUT = {"keepout_beam": {"on": "projector"}}
MATERIALS = {"rail_*|post_*|arm": "aluminium", "projector": None}
MASS = {"projector": 2700}
DRIVES = {"arm": {"servo": "MG996R", "torque_nmm": 900}}
BOM = {
    "leaf_*": {"print": "leaf"},
    "vertebra_*": {"print": "vertebra"},
    "rail_*|post_*": {"stock": "alu_tube_16x1.5", "material": "aluminium"},
    "arm": {"stock": "alu_bar_10x10", "material": "aluminium"},
    "projector": {"buy": "Epson EB-X49"},
    "_extra": [{"buy": "M5x30 bolt + nut", "qty": 40}],
}


def tube(length):
    return Cylinder(8, length) - Cylinder(6.5, length)


def build(p=PARAMS):
    kids = {
        "base": Pos(0, 0, -5) * Box(400, 200, 10),
        "projector": Pos(0, 0, 30) * Box(100, 100, 60),
        "keepout_beam": Pos(0, 150, 30) * Box(60, 200, 40),
        "leaf_left": Pos(-100, 150, 0) * leaf.build(),
        "leaf_right": Pos(2, 150, 0) * leaf.build(),
        "arm": Pos(0, 100, 300) * Box(10, 200, 10),
    }
    for i, y in enumerate((-80, 80)):
        kids[f"rail_{i + 1}"] = Pos(0, y, -20) * Rot(0, 90, 0) * tube(324)
    for i, (x, y) in enumerate([(-150, -60), (150, -60), (-150, 60), (150, 60)]):
        kids[f"post_{i + 1}"] = Pos(x, y, -12 - 92.5 / 2) * tube(92.5)
    for k in range(p["drop"]):
        kids[f"vertebra_{k + 1}"] = Pos(-170, -80, 100 + 12 * k) * vertebra.build()
    for name, shape in kids.items():
        shape.label = name
    return Compound(children=list(kids.values()), label="lamp")
'''


@pytest.fixture(scope="module")
def lamp(ws):
    p = ws.create_project("lamp", "", printer="bambu_x1c", material="pla")
    for name, source in (("leaf", LEAF), ("vertebra", VERTEBRA), ("strip", STRIP), ("lamp", LAMP)):
        p.write(name, source, agent=True)
    for name in ("leaf", "vertebra", "strip", "lamp"):
        got = agent_builds(p, name, exports=("3mf", "stl") if name in ("strip", "lamp") else ())
        assert got["built"], got.get("error")
    return p


def caller(ws):
    return agent.Caller(ws, "http://monet.test/w/KEY", "http://monet.test/w/someone")


# ---- #2 materials --------------------------------------------------------------------------------------------

def test_a_note_says_what_it_is_made_of_and_weighs(lamp):
    r = lamp.report("leaf")
    assert r["material"]["name"] == "petg" and r["material"]["max_temp_c"] == 70 and r["material"]["density"] == 1.27
    assert r["measure"]["mass_g"] == pytest.approx(98 * 6 * 80 / 1000 * 1.27, abs=1e-3)
    v = lamp.report("vertebra")       # no MATERIAL: the project's
    assert v["material"]["name"] == "pla" and v["material"]["how"] == "project"


def test_the_project_material_and_printer_are_chosen(lamp, ws):
    got = agent.call("status", caller(ws), {"project": "lamp"})[0]
    assert got["printer_profile"]["bed"] == [256, 256, 256] and got["material_profile"]["name"] == "PLA"
    assert "petg" in agent.call("status", caller(ws), {})[0]["materials"]
    changed = agent.call("set_profile", caller(ws), {"project": "lamp", "material": "asa"})[0]
    assert changed["material"] == "asa" and changed["material_profile"]["max_temp_c"] == 90
    assert lamp.report("vertebra")["material"]["name"] == "asa"
    with pytest.raises(Problem, match="no material 'unobtainium'"):
        lamp.set_profile(None, "unobtainium")
    lamp.set_profile(None, "pla")
    with pytest.raises(Problem, match="no printer"):
        ws.create_project("nowhere", "", printer="prusa_xl")
    assert ws.create_project("lamp_petg", "", material="petg").settings["material"] == "petg"


def test_an_assembly_weighs_its_parts_each_of_its_own_material(lamp):
    r = lamp.report("lamp")
    parts = {q["name"]: q for q in r["parts"]}
    assert parts["projector"]["material"] is None and parts["projector"]["mass_g"] == 2700        # bought: MASS
    assert parts["rail_1"]["material"] == "aluminium"
    tube = math.pi * (8 ** 2 - 6.5 ** 2) * 324 / 1000
    assert parts["rail_1"]["mass_g"] == pytest.approx(tube * 2.70, rel=2e-3)
    assert parts["leaf_left"]["material"] == "petg"                       # the BOM says it is the leaf Note: its MATERIAL
    assert parts["keepout_beam"] == {**parts["keepout_beam"], "keepout": True} and "mass_g" not in parts["keepout_beam"]
    assert r["mass"]["mass_g"] == pytest.approx(sum(q.get("mass_g") or 0 for q in r["parts"]), abs=0.01)
    lamp.add_check("lamp", {"id": "heavy", "what": "mass_g", "max": 10000, "why": "one person lifts it"}, by="agent")
    lamp.add_check("lamp", {"id": "projector", "what": "part.projector.mass_g", "equals": 2700}, by="agent")
    assert all(c["ok"] for c in lamp.report("lamp")["checks"] if c["id"] in ("heavy", "projector"))


def test_a_wrong_material_is_red(lamp):
    source = lamp.read("vertebra")
    try:
        r = lamp.write("vertebra", source.replace('TAGS = {}', 'TAGS = {}\nMATERIAL = "cheese"'), agent=True)
        assert r["state"] == "built"           # a material is no shape: still built
        bad = [c for c in r["checks"] if not c["ok"]]
        assert bad and "MATERIAL 'cheese'" in bad[0]["why"]
    finally:
        lamp.write("vertebra", source, agent=True)


# ---- #4 keep-outs and named poses ------------------------------------------------------------------------------

def test_a_keepout_is_no_material(lamp):
    r = lamp.result("lamp")
    assert r["keepouts"] == ["keepout_beam"]
    assert r["fingerprint"]["bbox"][4] == pytest.approx(200.0)       # the arm; the beam reaches y = 250: it is not in the part
    assert r["fingerprint"]["solids"] == len(r["parts"]) - 1
    mo = r["motion"]
    # as built the closed leaves stand in the beam: neither interference nor a clash
    assert not any("keepout_beam" in pair for pair in mo["interference"]["pairs"])
    assert mo["sweeps"]["leaf_left"]["clash_mm3"] == 0 and mo["sweeps"]["leaf_right"]["stop_min"] is None


def test_a_named_pose_and_what_it_keeps_clear(lamp, ws):
    mo = lamp.result("lamp")["motion"]
    open_ = mo["poses"]["projecting"]
    assert open_["resolved"] and open_["clear"]["keepout_beam"] == 0 and open_["interference_mm3"] == 0
    ajar = mo["poses"]["ajar"]
    assert ajar["clear"]["keepout_beam"] > 1000 and {n for n, _ in ajar["keepout_hits"]["keepout_beam"]} == {"leaf_left", "leaf_right"}
    lamp.add_check("lamp", {"id": "beam", "what": "pose.projecting.clear.keepout_beam", "max": 1, "why": "with the leaves open, the beam passes clear"}, by="agent")
    lamp.add_check("lamp", {"id": "ajar", "what": "pose.ajar.clear.keepout_beam", "max": 1}, by="agent")
    rows = {c["id"]: c for c in lamp.report("lamp")["checks"]}
    assert rows["beam"]["ok"] and not rows["ajar"]["ok"]
    lamp.put_check("lamp", "ajar", None)
    # pose() takes a pose by its name
    got, png = agent.call("pose", caller(ws), {"project": "lamp", "note": "lamp", "values": "projecting"})
    assert got["values"]["leaf_left"] == 90 and got["clashes"] == [] and png[:4] == b"\x89PNG"
    with pytest.raises(Problem, match="no pose 'wide'"):
        agent.call("pose", caller(ws), {"project": "lamp", "note": "lamp", "values": "wide"})


def test_a_pose_that_cannot_be_is_red(lamp):
    source = lamp.read("lamp")
    try:
        r = lamp.write("lamp", source.replace('"ajar": {"leaf_left": 20', '"ajar": {"leaf_left": 200'), agent=True)
        assert r["state"] == "built"           # poses are worked out from the build: no build again
        bad = {c["id"]: c for c in r["checks"] if not c["ok"]}
        assert "outside its range" in bad["pose-ajar"]["why"]
    finally:
        lamp.write("lamp", source, agent=True)


def test_exports_leave_the_keepout_out(lamp):
    import trimesh
    mesh = trimesh.load(io.BytesIO(lamp.export("lamp", "stl").read_bytes()), file_type="stl")
    assert mesh.bounds[1][1] == pytest.approx(200.0, abs=0.05)


# ---- #7 torque -------------------------------------------------------------------------------------------------

def test_what_gravity_asks_of_a_joint(lamp):
    r = lamp.report("lamp")
    t = r["motion"]["torque"]
    m = 10 * 200 * 10 / 1000 * 2.70 / 1000          # kg of the aluminium arm
    assert t["arm"]["unit"] == "N·mm" and t["arm"]["at"] == 0
    assert t["arm"]["max"] == pytest.approx(m * 9.80665 * 100, rel=1e-3)
    assert abs(t["arm"]["samples"][-1][1]) < 0.01                                       # straight up: nothing
    assert t["leaf_left"]["max"] < 1e-6                                                 # turning about a vertical axis
    assert t["arm"]["margin"] == pytest.approx(900 / t["arm"]["max"], rel=1e-3)
    lamp.add_check("lamp", {"id": "servo", "what": "joint.arm.torque_max_nmm", "max": 100}, by="agent")
    lamp.add_check("lamp", {"id": "too-weak", "what": "joint.arm.torque_max_nmm", "max": 10}, by="agent")
    rows = {c["id"]: c for c in lamp.report("lamp")["checks"]}
    assert rows["servo"]["ok"] and not rows["too-weak"]["ok"]
    lamp.put_check("lamp", "too-weak", None)


def test_torque_of_a_horizontal_arm_and_of_what_follows_it():
    spec = {"arm": {"kind": "revolute", "moves": "arm", "on": "base", "axis": {"origin": [0, 0, 0], "dir": "X"}, "range": [0, 90]},
            "horn": {"kind": "revolute", "moves": "horn", "on": "base", "axis": {"origin": [50, 0, 0], "dir": "X"}, "follows": {"arm": 2}}}
    m = joints.resolve(spec, "base", ["base", "arm", "horn"])
    t = joints.torque(m, {"base": 1000, "arm": 100, "horn": 10}, {"base": [0, 0, -10], "arm": [0, 100, 0], "horn": [50, 20, 0]})
    g = 9.80665
    # at 0 the arm (100 g, 100 mm out) and the horn (10 g, 20 mm out, turning twice as far) both hang on the drive
    assert t["arm"]["samples"][0] == [0.0, pytest.approx(0.1 * g * 100 + 2 * 0.01 * g * 20, rel=1e-4)]
    assert t["horn"]["own"] and t["horn"]["at_driver"]["arm"] == pytest.approx(2 * t["horn"]["max"])
    alone = joints.torque(joints.resolve({"arm": spec["arm"]}, "base", ["base", "arm"]), {"base": 1000, "arm": 100}, {"base": [0, 0, -10], "arm": [0, 100, 0]})
    assert alone["arm"]["max"] == pytest.approx(0.1 * g * 100, rel=1e-4) and abs(alone["arm"]["samples"][-1][1]) < 1e-6


# ---- #5 bill of materials --------------------------------------------------------------------------------------

def test_the_bill_of_materials(lamp, ws):
    b = agent.call("bom", caller(ws), {"project": "lamp", "note": "lamp"})[0]
    assert b["printed"]["leaf"]["qty"] == 2 and b["printed"]["leaf"]["material"] == "petg" and b["printed"]["leaf"]["fits_bed"]
    assert b["printed"]["vertebra"]["qty"] == 3
    cuts = {c["length_mm"]: c["qty"] for c in b["stock"]["alu_tube_16x1.5"]["cuts"]}
    assert cuts == {324.0: 2, 92.5: 4} and b["stock"]["alu_tube_16x1.5"]["total_mm"] == 1018.0
    assert b["stock"]["alu_bar_10x10"]["cuts"][0]["length_mm"] == 200.0
    assert b["bought"]["Epson EB-X49"]["qty"] == 1 and b["bought"]["M5x30 bolt + nut"]["qty"] == 40
    assert b["unlisted"] == ["base"] and "keepout_beam" not in json.dumps(b)
    assert b["csv"].startswith("http://monet.test/w/KEY/file/p/lamp/n/lamp/bom.csv")
    rows = lamp.report("lamp")
    assert rows["bom"]["unlisted"] == 1
    from monet import bom as boms
    text = boms.as_csv(lamp.bom("lamp"))
    assert "cut,alu_tube_16x1.5,2,324.0" in text and "print,leaf,2" in text


def test_more_vertebrae_are_more_in_the_list(lamp):
    source = lamp.read("lamp")
    try:
        lamp.write("lamp", source.replace("drop=3", "drop=5"), agent=True)
        agent_builds(lamp, "lamp")
        assert lamp.bom("lamp")["printed"]["vertebra"]["qty"] == 5
    finally:
        lamp.write("lamp", source, agent=True)
        agent_builds(lamp, "lamp")


# ---- #6 printed in pieces --------------------------------------------------------------------------------------

def test_a_part_bigger_than_the_bed_printed_in_pieces(lamp):
    lamp.add_check("strip", {"id": "bed", "what": "fits_bed"}, by="agent")
    lamp.add_check("strip", {"id": "one", "what": "solids", "equals": 1}, by="agent")
    r = lamp.report("strip")
    assert r["measure"]["size_z"] == pytest.approx(457.0)            # the whole, as the assembly has it
    assert [q["size"][2] for q in r["pieces"]] == [228.5, 228.5]     # each piece on its cut face
    rows = {c["id"]: c for c in r["checks"]}
    assert rows["bed"]["ok"] and rows["one"]["ok"] and "each of 2 pieces" in rows["bed"]["expect"]
    whole = lamp.result("strip")["fingerprint"]["volume"]
    dowels = 4 * math.pi * (2 + 0.15) ** 2 * (6 + 0.5)              # 2 holes a side, each side of the cut
    assert sum(q["volume"] for q in lamp.result("strip")["pieces"]) == pytest.approx(whole - dowels, rel=1e-6)
    with zipfile.ZipFile(lamp.export("strip", "3mf")) as z:
        model = z.read("3D/3dmodel.model").decode()
    assert model.count("<item ") == 2                                  # two objects on the plate


def test_dowel_holes_line_up_across_the_cut():
    from build123d import Box, Plane
    from monet.split import split
    pieces = split(Box(40, 30, 400), dowel=(4, 12))                 # no planes: across the long side, to fit the bed
    assert len(pieces) == 2 and all(max(q.shape.bounding_box().size) <= 256 for q in pieces)
    a, b = pieces
    assert len(a.dowels) == 2 and a.dowels == b.dowels
    for q in pieces:     # put back where it was, each piece has a hole round each of those points: 2.15 mm to its wall
        back = q.place * q.shape
        assert all(back.distance_to(tuple(x)) == pytest.approx(2.15, abs=1e-3) for x in q.dowels)
        assert back.bounding_box().size.Z == pytest.approx(200.0)


# ---- #3 animation ----------------------------------------------------------------------------------------------

def rendered(ws, args: dict) -> dict:
    """render_animation as the agent calls it: again with the same arguments until the file is there (issue #9)."""
    import time
    for _ in range(600):
        out = agent.call("render_animation", caller(ws), args)[0]
        if out.get("url"):
            return out
        assert out["state"] in ("rendering", "waiting") and out["frames"] > 0
        time.sleep(0.1)
    raise AssertionError("the render never finished")


def test_the_agent_animates_and_the_server_renders_it(lamp, ws):
    anim = {"fps": 30, "length": 60, "tracks": {"leaf_left": [[0, 0], [30, 90], [60, 0]], "leaf_right": [[0, 0], [30, -90], [60, 0]]}}
    got = agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": anim})[0]
    assert got["animation"]["tracks"]["leaf_left"][1] == [30, 90.0] and "warning" not in got
    assert lamp.status()["animations"]["lamp"]["length"] == 60           # the canvas's timeline has it
    with pytest.raises(Problem, match="a key is \\[frame, value\\]"):
        agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": {"tracks": {"leaf_left": [[0.5, 1]]}}})
    out = rendered(ws, {"project": "lamp", "note": "lamp", "fps": 10})
    assert out["frames"] == 21 and out["joints"] == ["leaf_left", "leaf_right"]
    from PIL import Image
    gif = Image.open(lamp.render_animation("lamp", "iso", 10)[0])
    assert gif.n_frames == 21
    video = rendered(ws, {"project": "lamp", "note": "lamp", "format": "mp4", "fps": 30})
    assert video["url"].split("?")[0].endswith("/animation.mp4") and video["frames"] == 61
    data = lamp.render_animation("lamp", "iso", 30, format="mp4")[0].read_bytes()
    assert data[4:8] == b"ftyp"                                          # an MP4, its index at the front
    with pytest.raises(Problem, match="gif or mp4"):
        agent.call("render_animation", caller(ws), {"project": "lamp", "note": "lamp", "format": "avi"})
    # the action line: the video ends at the pause, held a second there
    agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": {**anim, "actions": [{"frame": 30, "do": "pause", "hold": 1}]}})
    out = rendered(ws, {"project": "lamp", "note": "lamp", "fps": 10})
    assert out["frames"] == 11 + 10 and out["seconds"] == 2.0
    assert Image.open(lamp.render_animation("lamp", "iso", 10)[0]).n_frames == 21
    agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": None})
    assert "lamp" not in lamp.status()["animations"]


def test_a_render_runs_apart_once_and_the_rest_still_answers(lamp, ws, monkeypatch):
    """Issue #9: the render is a job; the call answers (here at once), the same call twice is one render, others answer."""
    from monet import jobs
    monkeypatch.setattr(agent, "WAIT_RENDER", 0)
    anim = {"fps": 30, "length": 60, "tracks": {"leaf_left": [[0, 0], [60, 90]]}}
    agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": anim})
    args = {"project": "lamp", "note": "lamp", "fps": 29, "format": "gif"}
    before = set(jobs._jobs)
    first = agent.call("render_animation", caller(ws), args)[0]
    assert first["state"] in ("rendering", "waiting") and "url" not in first and first["frames"] == 59
    mine = [k for k in jobs._jobs if k not in before]      # this render's job (another test's may still be running)
    assert len(mine) == 1
    job = jobs._jobs[mine[0]]["future"]
    second = agent.call("render_animation", caller(ws), args)[0]
    assert second["state"] in ("rendering", "waiting", "done")
    assert jobs._jobs.get(mine[0], {"future": job})["future"] is job      # one render, not two
    assert lamp.status()["notes"]                                                      # the rest answers meanwhile
    done = rendered(ws, args)
    assert done["state"] == "done" and done["bytes"] > 0
    agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": None})


def test_an_upload_with_pieces_that_are_not_pieces_is_refused(lamp):
    from conftest import built_files
    files = built_files(lamp.dir, "strip")
    r = json.loads(files["result.json"])
    r["pieces"] = [{"name": "x", "bbox": "everywhere"}]
    with pytest.raises(Problem, match="pieces of that build"):
        lamp.accept_build("strip", {**files, "result.json": json.dumps(r).encode()})
    r["pieces"], r["keepouts"] = None, "all"
    with pytest.raises(Problem, match="keepouts"):
        lamp.accept_build("strip", {**files, "result.json": json.dumps(r).encode()})


def test_a_bom_names_notes_never_paths(lamp):
    source = lamp.read("lamp")
    try:
        lamp.write("lamp", source.replace('"vertebra_*": {"print": "vertebra"}', '"vertebra_*": {"print": "../../../etc"}'), agent=True)
        b = lamp.bom("lamp")
        assert b["printed"]["../../../etc"]["fits_bed"] is None and "no build" in b["printed"]["../../../etc"]["why"]
        assert lamp.cached("../lamp") is None
    finally:
        lamp.write("lamp", source, agent=True)


# ---- lights and beams (0.10) ---------------------------------------------------------------------------------

LIGHTS = '''
LIGHTS = {
    "beam": {"kind": "projector", "on": "projector", "at": [0, 50, 30], "aim": [0, 1, 0], "throw": 1.5, "aspect": "16:9", "offset": 0.25, "lumens": 3000},
    "down": {"kind": "spot", "on": "arm", "at": [0, 190, 295], "aim": [0, 0, -1], "angle": 24, "lumens": 600},
    "line": {"kind": "laser", "on": "leaf_left", "at": [-100, 150, 20], "aim": [0, 1, 0], "fan": 40, "mw": 50},
    "glow": {"kind": "glow", "glow": "leaf_right", "color": "#ff9a4d"},
}
'''


def test_lights_are_checked_against_the_parts():
    from monet import lights
    got, wrong = lights.clean({"a": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, -2], "angle": 60, "lumens": 800}}, ["head"])
    assert wrong == [] and got[0]["aim"] == [0, 0, -1] and got[0]["soft"] == 0.2 and got[0]["reach"] == 3000
    assert got[0]["candela"] == pytest.approx(800 / (2 * 3.141592653589793 * (1 - 0.8660254)), rel=1e-4)     # lumens over the beam's solid angle
    p, _ = lights.clean({"p": {"kind": "projector", "at": [0, 0, 0], "aim": [0, 1, 0], "throw": 2, "aspect": "4:3"}}, [])
    assert p[0]["picture"] == {"width_at_1m": 500.0, "height_at_1m": 375.0} and p[0]["up"] == [0, 0, 1] and p[0]["reach"] == 6000
    straight, _ = lights.clean({"p": {"kind": "projector", "at": [0, 0, 0], "aim": [0, 0, -1]}}, [])
    assert straight[0]["up"] == [0, 1, 0]           # looking straight down, its picture's top is +Y
    fan, _ = lights.clean({"l": {"kind": "laser", "at": [0, 0, 0], "aim": [1, 0, 0], "fan": 30}}, [])
    assert fan[0]["across"] == [0, 0, 1] and fan[0]["mw"] == 50
    bad = {
        "room": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, 1]},
        "a": {"kind": "torch", "at": [0, 0, 0]},
        "b": {"kind": "spot", "at": [0, 0], "aim": [0, 0, 1]},
        "c": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, 0]},
        "d": {"kind": "spot", "on": "tail", "at": [0, 0, 0], "aim": [0, 0, 1]},
        "e": {"kind": "glow"},
        "f": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, 1], "angle": 200},
        "g": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, 1], "script": "alert(1)"},
        "h": {"kind": "projector", "at": [0, 0, 0], "aim": [0, 0, 1], "aspect": "wide"},
        "i": {"kind": "spot", "at": [0, 0, 0], "aim": [0, 0, 1], "color": "red"},
    }
    got, wrong = lights.clean(bad, ["head"])
    assert got == [] and len(wrong) == len(bad)
    assert lights.clean("lamp", []) == ([], ["LIGHTS is {name: {kind, at, …}}"])
    glows, wrong = lights.clean({"px": {"kind": "glow", "glow": "caps_*|lens"}, "no": {"kind": "glow", "glow": "tiles_*"}}, ["caps_top", "lens", "frame"])
    assert [L["glow"] for L in glows] == ["caps_*|lens"] and wrong == ["light no: glow: no part is 'tiles_*'"]
    assert lights.clean(None, []) == ([], [])


def test_the_lamp_has_lights_that_need_no_build(lamp):
    """LIGHTS is a fact: written into the Note, its build stays current; the report hands the lights to the canvas."""
    from monet import note
    source = lamp.read("lamp")
    with_lights = source.replace("\n\ndef tube(", LIGHTS + "\n\ndef tube(", 1)
    assert note.geometry_key(with_lights) == note.geometry_key(source)
    lamp.write("lamp", with_lights, agent=True)
    try:
        r = lamp.report("lamp")
        assert r["state"] == "built" and r["green"], [c for c in r["checks"] if not c["ok"]]
        by = {L["name"]: L for L in r["lights"]}
        assert set(by) == {"beam", "down", "line", "glow"}
        assert by["beam"]["on"] == "projector" and by["beam"]["aspect"] == pytest.approx(16 / 9) and by["glow"]["glow"] == "leaf_right"
        lamp.write("lamp", with_lights.replace('"on": "arm"', '"on": "boom"'), agent=True)
        r = lamp.report("lamp")
        row = next(c for c in r["checks"] if c["id"] == "lights")
        assert not r["green"] and "there is no part 'boom'" in row["why"] and len(r["lights"]) == 3
    finally:
        lamp.write("lamp", source, agent=True)
    assert "lights" not in lamp.report("lamp")


def test_the_timeline_keys_lights_the_room_and_the_haze(lamp):
    anim = {"fps": 30, "length": 60, "tracks": {"leaf_left": [[0, 0], [60, 90]]},
            "lights": {"beam": [[0, 0], [30, 1]], "room": [[0, 0.3], [60, 0.05]], "haze": [[10, 0.8]]},
            "actions": [{"frame": 50, "do": "pause"}]}
    got = lamp.set_animation("lamp", anim)["lamp"]
    assert got["lights"] == {"beam": [[0, 0.0], [30, 1.0]], "room": [[0, 0.3], [60, 0.05]], "haze": [[10, 0.8]]}
    for bad in ({"beam": [[0, 1.5]]}, {"beam": [[61, 1]]}, {"Beam!": [[0, 1]]}, {"beam": "on"}, ["beam"]):
        with pytest.raises(Problem):
            lamp.set_animation("lamp", {**anim, "lights": bad})
    lamp.set_animation("lamp", None)


# ---- #10 pixels ------------------------------------------------------------------------------------------------

PIXELS = '''"""Two caps over a tile: each cap a pixel, lit from the LEDs under it."""
from build123d import *

PARAMS = {}
TAGS = {}
LIGHTS = {"px": {"kind": "pixels", "glow": "caps", "leds": "leds", "color": "#2f6bff"}}


def leds(p=PARAMS):
    return [((0, 0, 1), (0, 0, 1), 9), ((2, 0, 1), (0, 0, 1), 9), (30, 0, 1), (300, 300, 300)]


def build(p=PARAMS):
    tile = Box(80, 30, 1, align=(Align.CENTER, Align.CENTER, Align.MAX))
    tile.label = "tile"
    caps = Pos(0, 0, 0) * Box(20, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) + Pos(30, 0, 0) * Box(20, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    caps.label = "caps"
    return Compound(children=[tile, caps])
'''


def test_pixels_are_found_by_the_build_with_their_leds(ws):
    """Every solid of a part a pixels light names is a pixel; each LED goes to the pixel whose box holds it."""
    p = ws.create_project("pixels")
    p.write("px", PIXELS, agent=True)
    r = agent_builds(p, "px")
    assert r["built"] and r["green"], r.get("error")
    px = r["pixels"]["px"]
    assert px["count"] == 2 and px["leds_total"] == 3 and px["stray"] == 1 and px["unlit"] == 0
    assert px["leds"] == {"min": 1, "median": 1.5, "max": 2} and px["density_ratio"] == 2.0 and px["current_a"] == 0.18
    geo = json.loads((p.out / "px" / "faces.json").read_text())
    cells = geo["pixels"]["px"]
    assert sorted(len(q["leds"]) for q in cells) == [1, 2] and all(q["part"] == "caps" and q["faces"] for q in cells)
    assert [len(q["leds"][0]) for q in cells] == [7, 7]      # x, y, z, normal, depth
    # a check holds them: no pixel much dimmer than the rest
    p.add_check("px", {"what": "pixels.px.density_ratio", "max": 1.5, "why": "no pixel noticeably dimmer"}, by="user")
    row = [c for c in p.report("px")["checks"] if c["what"] == "pixels.px.density_ratio"][0]
    assert row["value"] == 2.0 and not row["ok"]


def test_a_pixels_light_and_its_patterns_are_checked():
    from monet import lights as lamps
    ok, bad = lamps.clean({"px": {"kind": "pixels", "glow": "caps_*", "leds": "leds", "spill_mm": 6}}, ["caps_a", "tile"])
    assert not bad and ok[0]["spill_mm"] == 6 and ok[0]["lumens_per_led"] == 6
    _, bad = lamps.clean({"px": {"kind": "pixels"}}, ["caps_a"])
    assert "glow" in bad[0]
    assert lamps.pattern({"kind": "chase", "color": "#2F6BFF", "pulses": 4}) == {"kind": "chase", "color": "#2f6bff", "pulses": 4}
    for wrong in ({"kind": "strobe"}, {"kind": "chase", "axis": "z"}, {"kind": "scan", "axis": "w"}, {"kind": "wave", "speed": -1}):
        with pytest.raises(ValueError):
            lamps.pattern(wrong)


def test_patterns_are_kept_on_the_timeline(lamp, ws):
    anim = {"fps": 30, "length": 60, "tracks": {"leaf_left": [[0, 0], [60, 90]]},
            "patterns": {"strip": [[0, {"kind": "chase", "color": "#2f6bff"}], [30, {"kind": "rainbow"}]]}}
    got = agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": anim})[0]
    assert got["animation"]["patterns"]["strip"][1] == [30, {"kind": "rainbow"}]
    with pytest.raises(Problem, match="kind is one of"):
        agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": {**anim, "patterns": {"strip": [[0, {"kind": "strobe"}]]}}})
    agent.call("animate", caller(ws), {"project": "lamp", "note": "lamp", "animation": None})
