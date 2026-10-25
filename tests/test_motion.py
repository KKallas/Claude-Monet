"""Joints: an assembly's parts move as its JOINTS say, and what moving them hits is found.

The MG400 must move as Dobot's own robot description says it does (reference/mg400: their URDF):
every link where the URDF puts it, at any pose. Both of them: mg400 (Dobot's own link shapes) and
mg400_blocks (simple links). The rakis top must slide 79 mm, stopped by the L brackets."""
import json
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from monet import joints, note as notes
from monet.app import ROOT

URDF = ROOT / "reference/mg400/mg400_description.urdf"
REAL = json.loads((ROOT / "reference/mg400/links.json").read_text())["links"]
LINK = {v["urdf_link"]: k for k, v in REAL.items()}      # URDF link -> part of the Note


# ---- the rules, without a build -------------------------------------------------------------------------------

def test_a_tree_of_bodies_from_the_ground():
    spec = {"frame": {"kind": "rigid", "parts": ["a", "b"]},
            "hinge": {"kind": "revolute", "moves": "lid", "on": "frame", "axis": {"origin": [10, 0, 0], "dir": "Y"}, "range": [0, 90]},
            "slide": {"kind": "slider", "moves": "knob", "on": "lid", "axis": "X", "range": [-5, 5]},
            "gear": {"kind": "revolute", "moves": "wheel", "on": "frame", "axis": {"origin": [0, 0, 0], "dir": "Z"}, "follows": {"hinge": 2}}}
    m = joints.resolve(spec, "frame", ["a", "b", "lid", "knob", "wheel", "loose"])
    assert m["ok"] and m["problems"] == []
    assert m["bodies"]["frame"] == ["a", "b"] and m["free"] == ["loose"]
    assert m["tree"].index("hinge") < m["tree"].index("slide")          # a joint is placed after what it hangs on
    assert joints.drivers(m) == ["hinge", "slide"]
    assert joints.values(m, {"hinge": 30})["gear"] == 60

    pf = joints.part_frames(m, {"hinge": 90, "slide": 2})
    assert np.allclose(pf["a"], np.eye(4)) and np.allclose(pf["loose"], np.eye(4))
    turn = lambda T, p: (T @ [*p, 1.0])[:3]
    # a quarter turn about +Y through (10, 0, 0), right hand: +X goes to -Z
    assert np.allclose(turn(pf["lid"], (20, 0, 0)), (10, 0, -10))
    # the knob rides on the lid: its slide along X turns with it
    assert np.allclose(turn(pf["knob"], (20, 0, 0)), (10, 0, -12))
    assert np.allclose(turn(pf["wheel"], (1, 0, 0)), (math.cos(math.pi), math.sin(math.pi), 0), atol=1e-9)


def test_what_is_wrong_is_told_not_thrown():
    m = joints.resolve({"g": {"kind": "rigid", "parts": ["a", "nope"]},
                        "two": {"kind": "revolute", "moves": "b", "on": "g", "axis": "X"},
                        "again": {"kind": "slider", "moves": "b", "on": "c", "axis": "Y"},
                        "lost": {"kind": "revolute", "moves": "c", "on": "g", "axis": "no_such_tag"},
                        "round": {"kind": "revolute", "moves": "d", "on": "g", "axis": "Z", "follows": {"round2": 1}},
                        "round2": {"kind": "revolute", "moves": "e", "on": "a", "axis": "Z", "follows": {"round": 1}},
                        "odd": {"kind": "spring"}}, "nothing", ["a", "b", "c", "d", "e"], tags={}, found={})
    assert not m["ok"]
    said = " | ".join(m["problems"])
    assert "no part 'nope'" in said and "no body 'nothing'" in said and "kind is one of" in said and "round in a circle" in said
    assert m["joints"]["two"]["resolved"] and "moved by two already" in m["joints"]["again"]["why"]
    assert "no tag 'no_such_tag'" in m["joints"]["lost"]["why"]
    assert "no body 'a'" in m["joints"]["round2"]["why"]                  # a is in the group g now: the body is g


def test_joints_are_written_into_the_note_and_read_back():
    src = '"""A box."""\nfrom build123d import *\n\nTAGS = {}\n\n\ndef build():\n    return Box(1, 1, 1)\n'
    out = notes.set_joints(src, {"hinge": joints.clean({"kind": "revolute", "moves": "lid", "on": "box", "axis": {"origin": [0, 0, 5], "dir": "y"}, "range": [0, 90]})}, "box")
    parsed = notes.parse(out)
    assert parsed["ground"] == "box" and parsed["error"] is None
    assert parsed["joints"]["hinge"] == {"kind": "revolute", "moves": "lid", "on": "box", "axis": {"origin": [0.0, 0.0, 5.0], "dir": "Y"}, "range": [0.0, 90.0]}
    assert out.index("TAGS") < out.index("GROUND") < out.index("JOINTS") < out.index("def build")
    again = notes.set_joints(out, {}, None)
    assert notes.parse(again)["joints"] == {} and notes.parse(again)["ground"] == "box" and again.count("JOINTS") == 1
    with pytest.raises(ValueError):
        joints.clean({"kind": "revolute", "moves": "lid", "on": "box"})          # nothing to turn about


# ---- the MG400 moves as Dobot says it does --------------------------------------------------------------------

def urdf_frames(q):
    """World frame of every URDF link at J1..J4 = q (degrees), with the URDF's own mimic rules."""
    root = ET.parse(URDF).getroot()
    js = {}
    for j in root.iter("joint"):
        o = j.find("origin")
        js[j.find("child").get("link")] = {
            "name": j.get("name"), "parent": j.find("parent").get("link"),
            "xyz": [1000 * float(x) for x in o.get("xyz").split()] if o is not None else [0, 0, 0],
            "axis": [float(x) for x in j.find("axis").get("xyz").split()],
            "mimic": (j.find("mimic").get("joint"), float(j.find("mimic").get("multiplier", 1))) if j.find("mimic") is not None else None}
    by_name = {v["name"]: v for v in js.values()}
    given = dict(zip(("j1", "j2", "j3", "j4"), q))

    def value(name):
        if name in given:
            return given[name]
        other, k = by_name[name]["mimic"]
        return k * value(other)
    out = {"base_link": np.eye(4)}

    def frame(link):
        if link not in out:
            j = js[link]
            T = np.eye(4)
            T[:3, 3] = j["xyz"]
            out[link] = frame(j["parent"]) @ T @ joints.rotation((0, 0, 0), np.array(j["axis"]) / np.linalg.norm(j["axis"]), value(j["name"]))
        return out[link]
    for link in js:
        frame(link)
    return out


POSES = [(0, 0, 0, 0), (30, 10, 20, 45), (-120, 60, 80, -90), (160, -25, -25, 180), (45, 85, 105, 10), (-75, 40, -10, 0)]


@pytest.fixture(scope="module", params=["mg400", "mg400_blocks"])
def arm(ws, request):
    report = ws.project("mg400_rakis").report(request.param)
    assert report["built"], report.get("error")
    return report


@pytest.fixture(scope="module")
def mg400(ws):
    return ws.project("mg400_rakis").report("mg400")


@pytest.fixture(scope="module")
def blocks(ws):
    return ws.project("mg400_rakis").report("mg400_blocks")


@pytest.mark.parametrize("q", POSES, ids=[",".join(map(str, q)) for q in POSES])
def test_mg400_moves_as_its_urdf_says(arm, q):
    model = arm["motion"]
    assert model["ok"] and joints.drivers(model) == ["j1", "j2", "j3", "j4"]
    mine = joints.part_frames(model, dict(zip(("j1", "j2", "j3", "j4"), q)))
    home, there = urdf_frames((0, 0, 0, 0)), urdf_frames(q)
    for link, part in LINK.items():
        # how the URDF moves this link away from where it is as built, against how the Note's joints move it.
        # The URDF tilts J4 by 0.0007° (its SolidWorks export); the Note keeps it upright, which moves the tool by
        # up to 0.01 mm at the far poses. Every other link agrees to a micron.
        assert np.allclose(mine[part], there[link] @ np.linalg.inv(home[link]), atol=0.02 if part == "tool" else 1e-3), (part, q)


@pytest.mark.parametrize("q", POSES[1:], ids=[",".join(map(str, q)) for q in POSES[1:]])
def test_mg400_parallelograms_hold_and_the_tool_points_down(arm, q):
    pf = joints.part_frames(arm["motion"], dict(zip(("j1", "j2", "j3", "j4"), q)))
    at = lambda part, p: (pf[part] @ [*p, 1.0])[:3]
    # the rear loop: the top of the rear rod, the elbow plate's third pivot and the forearm rod's pivot are one point
    top = (37.4495, 0.0, 402.9969)
    assert np.allclose(at("upper_rod", top), at("elbow", top), atol=0.01) and np.allclose(at("upper_rod", top), at("forearm_rod", top), atol=0.01)
    # the front loop: where the forearm's far end meets the wrist
    d = (241.3448, 0.0, 440.7207)
    assert np.allclose(at("forearm", d), at("wrist", d), atol=0.01)
    # the tool stays upright whatever J2 and J3 do: only J1 and J4 turn it, about Z
    assert np.allclose(pf["tool"][:3, 2], (0, 0, 1), atol=1e-9)


@pytest.mark.parametrize("which,within", [("mg400", 0.5), ("mg400_blocks", 6.0)])
def test_mg400_links_are_the_size_of_the_real_ones(ws, which, within):
    """Each link's box, in its own frame, against the real link's: Dobot's shapes (simplified to 0.4 mm) within
    half a millimetre on every side; the blocks within 6 mm."""
    home = urdf_frames((0, 0, 0, 0))
    for part in ws.project("mg400_rakis").report(which)["parts"]:
        real = REAL[part["name"]]["bbox"]
        o = home[REAL[part["name"]]["urdf_link"]][:3, 3]
        lo = [part["at"][k] - part["size"][k] / 2 - o[k] for k in range(3)]
        hi = [part["at"][k] + part["size"][k] / 2 - o[k] for k in range(3)]
        assert np.allclose(lo, real[:3], atol=within) and np.allclose(hi, real[3:], atol=within), (part["name"], lo, hi, real)


def test_mg400_moves_freely_and_its_pins_are_not_clashes(mg400):
    """Dobot's shapes overlap where a pin sits in its hole. Turning on that pin is no clash, whether a joint joins
    the two parts or the pin closes a parallelogram: J1, J2 and J4 go their whole ranges freely."""
    m = mg400["motion"]
    assert m["ok"] and m["unchecked"] == [] and mg400["measure"]["valid"]
    pins = {(a, b) for a, b, _ in m["interference"]["pairs"]}
    assert ("turret", "upper_rod") in pins and ("forearm", "wrist") in pins          # the rear axle; the far pin of the front loop
    for j in ("j1", "j2", "j4"):
        assert m["sweeps"][j]["clash_mm3"] == 0.0, (j, m["sweeps"][j])
    # J2 tilted back past its range: the upper arm meets the rear rod. J3, with J2 upright: the wrist meets it too
    assert -33 < m["sweeps"]["j2"]["stop_min"] < -25
    s = m["sweeps"]["j3"]
    assert 80 < s["stop_max"] < 90 and s["clashes"][0][2][0][:2] == ["upper_rod", "wrist"]


def test_mg400_blocks_nothing_overlaps_as_built_and_the_wrist_meets_the_rod(blocks):
    m = blocks["motion"]
    assert m["interference"] == {"total_mm3": 0.0, "pairs": []} and m["unchecked"] == []
    for j in ("j1", "j2", "j4"):          # alone, each goes through its whole range freely
        assert m["sweeps"][j]["clash_mm3"] == 0.0, j
    # with J2 upright, J3 brings the wrist down onto the rear rod before the end of its range
    s = m["sweeps"]["j3"]
    assert 75 < s["stop_max"] < 90 and s["clashes"][0][2][0][:2] == ["upper_rod", "wrist"]


# ---- the rakis top slides between the L brackets --------------------------------------------------------------

def test_rakis_top_slides_79_mm_between_the_brackets(ws):
    p = ws.project("mg400_rakis")
    m = p.report("rakis")["motion"]
    assert m["ok"] and m["ground"] == ["rails"] and m["free"] == []
    assert m["joints"]["slide"]["dir"] == [1.0, 0.0, 0.0]                # along the pipe tunnel tag
    s = m["sweeps"]["slide"]
    assert s["stop_min"] == pytest.approx(-79.0, abs=0.05) and s["stop_max"] == pytest.approx(0.0, abs=0.05)
    assert s["clash_mm3"] == 0.0
    # as built, the nest's snap-off ears overlap the grid's first tiles and the back brackets
    pairs = {(a, b) for a, b, _ in m["interference"]["pairs"]}
    assert pairs == {("nest_front", "grid_pos_0"), ("nest_front", "grid_neg_0"), ("nest_back", "L_back_pos"), ("nest_back", "L_back_neg")}
    assert p.pose("rakis", {"slide": -40})["clashes"] == []
    hit = p.pose("rakis", {"slide": -80})["clashes"]
    assert {(a, b) for a, b, _ in hit} == {("grid_pos_1", "L_front_pos"), ("grid_neg_1", "L_front_neg")}
    assert all(v == pytest.approx(256, rel=0.05) for _, _, v in hit)      # 1 mm into the brackets' 256 mm² faces


# ---- the canvas poses parts as the server does ---------------------------------------------------------------

def test_the_canvas_poses_the_mg400_as_the_server_does(mg400, tmp_path):
    """canvas/motion.js has its own tests in node; here it is held against monet/joints.py on a real model."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("no node on this machine")
    done = subprocess.run([node, "--test", str(ROOT / "tests/motion.test.mjs")], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-2000:]
    poses = [dict(zip(("j1", "j2", "j3", "j4"), q)) for q in POSES]
    (tmp_path / "in.json").write_text(json.dumps({"model": mg400["motion"], "poses": poses}))
    script = (f"import {{ frames, bodyOf }} from {json.dumps((ROOT / 'canvas/motion.js').as_uri())};\n"
              f"const d = JSON.parse(require('fs').readFileSync({json.dumps(str(tmp_path / 'in.json'))}, 'utf8'));\n"
              "const of = bodyOf(d.model);\n"
              "console.log(JSON.stringify(d.poses.map((q) => { const f = frames(d.model, q); return Object.fromEntries(Object.entries(of).map(([p, b]) => [p, f[b]])); })));")
    (tmp_path / "pose.mjs").write_text(script.replace("require('fs')", "(await import('node:fs'))"))
    out = subprocess.run([node, str(tmp_path / "pose.mjs")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for q, theirs in zip(poses, json.loads(out.stdout)):
        mine = joints.part_frames(mg400["motion"], q)
        for part, m in theirs.items():
            assert np.allclose(np.array(m).reshape(4, 4), mine[part], atol=1e-9), (part, q)
