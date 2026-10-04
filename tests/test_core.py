"""The parts that need no CAD kernel: reading Notes, finding tags on face descriptors, checks, the load check."""
import pytest

from monet import feynman, note, semmelweis, tags

NOTE = '''"""
Thing: a test part.

Rules
- flat on the table
"""
from build123d import *

PARAMS = dict(a=1.0, b=2)

TAGS = {
    "base": {"kind": "planar_face", "normal": "-Z", "at": 0},  # a comment that goes when tags are rewritten
}


def build(p=PARAMS):
    return Box(1, 1, 1)
'''


def plane(i, normal, center, bbox, area=100.0):
    return {"i": i, "type": "plane", "normal": list(normal), "center": list(center), "bbox": list(bbox), "area": area, "tris": [0, 0]}


def tube(length=45.0, s=16.4, wall=3.0):
    """Face descriptors of a square tube along X, bottom on z = 0: what the runner makes of the rod foot."""
    o = s + 2 * wall
    h, c, x = o / 2, wall + s / 2, length / 2
    return [
        plane(0, (0, 0, -1), (0, 0, 0), (-x, -h, 0, x, h, 0)),
        plane(1, (0, 0, 1), (0, 0, o), (-x, -h, o, x, h, o)),
        plane(2, (0, -1, 0), (0, -h, h), (-x, -h, 0, x, -h, o)),
        plane(3, (0, 1, 0), (0, h, h), (-x, h, 0, x, h, o)),
        plane(4, (-1, 0, 0), (-x, 0, h), (-x, -h, 0, -x, h, o)),
        plane(5, (1, 0, 0), (x, 0, h), (x, -h, 0, x, h, o)),
        # the tunnel: its walls face into the void
        plane(6, (0, 0, 1), (0, 0, wall), (-x, -s / 2, wall, x, s / 2, wall)),
        plane(7, (0, 0, -1), (0, 0, wall + s), (-x, -s / 2, wall + s, x, s / 2, wall + s)),
        plane(8, (0, 1, 0), (0, -s / 2, c), (-x, -s / 2, wall, x, -s / 2, wall + s)),
        plane(9, (0, -1, 0), (0, s / 2, c), (-x, s / 2, wall, x, s / 2, wall + s)),
    ], [-x, -h, 0, x, h, o]


def test_parse_reads_a_note_without_running_it():
    p = note.parse(NOTE)
    assert p["is_note"] and p["error"] is None
    assert p["doc"].startswith("Thing: a test part.")
    assert p["params"] == {"a": 1.0, "b": 2}
    assert p["tags"]["base"]["normal"] == "-Z"
    assert not note.parse("X = 1\n")["is_note"]
    assert "syntax error" in note.parse("def build(:\n")["error"]
    assert "TAGS must be a plain literal" in note.parse("TAGS = make()\ndef build(): pass\n")["error"]
    assert note.parse("PARAMS = dict(P)\ndef build(): pass\n")["error"] is None      # shared params are fine


def test_imports_are_read_from_the_source():
    assert note.imports("from build123d import *\nimport nest_back, grid_pos_0\nfrom rakis_common import P\n") == {"build123d", "nest_back", "grid_pos_0", "rakis_common"}
    assert note.imports("def build(:") == set()


def test_set_tags_changes_only_the_tags():
    new = note.set_tags(NOTE, {"top": {"kind": "planar_face", "normal": "+Z", "at": 1.5, "through": True, "role": 'say "hi"'}})
    p = note.parse(new)
    assert p["tags"] == {"top": {"kind": "planar_face", "normal": "+Z", "at": 1.5, "through": True, "role": 'say "hi"'}}
    assert p["params"] == {"a": 1.0, "b": 2} and p["doc"].startswith("Thing") and "def build(p=PARAMS):" in new
    assert note.parse(note.set_tags(new, {}))["tags"] == {}
    added = note.set_tags("from build123d import *\n\ndef build():\n    return Box(1, 1, 1)\n", {"a": {"kind": "face_at", "point": [0, 0, 0]}})
    assert note.parse(added)["tags"]["a"]["kind"] == "face_at" and added.index("TAGS") < added.index("def build")


def test_planar_face_is_found_by_its_coordinate_whatever_the_normal():
    faces, box = tube()
    r = tags.resolve({"base": {"kind": "planar_face", "normal": "-Z", "at": 0}, "top": {"kind": "planar_face", "normal": "+Z"},
                      "left": {"kind": "planar_face", "normal": "-Y", "at": -11.2}}, faces, box)
    assert r["base"]["resolved"] and r["base"]["faces"] == [0]
    assert r["top"]["resolved"] and r["top"]["measure"]["at"] == pytest.approx(22.4)
    assert r["left"]["resolved"] and r["left"]["faces"] == [2]


def test_a_moved_face_reads_as_moved_not_as_gone():
    faces, box = tube()
    r = tags.resolve({"top": {"kind": "planar_face", "normal": "+Z", "at": 20.4}}, faces, box)["top"]
    assert not r["resolved"] and r["measure"]["moved"] == pytest.approx(2.0)


def test_square_hole_measures_what_is_there():
    faces, box = tube()
    r = tags.resolve({"bore": {"kind": "square_hole", "axis": "X", "at": [0, 11.2], "size": 16.4}}, faces, box)["bore"]
    assert r["resolved"] and sorted(r["faces"]) == [6, 7, 8, 9]
    assert r["measure"] == {"width": 16.4, "height": 16.4, "at": [0.0, 11.2], "length": 45.0, "through": True}
    # the tunnel made bigger: the tag still finds it and says how big it is now, so a check can fail on the number
    faces, box = tube(s=17.2)
    r = tags.resolve({"bore": {"kind": "square_hole", "axis": "X", "at": [0, 11.6], "size": 16.4}}, faces, box)["bore"]
    assert r["resolved"] and r["measure"]["width"] == pytest.approx(17.2)


def test_square_hole_that_moved_is_reported_where_it_went():
    faces, box = tube()
    r = tags.resolve({"bore": {"kind": "square_hole", "axis": "X", "at": [40.0, 11.2], "size": 16.4}}, faces, box)["bore"]
    assert not r["resolved"] and r["measure"]["moved"] == [-40.0, 0.0]


def test_bad_and_unknown_tags_do_not_crash():
    faces, box = tube()
    r = tags.resolve({"a": {"kind": "nonsense"}, "b": {"kind": "planar_face", "normal": "sideways"}, "c": {"kind": "round_hole", "axis": "Z", "at": [0, 0]}}, faces, box)
    assert not any(t["resolved"] for t in r.values())
    assert "unknown kind" in r["a"]["why"] and "bad tag" in r["b"]["why"]


def test_propose_describes_a_clicked_face():
    faces, _ = tube()
    assert tags.propose(faces[0]) == {"kind": "planar_face", "normal": "-Z", "at": 0.0}
    hole = {"i": 1, "type": "cylinder", "axis": [0, 0, -1], "origin": [10, 5, 3], "radius": 3.0, "concave": True, "center": [10, 5, 0], "bbox": [0] * 6, "area": 1}
    assert tags.propose(hole) == {"kind": "round_hole", "axis": "Z", "at": [10, 5], "diameter": 6.0}


# what the runner says of a 10 x 10 x 22.4 block with a round bore: two faces, two edges, two corners, one part
BLOCK = dict(
    faces=[plane(0, (0, 0, -1), (0, 0, 0), (-5, -5, 0, 5, 5, 0)), plane(1, (0, 0, 1), (0, 0, 22.4), (-5, -5, 22.4, 5, 5, 22.4))],
    edges=[{"i": 0, "p": 0, "type": "line", "len": 10.0, "a": [-5, -5, 0], "b": [5, -5, 0]},
           {"i": 1, "p": 0, "type": "circle", "len": 18.85, "a": [3, 0, 0], "b": [3, 0, 0], "r": 3.0, "c": [0, 0, 0]}],
    points=[{"i": 0, "p": 0, "at": [-5, -5, 0]}, {"i": 1, "p": 0, "at": [5, 5, 22.4]}],
    parts=[{"name": "foot", "volume": 2240.0, "bbox": [-5, -5, 0, 5, 5, 22.4], "faces": [0, 2]}])


def find(tag):
    return tags.resolve({"t": tag}, BLOCK["faces"], [-5, -5, 0, 5, 5, 22.4], edges=BLOCK["edges"], points=BLOCK["points"], parts=BLOCK["parts"])["t"]


def test_points_edges_and_objects_can_be_tagged():
    assert find({"kind": "point", "at": [-5, -5, 0]}) == {"resolved": True, "faces": [], "points": [0], "measure": {"at": [-5, -5, 0]}}
    gone = find({"kind": "point", "at": [9, 9, 9]})
    assert not gone["resolved"] and gone["measure"]["moved"] == pytest.approx(14.5451) and "nearest" in gone["why"]
    line = find({"kind": "edge", "a": [5, -5, 0], "b": [-5, -5, 0]})                  # either way round
    assert line["resolved"] and line["edges"] == [0] and line["measure"]["length"] == 10.0
    circle = find({"kind": "edge", "center": [0, 0, 0], "radius": 3.0})
    assert circle["resolved"] and circle["measure"]["diameter"] == 6.0
    # the bore made bigger is still the bore: found, and it says its size, so a check can fail on the number
    assert find({"kind": "edge", "center": [0, 0, 0], "radius": 2.5})["measure"]["radius"] == 3.0
    assert not find({"kind": "edge", "a": [0, 0, 0], "b": [1, 1, 1]})["resolved"]
    body = find({"kind": "object", "name": "foot"})
    assert body["parts"] == [0] and body["measure"] == {"volume_cm3": 2.24, "size": [10, 10, 22.4], "at": [0.0, 0.0, 11.2]}
    assert not find({"kind": "object", "name": "nobody"})["resolved"]


def test_a_group_is_found_when_all_of_it_is_and_measures_between_two():
    height = find({"kind": "group", "of": [{"kind": "planar_face", "normal": "-Z", "at": 0}, {"kind": "planar_face", "normal": "+Z", "at": 22.4}]})
    assert height["resolved"] and height["faces"] == [0, 1] and height["measure"] == {"count": 2, "area": 200.0, "distance": 22.4}
    diagonal = find({"kind": "group", "of": [{"kind": "point", "at": [-5, -5, 0]}, {"kind": "point", "at": [5, 5, 22.4]}]})
    assert diagonal["measure"]["distance"] == pytest.approx(26.4908)
    above = find({"kind": "group", "of": [{"kind": "point", "at": [5, 5, 22.4]}, {"kind": "planar_face", "normal": "-Z", "at": 0}]})
    assert above["measure"]["distance"] == pytest.approx(22.4)
    broken = find({"kind": "group", "of": [{"kind": "point", "at": [-5, -5, 0]}, {"kind": "point", "at": [50, 5, 22.4]}]})
    assert not broken["resolved"] and broken["why"] == "member 2 of 2 is not found" and "distance" not in broken["measure"]
    mixed = find({"kind": "group", "of": [{"kind": "edge", "a": [-5, -5, 0], "b": [5, -5, 0]}, {"kind": "object", "name": "foot"}, {"kind": "point", "at": [5, 5, 22.4]}]})
    assert mixed["resolved"] and (mixed["edges"], mixed["parts"], mixed["points"]) == ([0], [0], [1]) and mixed["measure"] == {"count": 3, "length": 10.0}
    assert "bad tag" in find({"kind": "group", "of": []})["why"]
    assert "bad tag" in find({"kind": "group", "of": [{"kind": "group", "of": []}]})["why"]


def test_a_sketch_lives_as_long_as_the_face_it_was_drawn_on():
    sketch = {"kind": "sketch", "plane": {"origin": [0, 0, 22.4], "normal": [0, 0, 1], "x": [1, 0, 0]},
              "curves": [{"type": "rect", "at": [-2, -2], "size": [4, 4]}, {"type": "polyline", "points": [[0, 0], [3, 0]]}],
              "on": {"kind": "planar_face", "normal": "+Z", "at": 22.4}}
    found = find(sketch)
    assert found["resolved"] and found["faces"] == [1] and found["measure"] == {"curves": 2, "closed": 1}
    moved = find({**sketch, "on": {"kind": "planar_face", "normal": "+Z", "at": 30}})
    assert not moved["resolved"] and "the face this was drawn on is not found" in moved["why"]
    assert find({k: v for k, v in sketch.items() if k != "on"})["resolved"]              # a free plane
    assert "bad tag" in find({"kind": "sketch", "curves": []})["why"]


def test_a_sketch_is_checked_before_it_is_kept():
    plane = {"origin": [0, 0, 22.4], "normal": [0, 0, 1], "x": [1, 0, 0]}
    kept = tags.clean_sketch({"plane": plane, "junk": 1, "on": {"kind": "planar_face", "normal": "+Z", "at": 22.4}, "curves": [
        {"type": "rect", "at": [-9.00004, -3], "size": [15, 7], "extra": True},
        {"type": "circle", "center": [13, 0], "r": 3},
        {"type": "polyline", "points": [[10, 2], [14, 2], [12, -2]], "closed": True},
        {"type": "polyline", "points": [[0, 0], [5, 5]], "closed": True}]})
    assert kept == {"plane": plane, "on": {"kind": "planar_face", "normal": "+Z", "at": 22.4}, "curves": [
        {"type": "rect", "at": [-9.0, -3.0], "size": [15.0, 7.0]}, {"type": "circle", "center": [13.0, 0.0], "r": 3.0},
        {"type": "polyline", "points": [[10.0, 2.0], [14.0, 2.0], [12.0, -2.0]], "closed": True},
        {"type": "polyline", "points": [[0.0, 0.0], [5.0, 5.0]], "closed": False}]}       # two points do not close
    assert "on" not in tags.clean_sketch({"plane": plane, "curves": [], "on": {"kind": "group", "of": []}})
    for bad in ({"curves": []}, {"plane": {**plane, "x": [1, 0]}, "curves": []}, {"plane": plane, "curves": [{"type": "spline"}]},
                {"plane": plane, "curves": [{"type": "rect", "at": [0, 0], "size": [0, 5]}]}, {"plane": plane, "curves": [{"type": "circle", "center": [0, 0], "r": -1}]},
                {"plane": plane, "curves": [{"type": "polyline", "points": [[0, 0]]}]}, {"plane": plane, "curves": [{"type": "rect", "at": [0, "x"], "size": [1, 1]}]}):
        with pytest.raises(ValueError):
            tags.clean_sketch(bad)


def test_whatever_is_selected_can_become_a_tag():
    items = [{"kind": "vertex", "at": [1, 2, 3]}, {"kind": "edge", "type": "circle", "c": [0, 0, 0], "r": 3, "a": [3, 0, 0], "b": [3, 0, 0]},
             {"kind": "edge", "type": "line", "a": [0, 0, 0], "b": [1, 0, 0]}, {"kind": "part", "name": "foot"}, {"kind": "face", **BLOCK["faces"][1]}]
    assert tags.propose_many(items[:1]) == {"kind": "point", "at": [1, 2, 3]}
    assert tags.propose_many(items) == {"kind": "group", "of": [
        {"kind": "point", "at": [1, 2, 3]}, {"kind": "edge", "center": [0, 0, 0], "radius": 3}, {"kind": "edge", "a": [0, 0, 0], "b": [1, 0, 0]},
        {"kind": "object", "name": "foot"}, {"kind": "planar_face", "normal": "+Z", "at": 22.4}]}
    with pytest.raises(ValueError):
        tags.propose_many([])


def test_the_measuring_geometry_of_the_canvas():
    """canvas/measure.js has its own tests, in node: run them from here so one command covers everything."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("no node on this machine")
    done = subprocess.run([node, "--test", str(Path(__file__).parent / "measure.test.mjs")], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-2000:]


RESULT = {"fingerprint": {"volume": 10476.0, "area": 7449.6, "bbox": [-22.5, -11.2, 0, 22.5, 11.2, 22.4], "com": [0, 0, 11.2], "solids": 1, "faces": 10},
          "valid": True, "tags": {"bore": {"resolved": True, "measure": {"width": 16.4, "through": True, "at": [0.0, 11.2]}}}}


def test_checks_pass_fail_and_cannot_be_measured():
    rows = feynman.evaluate([
        {"id": "w", "what": "tag.bore.width", "min": 16.2, "max": 16.4},
        {"id": "t", "what": "tag.bore.through", "equals": True},
        {"id": "big", "what": "volume_cm3", "min": 20},
        {"id": "bed", "what": "fits_bed"},
        {"id": "gone", "what": "tag.missing.width", "min": 1},
        {"id": "y", "what": "tag.bore.at[1]", "min": 11.1, "max": 11.3},
    ], RESULT, {"bed": [256, 256, 256]})
    assert [r["ok"] for r in rows] == [True, True, False, True, False, True]
    assert rows[4]["note"] == "tag not found on the part"
    assert not feynman.evaluate([{"id": "bed", "what": "fits_bed", "bed": [20, 20]}], RESULT)[0]["ok"]


def test_a_check_must_say_something():
    assert feynman.clean({"what": "size_x", "max": 5}, "agent") == {"id": "size-x", "what": "size_x", "max": 5.0, "why": "", "by": "agent"}
    for bad in ({}, {"what": "size_x"}, {"what": "size_x", "min": 3, "max": 1}, {"what": "size_x", "min": 1, "id": "Bad Id"}):
        with pytest.raises(ValueError):
            feynman.clean(bad, "user")


def test_load_check_green_yellow_red():
    saved = {"fingerprint": RESULT["fingerprint"], "tags": RESULT["tags"]}
    assert semmelweis.compare(saved, saved, 0.1)["status"] == "green"
    nudge = {"fingerprint": {**RESULT["fingerprint"], "bbox": [-22.5, -11.2, 0, 22.5, 11.2, 22.45]}, "tags": RESULT["tags"]}
    assert semmelweis.compare(saved, nudge, 0.1)["status"] == "yellow"
    grown = {"fingerprint": {**RESULT["fingerprint"], "bbox": [-22.5, -11.2, 0, 30.0, 11.2, 22.4]}, "tags": RESULT["tags"]}
    assert semmelweis.compare(saved, grown, 0.1)["status"] == "red"
    lost = {"fingerprint": RESULT["fingerprint"], "tags": {"bore": {"resolved": False, "measure": {}}}}
    r = semmelweis.compare(saved, lost, 0.1)
    assert r["status"] == "red" and r["changes"][0]["what"] == "tag bore"
    blind = {"fingerprint": RESULT["fingerprint"], "tags": {"bore": {"resolved": True, "measure": {"width": 16.4, "through": False, "at": [0.0, 11.2]}}}}
    assert semmelweis.compare(saved, blind, 0.1)["status"] == "red"
