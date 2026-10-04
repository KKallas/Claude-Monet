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
