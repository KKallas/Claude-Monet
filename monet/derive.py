"""A build's tags and joints, found from what the build left: its faces, edges, points and parts (faces.json), its
bounding box and its preview mesh. No CAD kernel and no Note: the runner asks this right after a build, and the
server asks it again when the person tags a face or makes a joint in the canvas, which changes no geometry.

Snap points (a Note's SNAPS: where other Notes may be put, as the centre of every cell of a grid) and the instances
put at them (PLACED) are read here too: an instance rides the body its snap point is on."""
import math
import re
import time

from . import joints, rays, tags


MAX_SNAPS = 2000
SNAP_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def clean_snaps(raw) -> dict:
    """A Note's SNAPS as a build records them: {name: {"at": [x, y, z], "turn": degrees about Z, "on": part or None}}.
    ValueError says what is wrong."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_SNAPS:
        raise ValueError(f"SNAPS is a dict of at most {MAX_SNAPS} snap points: {{name: {{at: [x, y, z], turn, on}}}}")
    out = {}
    for name, s in raw.items():
        if not isinstance(name, str) or not SNAP_NAME.match(name) or not isinstance(s, dict):
            raise ValueError(f"snap {name!r}: a name of letters, digits, _ . -, and {{at: [x, y, z], turn, on}}")
        at, turn, on = s.get("at"), s.get("turn", 0), s.get("on")
        if not isinstance(at, (list, tuple)) or len(at) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in at):
            raise ValueError(f"snap {name!r}: at is [x, y, z] in mm")
        if isinstance(turn, bool) or not isinstance(turn, (int, float)) or not math.isfinite(turn):
            raise ValueError(f"snap {name!r}: turn is degrees about Z")
        if on is not None and (not isinstance(on, str) or not 0 < len(on) <= 120):
            raise ValueError(f"snap {name!r}: on is the name of the part it is on")
        out[name] = {"at": [round(float(v), 4) for v in at], "turn": round(float(turn), 4), "on": on}
    return out


def attached(spec: dict, placed: dict, snaps: dict, part_names: list) -> dict:
    """JOINTS with every instance put at a snap point (PLACED) held on the body that point is on: its parts made one
    rigid group, fixed there. An instance the person already put in a group of their own is left as it is."""
    spec = dict(spec or {})
    groups = {n: j for n, j in spec.items() if isinstance(j, dict) and j.get("kind") == "rigid" and j.get("parts")}
    grouped = {q for j in groups.values() for q in j["parts"]}
    for name, p in (placed or {}).items():
        mine = [q for q in part_names if q == name or q.startswith(name + "/")]
        snap = (snaps or {}).get(p.get("at")) if isinstance(p, dict) else None
        if not mine or not snap or not snap.get("on") or grouped & set(mine):
            continue
        owner = next((g for g, j in groups.items() if snap["on"] in j["parts"]), snap["on"])
        spec[f"{name}_placed"] = {"kind": "rigid", "parts": mine}
        spec[f"{name}_on"] = {"kind": "rigid", "moves": f"{name}_placed", "on": owner}
    return spec


def found(literals: dict, bbox, geo: dict, verts, tris, snaps: dict | None = None) -> tuple:
    """(tags found, motion or None). literals: the Note's {"tags", "joints", "ground", "tips", "placed"}; geo:
    faces.json; snaps: the build's snap points."""
    parts = geo["parts"]
    got = tags.resolve(literals.get("tags") or {}, geo["faces"], bbox, blocked=rays.crossing(verts, tris),
                       edges=geo.get("edges"), points=geo.get("points"), parts=parts)
    spec = attached(literals.get("joints") or {}, literals.get("placed") or {}, snaps or {}, [p["name"] for p in parts])
    if len(parts) < 2 and not spec:
        return got, None
    t0 = time.time()
    model = joints.resolve(spec, literals.get("ground"), [p["name"] for p in parts], literals.get("tags") or {}, got,
                           geo["faces"], literals.get("tips") or {})
    model.update(joints.analyse(model, joints.solids(verts, tris, parts)))
    model["seconds"] = round(time.time() - t0, 2)
    return got, model
