"""Feynman: the checks. You must not fool yourself, and you are the easiest person to fool.

A check is a named measurement and the range it must stay in. Checks live in
<note>.checks.json next to the Note, not in it: the agent writes Notes, the user owns
checks. Through the agent's door a check can be added, never changed or removed.

    {"id": "tunnel-width", "what": "tag.pipe_tunnel.width", "min": 16.2, "max": 16.4, "why": "16 mm pipe slides in"}
    {"id": "bed", "what": "fits_bed"}                        # the project's printer
    {"id": "one", "what": "solids", "equals": 1}

Measurements: volume_cm3, area_cm2, size_x/y/z, min_x..max_z, com_x/y/z, solids, faces,
valid, tag.<name>.resolved, tag.<name>.<measure> (lists as tag.<name>.at[0]).
"""
import json
import re
from pathlib import Path

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
    return m


def _fits_bed(m, check, printer):
    bed = check.get("bed") or (printer or {}).get("bed")
    if not bed:
        return False, None, "no bed size: give the check a bed or the project a printer"
    x, y, z = m["size_x"], m["size_y"], m["size_z"]
    flat = (x <= bed[0] and y <= bed[1]) or (y <= bed[0] and x <= bed[1])
    ok = flat and (len(bed) < 3 or z <= bed[2])
    return ok, [round(x, 2), round(y, 2), round(z, 2)], f"bed {bed}"


def evaluate(checks: list, result: dict, printer: dict | None = None) -> list:
    """Run every check against one build. A check that cannot be measured fails."""
    m = measurements(result)
    out = []
    for c in checks:
        what = c.get("what", "")
        row = {"id": c.get("id"), "what": what, "why": c.get("why", ""), "by": c.get("by", "user")}
        if what == "fits_bed":
            row["ok"], row["value"], row["expect"] = _fits_bed(m, c, printer)
        elif what not in m:
            row.update(ok=False, value=None, expect=_expect(c),
                       note="tag not found on the part" if what.startswith("tag.") else "nothing by that name to measure")
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
