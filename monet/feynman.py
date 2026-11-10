"""Feynman: the checks. You must not fool yourself, and you are the easiest person to fool.

A check is a named measurement and the range it must stay in. Checks live in
<note>.checks.json next to the Note, not in it: the agent writes Notes, the user owns
checks. Through the agent's door a check can be added, never changed or removed.

    {"id": "tunnel-width", "what": "tag.pipe_tunnel.width", "min": 16.2, "max": 16.4, "why": "16 mm pipe slides in"}
    {"id": "bed", "what": "fits_bed"}                        # the project's printer
    {"id": "one", "what": "solids", "equals": 1}

Measurements: volume_cm3, area_cm2, size_x/y/z, min_x..max_z, com_x/y/z, solids, faces,
valid, tag.<name>.resolved, tag.<name>.<measure> (lists as tag.<name>.at[0]); of an assembly
interference_mm3 (parts overlapping as built), and of each joint joint.<name>.resolved,
joint.<name>.stop_min / stop_max (where moving it first hits something, each way) and
joint.<name>.clash_mm3 (the worst new overlap anywhere in its range); joint.<name>.torque_max_nmm (force_max_n of a
slider: what gravity asks of it at worst) and joint.<name>.torque_margin (its DRIVES against that); of each named pose
(POSES) pose.<name>.interference_mm3, pose.<name>.clash_mm3 and pose.<name>.clear.<keepout>. mass_g (and
part.<name>.mass_g), from the materials; bom.unlisted (parts the BOM does not name); pieces (how many a part is printed
in: then fits_bed and solids hold for every piece).
"""
import json
import re
from pathlib import Path

from . import joints

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,47}$")


def measurements(result: dict) -> dict:
    """Every number a check can ask about, from one build result."""
    fp = result["fingerprint"]
    bb = fp["bbox"]
    m = {
        "volume_cm3": fp["volume"] / 1000.0, "area_cm2": fp["area"] / 100.0,
        "size_x": bb[3] - bb[0], "size_y": bb[4] - bb[1], "size_z": bb[5] - bb[2],
        "min_x": bb[0], "min_y": bb[1], "min_z": bb[2], "max_x": bb[3], "max_y": bb[4], "max_z": bb[5],
        "com_x": fp["com"][0], "com_y": fp["com"][1], "com_z": fp["com"][2],
        "solids": fp["solids"], "faces": fp["faces"], "valid": bool(result.get("valid", True)),
    }
    for name, tag in (result.get("tags") or {}).items():
        m[f"tag.{name}.resolved"] = bool(tag.get("resolved"))
        for k, v in (tag.get("measure") or {}).items():
            if isinstance(v, (list, tuple)):
                for i, x in enumerate(v):
                    m[f"tag.{name}.{k}[{i}]"] = x
            else:
                m[f"tag.{name}.{k}"] = v
    m.update(joints.measurements(result.get("motion")))
    mats = result.get("materials")
    if mats:
        m["mass_g"] = mats["mass_g"]
        for name, row in mats["parts"].items():
            if row["mass_g"] is not None and len(mats["parts"]) > 1:
                m[f"part.{name}.mass_g"] = row["mass_g"]
    if result.get("bom"):
        m["bom.unlisted"] = len(result["bom"]["unlisted"])
    pieces = result.get("pieces")
    if pieces:     # what is printed is the pieces: one solid each, and each on the bed
        m["pieces"] = len(pieces)
        m["solids"] = max(q["solids"] for q in pieces)
    return m


def _fits(size, bed) -> bool:
    x, y, z = size
    flat = (x <= bed[0] and y <= bed[1]) or (y <= bed[0] and x <= bed[1])
    return flat and (len(bed) < 3 or z <= bed[2])


def _fits_bed(m, check, printer, pieces=None):
    bed = check.get("bed") or (printer or {}).get("bed")
    if not bed:
        return False, None, "no bed size: give the check a bed or the project a printer"
    if pieces:      # printed in pieces: every one of them on the bed, as it lies; the value is the biggest
        sizes = [[q["bbox"][k + 3] - q["bbox"][k] for k in range(3)] for q in pieces]
        worst = max(sizes, key=lambda s: (not _fits(s, bed), s[0] * s[1] * s[2]))
        return all(_fits(s, bed) for s in sizes), [round(x, 2) for x in worst], f"bed {bed}, each of {len(pieces)} pieces"
    size = [m["size_x"], m["size_y"], m["size_z"]]
    return _fits(size, bed), [round(x, 2) for x in size], f"bed {bed}"


def evaluate(checks: list, result: dict, printer: dict | None = None) -> list:
    """Run every check against one build. A check that cannot be measured fails."""
    m = measurements(result)
    out = []
    for c in checks:
        what = c.get("what", "")
        row = {"id": c.get("id"), "what": what, "why": c.get("why", ""), "by": c.get("by", "user")}
        if what == "fits_bed":
            row["ok"], row["value"], row["expect"] = _fits_bed(m, c, printer, result.get("pieces"))
        elif what not in m:
            row.update(ok=False, value=None, expect=_expect(c),
                       note="tag not found on the part" if what.startswith("tag.")
                       else "nothing hit within the sweep" if re.match(r"^joint\.[^.]+\.stop_(min|max)$", what)
                       else "no such pose, or it is not resolved" if what.startswith("pose.")
                       else "nothing by that name to measure")
        else:
            v = m[what]
            ok = True
            if "equals" in c:
                ok = v == c["equals"] if isinstance(c["equals"], bool) or isinstance(v, bool) else abs(v - c["equals"]) <= 1e-9
            if "min" in c and c["min"] is not None:
                ok = ok and not isinstance(v, bool) and v >= c["min"]
            if "max" in c and c["max"] is not None:
                ok = ok and not isinstance(v, bool) and v <= c["max"]
            row.update(ok=bool(ok), value=round(v, 4) if isinstance(v, float) else v, expect=_expect(c))
        out.append(row)
    return out


def _expect(c):
    if "equals" in c:
        return f"= {c['equals']}"
    lo, hi = c.get("min"), c.get("max")
    if lo is not None and hi is not None:
        return f"{lo} … {hi}"
    return f"≥ {lo}" if lo is not None else f"≤ {hi}" if hi is not None else "?"


def clean(check: dict, by: str) -> dict:
    """A check as it is stored. Raises ValueError on a check that says nothing."""
    what = str(check.get("what", "")).strip()
    if not what:
        raise ValueError("a check needs `what`: the measurement it is about")
    out = {"id": str(check.get("id") or re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-"))[:48], "what": what}
    if not ID_RE.match(out["id"]):
        raise ValueError("a check id is lowercase letters, digits, dots, dashes or underscores")
    for k in ("min", "max"):
        if check.get(k) is not None:
            out[k] = float(check[k])
    if check.get("equals") is not None:
        out["equals"] = check["equals"]
    if what == "fits_bed":
        if check.get("bed"):
            out["bed"] = [float(x) for x in check["bed"]]
    elif not any(k in out for k in ("min", "max", "equals")):
        raise ValueError("a check needs a min, a max or an equals")
    if "min" in out and "max" in out and out["min"] > out["max"]:
        raise ValueError("min is above max")
    out["why"] = str(check.get("why", "")).strip()[:300]
    out["by"] = by
    return out


def load(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("checks", [])


def store(path: Path, checks: list) -> None:
    path.write_text(json.dumps({"checks": checks}, indent=1, ensure_ascii=False) + "\n")
