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
