"""
Verify the rakis Notes against the Fusion model.

Builds every Note and compares bounding box, volume and surface area with
reference/mg400_rakis/F_report.json and measured_from_fusion.json.

Targets: bounding box within 0.05 mm, volume and area within 1 %.
Also: valid solid, single solid per printed part, TAGS resolve on the geometry,
pockets widen towards the top. Exit code is non-zero on any FAIL.

Run: cd <repo> && uv run python notes/mg400_rakis/_verify.py
"""
import ast
import importlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = HERE.parents[1] / "reference" / "mg400_rakis"
sys.path.insert(0, str(HERE))

from build123d import GeomType, Vector  # noqa: E402

BBOX_TOL = 0.05     # mm
REL_TOL = 1.0       # percent, volume and area
TAG_TOL = 0.01      # mm, TAGS literals are rounded to 2 decimals

# Note -> Fusion body it must match
NOTES = [
    ("nest_back", "nest_back"), ("nest_front", "nest_front"),
    ("grid_pos_0", "grid_pos_0"), ("grid_pos_1", "grid_pos_1"),
    ("grid_neg_0", "grid_neg_0"), ("grid_neg_1", "grid_neg_1"),
    ("l_bracket", "L_back_pos"),
]


def expected():
    """name -> dict(size_xy, z, vol, area); vol/area from the exact measurement where there is one."""
    rep = json.loads((REF / "F_report.json").read_text())
    meas = json.loads((REF / "measured_from_fusion.json").read_text())["bodies"]
    exp = {}
    for b in rep["bodies"]:
        m = meas.get(b["name"], {})
        exp[b["name"]] = dict(size_xy=b["size_xy"], z=b["z"],
                              vol=m.get("volume_cm3", b["volume_cm3"]), area=m.get("area_cm2"))
    return exp


def literal_tags(path):
    """TAGS as the loader will read it: a plain literal, parsed without running the file."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TAGS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("no TAGS in " + path.name)


AX = {"X": 0, "Y": 1, "Z": 2}


def has_planar_face(shape, axis, sign, at=None):
    for f in shape.faces():
        if f.geom_type != GeomType.PLANE:
            continue
        n, c = tuple(f.normal_at()), tuple(f.center())
        if abs(n[axis] * sign - 1) < 1e-6 and (at is None or abs(c[axis] - at) <= TAG_TOL):
            return True
    return False


def tag_problems(shape, tags):
    """Names of tags that do not resolve on the geometry."""
    bad = []
    solid = shape.solids()[0]
    bb = shape.bounding_box()
    lo, hi = tuple(bb.min), tuple(bb.max)
    for name, t in tags.items():
        ok = isinstance(t.get("role"), str)
        if t["kind"] == "planar_face":
            ok &= has_planar_face(shape, AX[t["normal"][1]], 1 if t["normal"][0] == "+" else -1, t.get("at"))
        elif t["kind"] == "square_hole":
            i = AX[t["axis"]]
            others = [a for a in (0, 1, 2) if a != i]
            half = t["size"] / 2
            for a, c in zip(others, t["at"]):          # four flat walls, normals pointing into the hole
                ok &= has_planar_face(shape, a, -1, c + half) and has_planar_face(shape, a, 1, c - half)
            free = []                                  # centre line, every mm: is it free of material?
            for k in range(int(hi[i] - lo[i])):
                pt = [0.0, 0.0, 0.0]
                pt[i], pt[others[0]], pt[others[1]] = lo[i] + 0.5 + k, t["at"][0], t["at"][1]
                free.append(not solid.is_inside(Vector(*pt)))
            # through: free all the way; blind: open at one end of the part, closed somewhere
            ok &= all(free) if t["through"] else ((free[0] or free[-1]) and not all(free))
        else:
            ok = False
        if not ok:
            bad.append(name)
    return bad


def pct(actual, exp):
    return 100.0 * (actual - exp) / exp


def measure(shape, exp, single_solid=True):
    """One table row (dict) for a built shape against its expected numbers."""
    bb = shape.bounding_box()
    size = (bb.size.X, bb.size.Y)
    z = (bb.min.Z, bb.max.Z)
    vol, area = shape.volume / 1000.0, shape.area / 100.0
    n_solids = len(shape.solids())
    fails = []
    if max(abs(a - e) for a, e in zip(size + z, exp["size_xy"] + exp["z"])) > BBOX_TOL:
        fails.append("bbox")
    dv = pct(vol, exp["vol"])
    if abs(dv) > REL_TOL:
        fails.append("volume")
    da = pct(area, exp["area"]) if exp["area"] else None
    if da is not None and abs(da) > REL_TOL:
        fails.append("area")
    if not shape.is_valid:
        fails.append("invalid")
    if single_solid and n_solids != 1:
        fails.append("%d solids" % n_solids)
    return dict(size=size, z=z, vol=vol, area=area, dv=dv, da=da, exp=exp, solids=n_solids, fails=fails)


def row(name, r, secs=None):
    e = r["exp"]
    return "%-14s %8.2f x %-7.2f (%6.2f x %-6.2f) %7.2f..%-5.2f (%6.2f..%-5.2f) %8.3f (%7.3f) %+7.3f%% %9.3f %-10s %-9s %-6s %s" % (
        name, r["size"][0], r["size"][1], e["size_xy"][0], e["size_xy"][1],
        r["z"][0], r["z"][1], e["z"][0], e["z"][1],
        r["vol"], e["vol"], r["dv"], r["area"],
        "(%8.3f)" % e["area"] if e["area"] else "(no ref)",
        "%+.3f%%" % r["da"] if r["da"] is not None else "-",
        "%.2f" % secs if secs is not None else "-",
        "PASS" if not r["fails"] else "FAIL: " + ", ".join(r["fails"]))


def main():
    exp = expected()
    failed = 0
    head = "%-14s %-18s %-17s %-14s %-15s %8s %9s %8s %9s %-10s %-9s %-6s %s" % (
        "name", "size_xy mm", "(expected)", "z mm", "(expected)", "vol cm3", "(exp)", "dev",
        "area cm2", "(exp)", "dev", "t s", "result")
    print(head)
    print("-" * len(head))

    # every Note on its own
    for note, body in NOTES:
        mod = importlib.import_module(note)
        t = time.perf_counter()
        shape = mod.build()
        secs = time.perf_counter() - t
        r = measure(shape, exp[body])
        bad = tag_problems(shape, literal_tags(HERE / (note + ".py")))
        if bad:
            r["fails"].append("tags: " + ", ".join(bad))
        failed += bool(r["fails"])
        print(row(note, r, secs))

    # the assembly: every Fusion body, by name
    rakis = importlib.import_module("rakis")
    t = time.perf_counter()
    asm = rakis.build()
    secs = time.perf_counter() - t
    print("\nrakis (assembly), built in %.2f s, %d children" % (secs, len(asm.children)))
    children = {c.label: c for c in asm.children}
    for name in exp:
        if name not in children:
            print("%-14s FAIL: missing from the assembly" % name)
            failed += 1
            continue
        r = measure(children[name], exp[name])
        failed += bool(r["fails"])
        print(row(name, r))
    extra = sorted(set(children) - set(exp))
    if extra:
        print("FAIL: children not in the Fusion model: " + ", ".join(extra))
        failed += 1

    # other checks
    print("\nchecks")
    checks = []
    nb, g0 = importlib.import_module("nest_back"), importlib.import_module("grid_pos_0")
    rc = importlib.import_module("rakis_common")
    L = rc.levels(rc.P)

    def width_at(shape, z_face):                       # x size of the flat face at height z
        f = [f for f in shape.faces() if f.geom_type == GeomType.PLANE and abs(f.center().Z - z_face) < 1e-6]
        return max(x.bounding_box().size.X for x in f)

    pocket = nb.pocket_cutter(rc.P, L)
    top, bot = width_at(pocket, L.z_top), width_at(pocket, 0.0)
    checks.append(("nest pocket widens towards the top: %.2f at z=0, %.2f at z_top (want 191.00, 231.00)"
                   % (bot, top), abs(bot - 191.0) < 0.01 and abs(top - 231.0) < 0.01))
    ramp = pocket.volume / 1000.0
    cell = g0.cell_cutter(rc.P, L)
    ctop, cbot = width_at(cell, L.z_top), width_at(cell, L.T - 1)
    checks.append(("grid pocket widens towards the top: %.2f at the bottom, %.2f at z_top (want 36.28, 41.98)"
                   % (cbot, ctop), abs(cbot - 36.28) < 0.01 and abs(ctop - 41.98) < 0.01))
    bb = asm.bounding_box()
    got = (bb.min.X, bb.max.X, bb.min.Y, bb.max.Y, bb.min.Z, bb.max.Z)
    want = (L.x_edge_f - rc.P["L_lip"], L.x_edge_b + rc.P["L_lip"], -rc.P["half_w"], rc.P["half_w"],
            L.T - rc.P["L_drop"], L.z_top)
    checks.append(("assembly extent x %.2f..%.2f, y %.2f..%.2f, z %.2f..%.2f" % got,
                   max(abs(a - b) for a, b in zip(got, want)) < BBOX_TOL))
    checks.append(("assembly has the 14 bodies of the Fusion model", len(children) == 14 and not extra))
    for text, ok in checks:
        failed += not ok
        print("  %-4s %s" % ("PASS" if ok else "FAIL", text))
    print("  info nest pocket cutter volume %.3f cm3" % ramp)

    print("\n%s" % ("ALL PASS" if not failed else "%d FAILED" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
