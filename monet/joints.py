"""Joints: how the parts of an assembly may still move, from where build() put them.

An assembly Note places every part as built. JOINTS only says which way a part may still
move from there and how far, so every joint is an "as-built" joint: no snapping parts
together, no solver. A part that no joint names is free; GROUND is what never moves.

    GROUND = "rails"
    JOINTS = {
        "rails": {"kind": "rigid", "parts": ["L_back_pos", "pipe_long_pos"]},     # a rigid group: one body
        "slide": {"kind": "slider", "moves": "top", "on": "rails", "axis": "pipe_tunnel", "range": [-79, 0]},
        "lever": {"kind": "revolute", "moves": "lever", "on": "jaw", "axis": {"origin": [0, 0, 12], "dir": "Y"}, "range": [0, 110]},
        "rod": {"kind": "revolute", "moves": "rod", "on": "base", "axis": "rod_pin", "follows": {"lever": -1}},
    }

- kind: rigid (no movement; with `parts` it makes a group that moves as one), revolute (turns about
  the axis, degrees, right hand about `dir`), slider (moves along the axis, mm). Every value is 0 as built.
- moves / on: bodies: a rigid group by its name, or a part of the assembly by its name.
- axis: a tag of the assembly (a round or square hole, a boss: its centre line; a flat face: its normal
  through its middle; a group of two points: the line from the first to the second), or
  {"origin": [x, y, z], "dir": "X" | "-Z" | [x, y, z]}. "flip": true turns the positive way round.
- range: [lo, hi], where the joint may go. locked: true holds it where it is.
- follows: {joint: factor, ...}: this joint's value is the sum of those joints' values times the
  factors. Gears, rack and pinion, and the parallelograms of a robot arm (each link follows a
  combination of the motors), without solving a loop.

The joints form a tree from the ground: each body is moved by at most one joint. Everything here
is plain data and numpy; the clash sweeps need manifold3d (meshes in, volumes out).

    TIPS = {"nose": {"on": "tool", "at": [278.42, 0, 352.25]}}

A tip is a point on a part (`at`: where it is as built) that can be led somewhere: solve() finds the
values of the joints moved by hand that put it there, within their ranges (inverse kinematics). The
canvas does the same, live, when the tip is dragged (canvas/motion.js).
"""
import math

import numpy as np

KINDS = ("rigid", "revolute", "slider")
UNIT = {"revolute": "°", "slider": "mm"}
AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
CLASH = 1.0          # mm³ of new overlap between two parts before it counts as a clash (touching is not)
NOISE = 0.05         # and, where two parts overlap as built (a pin in its hole), this much of that more: a faceted pin
                     # turning in a faceted hole overlaps it a little more or less at every step
STEP = 1.0           # mm: how far the farthest moving point goes between two looks during a sweep
EXACT = 0.01         # mm or degrees: how closely a stop is found
MAX_SAMPLES = 1500   # per direction of a sweep


def _dir(spec):
    if isinstance(spec, str):
        s = spec.strip().upper()
        sign = -1.0 if s.startswith("-") else 1.0
        v = AXES.get(s.lstrip("+-"))
        if v is None:
            raise ValueError(f"dir {spec!r}: use X, Y, Z, -X, -Y, -Z or [x, y, z]")
        return np.array(v) * sign
    v = np.array([float(x) for x in spec], dtype=float)
    if v.shape != (3,) or not np.all(np.isfinite(v)) or np.linalg.norm(v) < 1e-9:
        raise ValueError(f"dir {spec!r}: three numbers, not all zero")
    return v / np.linalg.norm(v)


def _axis_of_tag(name, tags, found, faces):
    """(origin, dir) of a tag that has a line to it, from what the build found."""
    tag, hit = (tags or {}).get(name), (found or {}).get(name)
    if not tag:
        raise ValueError(f"there is no tag {name!r} in this Note")
    if not hit or not hit.get("resolved"):
        raise ValueError(f"the tag {name!r} is not found on the build" + (f": {hit['why']}" if hit and hit.get("why") else ""))
    kind, ids = tag.get("kind"), hit.get("faces") or []
    fs = [faces[i] for i in ids if 0 <= i < len(faces)]
    if kind in ("square_hole", "round_hole", "boss"):
        a = "XYZ".index(str(tag.get("axis", "Z")).upper().lstrip("+-"))
        u, v = [k for k in range(3) if k != a]
        at = hit["measure"]["at"]
        lo = min(f["bbox"][a] for f in fs) if fs else 0.0
        hi = max(f["bbox"][a + 3] for f in fs) if fs else 0.0
        origin = np.zeros(3)
        origin[a], origin[u], origin[v] = (lo + hi) / 2, at[0], at[1]
        return origin, np.array(AXES["XYZ"[a]])
    if kind == "planar_face":
        if not fs:
            raise ValueError(f"the tag {name!r} has no faces")
        return np.mean([f["center"] for f in fs], axis=0), np.array(fs[0]["normal"], dtype=float)
    if kind == "group":
        pts = [s.get("at") for s in tag.get("of") or [] if s.get("kind") == "point"]
        if len(pts) == 2 and len(tag["of"]) == 2:
            a, b = np.array(pts[0], dtype=float), np.array(pts[1], dtype=float)
            if np.linalg.norm(b - a) < 1e-6:
                raise ValueError(f"the two points of {name!r} are in one place: no line between them")
            return a, (b - a) / np.linalg.norm(b - a)
    raise ValueError(f"the tag {name!r} ({kind}) has no line to turn about or slide along: use a hole, a boss, a flat face or two points")


def _axis(joint, tags, found, faces):
    spec = joint.get("axis")
    if spec is None:
        raise ValueError("a joint that moves needs an axis")
    if isinstance(spec, str) and spec.upper().lstrip("+-") in AXES:
        origin, d = np.zeros(3), _dir(spec)
    elif isinstance(spec, str):
        origin, d = _axis_of_tag(spec, tags, found, faces)
    elif isinstance(spec, dict):
        o = spec.get("origin", [0, 0, 0])
        origin = np.array([float(x) for x in o], dtype=float)
        if origin.shape != (3,):
            raise ValueError("an axis origin is [x, y, z]")
        d = _dir(spec.get("dir", "Z"))
    else:
        raise ValueError(f"axis {spec!r}: a tag's name, or {{origin, dir}}")
    if joint.get("flip"):
        d = -d
    return origin, d / np.linalg.norm(d)


def _range(joint):
    r = joint.get("range")
    if r is None:
        return None
    if not isinstance(r, (list, tuple)) or len(r) != 2 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in r):
        raise ValueError("a range is [lo, hi]")
    lo, hi = float(r[0]), float(r[1])
    if lo > hi:
        raise ValueError("a range is [lo, hi], lo first")
    return [lo, hi]


def resolve(joints: dict, ground, part_names: list, tags: dict | None = None, found: dict | None = None, faces: list | None = None,
            tips: dict | None = None) -> dict:
    """The motion of an assembly as plain data: bodies, joints with their axes in the assembly's frame, the order
    to place them in, and every problem found. Never raises: a broken joint is told, not thrown."""
    joints, problems = dict(joints or {}), []
    known = set(part_names)
    bodies, body_of = {}, {}
    for name, j in joints.items():
        if not isinstance(j, dict) or j.get("kind") not in KINDS:
            problems.append(f"{name}: kind is one of {', '.join(KINDS)}")
            continue
        if j["kind"] == "rigid" and j.get("parts") is not None:
            if name in known:
                problems.append(f"{name}: a rigid group may not be named like a part")
                continue
            members = []
            for p in j.get("parts") or []:
                if p not in known:
                    problems.append(f"{name}: there is no part {p!r} in this assembly")
                elif p in body_of:
                    problems.append(f"{name}: {p} is in the group {body_of[p]} already")
                else:
                    members.append(p)
                    body_of[p] = name
            bodies[name] = members
    for p in part_names:
        if p not in body_of:
            bodies[p], body_of[p] = [p], p

    ground = [ground] if isinstance(ground, str) else list(ground or [])
    for g in ground:
        if g not in bodies:
            problems.append(f"GROUND: there is no body {g!r}: name a part or a rigid group")
    ground = [g for g in ground if g in bodies]

    out, parent = {}, {}
    for name, j in joints.items():
        if not isinstance(j, dict) or j.get("kind") not in KINDS or (j["kind"] == "rigid" and j.get("parts") is not None):
            continue
        row = {"kind": j["kind"], "moves": j.get("moves"), "on": j.get("on"), "unit": UNIT.get(j["kind"], ""),
               "range": None, "follows": None, "locked": bool(j.get("locked")), "resolved": True}
        why = []
        for side in ("moves", "on"):
            if row[side] not in bodies:
                why.append(f"{side}: there is no body {row[side]!r}")
        if row["moves"] == row["on"]:
            why.append("a body cannot move on itself")
        if row["moves"] in ground:
            why.append(f"{row['moves']} is the ground: it does not move")
        if row["moves"] in parent and not why:
            why.append(f"{row['moves']} is moved by {parent[row['moves']]} already: a body hangs on one joint (a loop is made with follows)")
        if j["kind"] != "rigid":
            try:
                origin, d = _axis(j, tags, found, faces or [])
                row["origin"], row["dir"] = [round(float(x), 6) for x in origin], [round(float(x), 9) for x in d]
            except (ValueError, KeyError, IndexError, TypeError) as e:
                why.append(f"axis: {e}")
            try:
                row["range"] = _range(j)
            except ValueError as e:
                why.append(str(e))
            if j.get("follows") is not None:
                f = j["follows"]
                if not isinstance(f, dict) or not f or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in f.values()):
                    why.append("follows is {joint: factor, ...}")
                else:
                    row["follows"] = {str(k): float(v) for k, v in f.items()}
        if why:
            row.update(resolved=False, why="; ".join(why))
        elif row["moves"] not in parent:
            parent[row["moves"]] = name
        out[name] = row

    # follows: only joints that move, and no circles
    for name, row in out.items():
        for k in (row["follows"] or {}):
            other = out.get(k)
            if k == name or other is None or other["kind"] == "rigid":
                row.update(resolved=False, why=(row.get("why", "") + "; " if row.get("why") else "") + f"follows {k!r}: no such joint that moves")
    order_f, state = [], {}

    def visit(n, trail):
        if state.get(n) == 2:
            return True
        if state.get(n) == 1:
            problems.append(f"follows go round in a circle: {' → '.join(trail + [n])}")
            return False
        state[n] = 1
        ok = all(visit(k, trail + [n]) for k in (out[n]["follows"] or {}) if k in out)
        state[n] = 2
        order_f.append(n)
        return ok
    for n in out:
        if out[n]["kind"] != "rigid":
            visit(n, [])

    # the tree: from each body up to where it hangs, never round in a circle
    depth = {}
    for b in bodies:
        seen, cur = [], b
        while cur in parent and cur not in seen:
            seen.append(cur)
            cur = out[parent[cur]]["on"]
        if cur in parent:
            problems.append(f"the joints go round in a circle: {' → '.join(seen + [cur])}")
            for x in seen:
                parent.pop(x, None)
        depth[b] = len(seen)
    tree = sorted(parent, key=lambda b: depth.get(b, 0))
    free = [b for b in bodies if b not in ground and b not in parent]
    body_of = {p: b for b, ps in bodies.items() for p in ps}
    found_tips = {}
    for name, t in (tips or {}).items():
        on, at = (t or {}).get("on"), (t or {}).get("at")
        row = {"on": on, "body": body_of.get(on, on if on in bodies else None), "resolved": True}
        if row["body"] is None:
            row.update(resolved=False, why=f"there is no part or body {on!r}")
        try:
            row["at"] = [float(x) for x in at]
            if len(row["at"]) != 3 or not all(math.isfinite(x) for x in row["at"]):
                raise ValueError
        except (TypeError, ValueError):
            row.update(resolved=False, at=None, why="at is [x, y, z]: where the tip is as built")
        found_tips[name] = row
    return {"ok": not problems and all(r["resolved"] for r in out.values()) and all(t["resolved"] for t in found_tips.values()),
            "problems": problems, "ground": ground, "bodies": bodies, "free": free, "joints": out, "tips": found_tips,
            "tree": [parent[b] for b in tree], "follow_order": [n for n in order_f if out[n]["resolved"]]}


def rotation(origin, d, degrees):
    """4x4: a turn about the line through origin along d, right hand."""
    a = math.radians(degrees)
    x, y, z = d
    c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
    R = np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                  [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                  [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(origin) - R @ np.asarray(origin)
    return T


def values(model: dict, given: dict | None = None) -> dict:
    """Every joint's value: the ones given (the drivers), followers worked out from them, the rest 0."""
    given = given or {}
    out = {}
    for name, row in model["joints"].items():
        if row["kind"] == "rigid" or not row["resolved"]:
            out[name] = 0.0
        elif not row["follows"]:
            out[name] = float(given.get(name, 0.0))
    for name in model["follow_order"]:
        row = model["joints"][name]
        if row["follows"]:
            out[name] = sum(f * out.get(k, 0.0) for k, f in row["follows"].items())
    return out


def frames(model: dict, given: dict | None = None, free: dict | None = None) -> dict:
    """{body: 4x4} where each body is at these joint values (as built: the identity). `free` places free bodies
    (a dragged part): {body: 4x4}."""
    v = values(model, given)
    out = {b: np.array((free or {}).get(b, np.eye(4)), dtype=float) for b in model["bodies"]}
    for name in model["tree"]:
        row = model["joints"][name]
        T = np.eye(4)
        if row["kind"] == "revolute":
            T = rotation(row["origin"], row["dir"], v[name])
        elif row["kind"] == "slider":
            T[:3, 3] = np.asarray(row["dir"]) * v[name]
        out[row["moves"]] = out[row["on"]] @ T
    return out


def part_frames(model: dict, given: dict | None = None, free: dict | None = None) -> dict:
    """{part: 4x4}."""
    fb = frames(model, given, free)
    return {p: fb[b] for b, ps in model["bodies"].items() for p in ps}


def drivers(model: dict) -> list:
    """The joints that are moved by hand: they move, they are found, they follow nothing."""
    return [n for n, r in model["joints"].items() if r["kind"] != "rigid" and r["resolved"] and not r["follows"]]


def tip_at(model: dict, tip: str, given: dict | None = None) -> list:
    """Where a tip is with the joints at these values."""
    t = model["tips"][tip]
    return (frames(model, given)[t["body"]] @ [*t["at"], 1.0])[:3].tolist()


def solve(model: dict, tip: str, target, start: dict | None = None, iterations: int = 200) -> dict:
    """Inverse kinematics: the values of the joints moved by hand (and not locked) that put the tip at target,
    starting from `start` (the pose it is in) and never leaving a joint's range. Damped least squares on the
    joints' own frames, so whatever the joints are (and whatever follows them) it is the same motion as posing.
    Out of reach, it stops where the tip comes nearest: `off` says how far that is. Same as solve() in
    canvas/motion.js, step for step."""
    t = model["tips"].get(tip)
    if not t or not t["resolved"]:
        raise ValueError(f"no tip {tip!r}" + (f": {t['why']}" if t else f"; there are: {', '.join(model['tips']) or 'none'}"))
    names = [n for n in drivers(model) if not model["joints"][n]["locked"]]
    start = dict(start or {})
    q = np.array([float(start.get(n, 0.0)) for n in names])
    spans = [model["joints"][n]["range"] or ((-180.0, 180.0) if model["joints"][n]["kind"] == "revolute" else (-1e6, 1e6)) for n in names]
    lo, hi = np.array([a for a, _ in spans]), np.array([b for _, b in spans])
    q = np.clip(q, lo, hi)
    goal = np.asarray(target, dtype=float)

    def at(x):
        return np.asarray(tip_at(model, tip, {**start, **dict(zip(names, x))}))
    best, damping = None, 1.0
    for k in range(iterations):
        here = at(q)
        e = goal - here
        if best is None or np.linalg.norm(e) < best[1]:
            best = (q.copy(), float(np.linalg.norm(e)))
        if np.linalg.norm(e) < 1e-4:
            break
        J = np.column_stack([(at(q + np.eye(len(q))[i] * 1e-3) - here) / 1e-3 for i in range(len(q))])
        step = J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(3), e)
        big = np.abs(step).max()
        if big > 10:          # at most 10 degrees (or mm) a step: far targets are walked to, not jumped at
            step *= 10 / big
        q = np.clip(q + step, lo, hi)
    q, off = best
    return {"values": {**{n: round(float(start.get(n, 0.0)), 4) for n in drivers(model)}, **{n: round(float(v), 4) for n, v in zip(names, q)}},
            "tip": [round(x, 4) for x in at(q).tolist()], "off": round(off, 4), "reached": off <= 0.05}


# ---- clashes: meshes in, volumes out --------------------------------------------------------------------------

def solids(verts, tris, parts) -> dict:
    """{part name: manifold3d.Manifold or None} from one build's mesh (parts are ranges of its triangles). A part
    whose mesh is not closed cannot be told apart inside from outside, and is None."""
    import manifold3d as mf
    verts, tris = np.asarray(verts, dtype=np.float64).reshape(-1, 3), np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    out = {}
    for p in parts:
        start, n = p["tris"]
        t = tris[start:start + n]
        if not len(t):
            out[p["name"]] = None
            continue
        # the runner writes each face with vertices of its own: weld them where they meet
        used, inverse = np.unique(t.reshape(-1), return_inverse=True)
        pts = np.round(verts[used], 4)
        uniq, back = np.unique(pts, axis=0, return_inverse=True)
        faces = back.reshape(-1)[inverse].reshape(-1, 3)
        faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
        m = mf.Manifold(mf.Mesh(vert_properties=uniq.astype(np.float32), tri_verts=faces.astype(np.uint32)))
        out[p["name"]] = m if m.status() == mf.Error.NoError and m.volume() > 0 else None
    return out


def _moved(shapes, pf):
    out = {}
    for name, m in shapes.items():
        if m is None:
            continue
        T = pf.get(name)
        out[name] = m if T is None or np.allclose(T, np.eye(4)) else m.transform(np.asarray(T)[:3, :].tolist())
    return out


def _apart(a, b):
    return any(a[k] > b[k + 3] or b[k] > a[k + 3] for k in range(3))


def overlaps(placed: dict, pairs) -> dict:
    """{(a, b): mm³ of material both take up}, for the pairs whose boxes meet."""
    boxes = {n: m.bounding_box() for n, m in placed.items() if m is not None}
    out = {}
    for a, b in pairs:
        if a in boxes and b in boxes and not _apart(boxes[a], boxes[b]):
            v = (placed[a] ^ placed[b]).volume()
            if v > 1e-6:
                out[(a, b)] = v
    return out


def _excess(now: dict, home: dict) -> list:
    """[[a, b, mm³]]: the pairs that overlap more than they did as built, by more than the noise of their facets."""
    out = []
    for k, v in now.items():
        extra = v - home.get(k, 0.0)
        if extra > CLASH + NOISE * home.get(k, 0.0):
            out.append([k[0], k[1], round(extra, 3)])
    return sorted(out, key=lambda r: -r[2])


def _turns_about(T, box) -> bool:
    """Does the rigid motion T turn about a line through this box (a pin through where two parts overlap), without
    sliding along it?"""
    R, t = np.asarray(T)[:3, :3], np.asarray(T)[:3, 3]
    angle = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))
    if angle < 1e-6:
        return False
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    if np.linalg.norm(w) < 1e-9:       # half a turn: the axis is where R leaves a line in place
        vals, vecs = np.linalg.eigh((R + np.eye(3)) / 2)
        w = vecs[:, int(np.argmax(vals))]
    w = w / np.linalg.norm(w)
    if abs(float(np.dot(t, w))) > 0.01:
        return False
    point = np.linalg.lstsq(np.eye(3) - R, t, rcond=None)[0]
    c, half = (np.asarray(box[:3]) + box[3:]) / 2, np.linalg.norm(np.asarray(box[3:]) - box[:3]) / 2
    off = c - point
    return float(np.linalg.norm(off - np.dot(off, w) * w)) <= half + 0.5


def pinned(model: dict, shapes: dict, home: dict, poses) -> set:
    """The pairs of parts that turn on a pin: overlapping as built (the pin drawn in its hole), and at every one of
    these poses turned against each other about a line through that overlap (joined by a revolute joint, or
    closing a loop, as the far pin of a parallelogram). However they turn, that is the pin in its hole."""
    out = set()
    for (a, b), v in home.items():
        if v <= 0:
            continue
        box = (shapes[a] ^ shapes[b]).bounding_box()
        rel = [np.linalg.inv(pf.get(b, np.eye(4))) @ pf.get(a, np.eye(4)) for pf in poses]
        if all(_turns_about(T, box) or np.allclose(T, np.eye(4)) for T in rel) and not all(np.allclose(T, np.eye(4)) for T in rel):
            out.add((a, b))
    return out


def interference(shapes: dict) -> dict:
    """Where parts take up the same material as built (pins in their holes too: they are listed, not clashes)."""
    names = [n for n, m in shapes.items() if m is not None]
    hit = overlaps(shapes, [(a, b) for i, a in enumerate(names) for b in names[i + 1:]])
    pairs = sorted(([a, b, round(v, 3)] for (a, b), v in hit.items() if v > CLASH / 2), key=lambda r: -r[2])
    return {"total_mm3": round(sum(r[2] for r in pairs), 3), "pairs": pairs}


def sweep(model: dict, shapes: dict, joint: str, home: dict | None = None) -> dict:
    """Move one joint (and what follows it) through its range and a little past both ends, the others as built.
    A clash is new overlap between two parts that move against each other (what overlapped as built already is
    the interference's to report). Gives where it first hits each way (stop_min, stop_max), the worst overlap
    inside the range (clash_mm3), and the stretches where it clashes."""
    row = model["joints"][joint]
    rng = row["range"]
    if rng is None and row["kind"] == "slider":
        return {"skipped": "no range: give the slider a range to have it checked"}
    lo, hi = rng if rng else (-180.0, 180.0)
    past = 0.0 if rng is None else max(5.0, 0.1 * (hi - lo))
    a, b = lo - past, hi + past
    names = [n for n, m in shapes.items() if m is not None]
    probe = [part_frames(model, {joint: x}) for x in (a or -1.0, b or 1.0)]
    moving = [n for n in names if any(not np.allclose(pf.get(n, np.eye(4)), np.eye(4)) for pf in probe)]
    pairs = [(p, q) for i, p in enumerate(names) for q in names[i + 1:]
             if (p in moving or q in moving) and any(not np.allclose(pf.get(p, np.eye(4)), pf.get(q, np.eye(4))) for pf in probe)]
    if not pairs:
        return {"stop_min": None, "stop_max": None, "clash_mm3": 0.0, "clashes": [], "looked": 0}
    if home is None:
        home = overlaps(shapes, pairs)
    pins = pinned(model, shapes, home, probe)
    pairs = [k for k in pairs if k not in pins]
    if not pairs:
        return {"stop_min": None, "stop_max": None, "clash_mm3": 0.0, "clashes": [], "looked": 0}
    if row["kind"] == "revolute":
        reach = 1.0
        for n in moving:
            bb = shapes[n].bounding_box()
            for c in ((x, y, z) for x in (bb[0], bb[3]) for y in (bb[1], bb[4]) for z in (bb[2], bb[5])):
                p = np.asarray(c) - row["origin"]
                reach = max(reach, float(np.linalg.norm(p - np.dot(p, row["dir"]) * np.asarray(row["dir"]))))
        step = min(2.0, max(0.25, math.degrees(STEP / reach)))
    else:
        step = STEP
    looked = [0]

    def at(x):
        looked[0] += 1
        who = _excess(overlaps(_moved(shapes, part_frames(model, {joint: x})), pairs), home)
        return (who[0][2] if who else 0.0), who

    def edge(x_ok, x_bad):      # where between a free place and a clashing one the clash begins
        while abs(x_bad - x_ok) > EXACT:
            mid = (x_ok + x_bad) / 2
            if at(mid)[1]:
                x_bad = mid
            else:
                x_ok = mid
        return x_bad

    out = {"stop_min": None, "stop_max": None, "clash_mm3": 0.0, "clashes": []}
    worst_at = None
    for sign, end in ((1, b), (-1, a)):
        if sign * end <= 0:
            continue
        x, clashing, since = 0.0, False, None
        n = min(MAX_SAMPLES, max(1, math.ceil(abs(end) / step)))
        for k in range(1, n + 1):
            nx = end * k / n
            worst, who = at(nx)
            if lo - 1e-9 <= nx <= hi + 1e-9 and worst > out["clash_mm3"]:
                out["clash_mm3"], worst_at = worst, (nx, who)
            bad = bool(who)
            if bad and not clashing:
                since = edge(x, nx)
                key = "stop_max" if sign > 0 else "stop_min"
                if out[key] is None:
                    out[key] = round(since, 3)
                clashing, first = True, who
            elif not bad and clashing:
                out["clashes"].append(sorted([round(since, 3), round(edge(nx, x), 3)]) + [first])
                clashing = False
            x = nx
        if clashing:
            out["clashes"].append(sorted([round(since, 3), round(end, 3)]) + [first])
    out["clash_mm3"] = round(out["clash_mm3"], 3)
    if worst_at:
        out["worst"] = {"at": round(worst_at[0], 3), "pairs": worst_at[1]}
    out["clashes"].sort(key=lambda c: c[0])
    out["searched"] = [round(a, 3), round(b, 3)]
    out["looked"] = looked[0]
    return out


def analyse(model: dict, shapes: dict) -> dict:
    """Interference as built, and a sweep of every joint moved by hand."""
    out = {"interference": interference(shapes), "unchecked": sorted(n for n, m in shapes.items() if m is None), "sweeps": {}}
    for name in drivers(model):
        out["sweeps"][name] = sweep(model, shapes, name)
    return out


def pose_clashes(model: dict, shapes: dict, given: dict | None = None, free: dict | None = None) -> list:
    """[[a, b, mm³]]: the new overlaps at one pose, over what overlapped as built."""
    names = [n for n, m in shapes.items() if m is not None]
    pf = part_frames(model, given, free)
    pairs = [(p, q) for i, p in enumerate(names) for q in names[i + 1:]
             if not np.allclose(pf.get(p, np.eye(4)), pf.get(q, np.eye(4)))]
    home = overlaps(shapes, pairs)
    pins = pinned(model, shapes, home, [pf])
    pairs = [k for k in pairs if k not in pins]
    return _excess(overlaps(_moved(shapes, pf), pairs), home)


def measurements(motion: dict) -> dict:
    """The numbers a check can hold: joint.<name>.<measure> and interference_mm3."""
    m = {}
    if not motion:
        return m
    if "interference" in motion:
        m["interference_mm3"] = motion["interference"]["total_mm3"]
    for name, row in (motion.get("joints") or {}).items():
        m[f"joint.{name}.resolved"] = bool(row.get("resolved"))
        if row.get("range"):
            m[f"joint.{name}.range[0]"], m[f"joint.{name}.range[1]"] = row["range"]
    for name, s in (motion.get("sweeps") or {}).items():
        for k in ("stop_min", "stop_max", "clash_mm3"):
            if s.get(k) is not None:
                m[f"joint.{name}.{k}"] = s[k]
    return m


def _clean_name(s, what):
    s = str(s or "").strip()
    if not s or len(s) > 64:
        raise ValueError(f"{what} is a name")
    return s


def clean(spec: dict) -> dict:
    """One joint as the canvas sends it, checked and tidied for the Note. Raises ValueError."""
    if not isinstance(spec, dict):
        raise ValueError("a joint is {kind, moves, on, axis, range}")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    if kind == "rigid" and spec.get("parts") is not None:
        parts = [_clean_name(p, "a part") for p in spec["parts"]]
        if not parts:
            raise ValueError("a rigid group needs parts")
        return {"kind": "rigid", "parts": parts}
    out = {"kind": kind, "moves": _clean_name(spec.get("moves"), "moves"), "on": _clean_name(spec.get("on"), "on")}
    if kind == "rigid":
        return out
    axis = spec.get("axis")
    if isinstance(axis, str):
        out["axis"] = _clean_name(axis, "the axis")
    elif isinstance(axis, dict):
        origin = [round(float(x), 4) for x in axis.get("origin", [0, 0, 0])]
        if len(origin) != 3 or not all(math.isfinite(x) for x in origin):
            raise ValueError("an axis origin is [x, y, z]")
        d = axis.get("dir", "Z")
        out["axis"] = {"origin": origin, "dir": d.upper() if isinstance(d, str) else [round(float(x), 6) for x in _dir(d)]}
        _dir(out["axis"]["dir"])
    else:
        raise ValueError("a joint that moves needs an axis: a tag's name, or {origin, dir}")
    if spec.get("flip"):
        out["flip"] = True
    if spec.get("range") is not None:
        out["range"] = [round(x, 4) for x in _range(spec)]
    if spec.get("follows"):
        f = spec["follows"]
        if not isinstance(f, dict) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in f.values()):
            raise ValueError("follows is {joint: factor, ...}")
        out["follows"] = {_clean_name(k, "a joint"): float(v) for k, v in f.items()}
    if spec.get("locked"):
        out["locked"] = True
    return out
