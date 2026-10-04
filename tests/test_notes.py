"""Every Note in notes/ builds, keeps its tags and passes its checks. The MG400 parts must also match what the
Fusion script produced (reference/mg400_rakis): sizes exactly, volume and surface within 1 %."""
import json

import pytest

from monet.app import ROOT

NOTES = sorted((p.parent.name, p.stem) for p in (ROOT / "notes").glob("*/*.py")
               if not p.stem.startswith("_") and "def build(" in p.read_text())
REPORT = {b["name"]: b for b in json.loads((ROOT / "reference/mg400_rakis/F_report.json").read_text())["bodies"]}
EXACT = json.loads((ROOT / "reference/mg400_rakis/measured_from_fusion.json").read_text())["bodies"]
FUSION_BODY = {"nest_back": "nest_back", "nest_front": "nest_front", "grid_pos_0": "grid_pos_0", "grid_neg_0": "grid_neg_0",
               "grid_pos_1": "grid_pos_1", "grid_neg_1": "grid_neg_1", "l_bracket": "L_back_pos"}


@pytest.mark.parametrize("project,name", NOTES, ids=[f"{p}/{n}" for p, n in NOTES])
def test_note_builds_and_is_green(ws, project, name):
    report = ws.project(project).report(name)
    assert report["built"], report.get("error")
    assert report["measure"]["valid"]
    failed = [(c["id"], c["value"], c["expect"]) for c in report["checks"] if not c["ok"]]
    assert not failed
    assert report["green"]


@pytest.mark.parametrize("name,body", FUSION_BODY.items())
def test_port_matches_fusion(ws, name, body):
    m = ws.project("mg400_rakis").report(name)["measure"]
    ref = REPORT[body]
    assert m["size_x"] == pytest.approx(ref["size_xy"][0], abs=0.05)
    assert m["size_y"] == pytest.approx(ref["size_xy"][1], abs=0.05)
    assert m["min_z"] == pytest.approx(ref["z"][0], abs=0.05) and m["max_z"] == pytest.approx(ref["z"][1], abs=0.05)
    assert m["solids"] == 1
    assert m["volume_cm3"] == pytest.approx(EXACT.get(body, ref)["volume_cm3"], rel=0.01)
    if body in EXACT:   # measured from the Fusion model itself: a much sharper test than volume
        assert m["area_cm2"] == pytest.approx(EXACT[body]["area_cm2"], rel=0.01)


def test_assembly_has_the_fourteen_bodies(ws):
    m = ws.project("mg400_rakis").report("rakis")["measure"]
    assert m["solids"] == len(REPORT) == 14


def test_assembly_knows_its_parts(ws):
    """The parts of an assembly are the labelled children its Note returns: named, each a range of the one mesh."""
    project = ws.project("mg400_rakis")
    report = project.report("rakis")
    assert [p["name"] for p in report["parts"]] == list(REPORT)          # the body names of the Fusion model, in order
    by_name = {p["name"]: p for p in report["parts"]}
    assert by_name["grid_pos_0"]["volume_cm3"] == pytest.approx(159.364, abs=0.01) and by_name["grid_pos_0"]["size"] == [168.0, 210.0, 24.0]
    assert "parts" not in project.report("nest_back")                    # a plain part is not an assembly

    described = json.loads((project.out / "rakis" / "faces.json").read_text())
    result = project.cached("rakis")
    tri = face = seg = 0
    for part in described["parts"]:
        assert part["tris"][0] == tri and part["faces"][0] == face and part["edges"][0] == seg    # one after the other
        tri, face, seg = tri + part["tris"][1], face + part["faces"][1], seg + part["edges"][1]
    assert tri == result["triangles"] and face == len(described["faces"]) == result["fingerprint"]["faces"]

    # and the preview keeps that order: every part's triangles and edges lie inside that part's own box
    import numpy as np
    from monet import render
    verts, tris, segs = render.load(project.out / "rakis" / "model.glb")
    assert len(segs) == seg
    for part in described["parts"]:
        lo, hi = np.array(part["bbox"][:3]) - 0.01, np.array(part["bbox"][3:]) + 0.01
        for pts in (verts[tris[part["tris"][0]:part["tris"][0] + part["tris"][1]].reshape(-1)],
                    segs[part["edges"][0]:part["edges"][0] + part["edges"][1]].reshape(-1, 3)):
            assert (pts >= lo).all() and (pts <= hi).all(), part["name"]


def test_status_says_which_note_is_the_assembly(workspaces):
    fresh = workspaces.create("unbuilt").project("mg400_rakis")          # nothing built yet: told from its imports
    kinds = {n["name"]: n["kind"] for n in fresh.status()["notes"]}
    assert kinds["rakis"] == "assembly" and kinds["nest_front"] == "note" and kinds["grid_neg_1"] == "note" and kinds["rakis_common"] == "module"
    fresh.report("rakis")                                                # built: told from its parts
    assert {n["name"]: n["kind"] for n in fresh.status()["notes"]}["rakis"] == "assembly"


def test_edges_and_points_can_be_pointed_at(ws):
    """Every edge and corner point of a build is plain data with its number, so the canvas can select it."""
    project = ws.project("starter")
    project.report("rod_foot")
    d = json.loads((project.out / "rod_foot" / "faces.json").read_text())
    assert len(d["edges"]) == 24 and len(d["points"]) == 16          # a box with a square tunnel through it
    assert [e["i"] for e in d["edges"]] == list(range(24)) and [v["i"] for v in d["points"]] == list(range(16))
    assert {e["type"] for e in d["edges"]} == {"line"} and sorted({e["len"] for e in d["edges"]}) == [16.4, 22.4, 45.0]
    seg = 0
    for e in d["edges"]:
        assert e["segs"][0] == seg and e["p"] == 0
        seg += e["segs"][1]
    assert seg == d["parts"][0]["edges"][1]
    assert d["parts"][0]["name"] == "rod_foot"                        # a plain part goes by the name of its Note
    assert [-22.5, -11.2, 0.0] in [v["at"] for v in d["points"]]

    asm = ws.project("mg400_rakis")
    asm.report("rakis")
    a = json.loads((asm.out / "rakis" / "faces.json").read_text())
    assert [v["i"] for v in a["points"]] == list(range(len(a["points"])))
    assert {e["type"] for e in a["edges"]} == {"line", "circle", "other"}
    last = a["parts"][-1]
    assert all(e["p"] == len(a["parts"]) - 1 for e in a["edges"] if e["segs"][0] >= last["edges"][0])
    circle = next(e for e in a["edges"] if e["type"] == "circle")
    assert circle["r"] > 0 and len(circle["c"]) == 3
