"""Tags: features named by description, never by face number.

A tag is a selector ("the planar face with normal -Z at z = -16.72", "the square
tunnel along X centred at y, z"). Face numbers change on every rebuild; a description
either still finds its feature or it does not, and that is the point.

Everything here works on face descriptors (plain dicts made by the runner), so it runs
and is tested without a CAD kernel.

Kinds
- planar_face: normal ("+X".."-Z" or [x, y, z]), at (plane position along the normal;
  omitted = the outermost such face)
- square_hole: axis ("X"/"Y"/"Z"), at ([u, v]: the other two coordinates, in axis
  order), size
- round_hole / boss: axis, at, diameter (concave / convex cylinder)
- face_at: point [x, y, z] (fallback for any other surface)
"""
import math

TOL = 0.05          # mm: how far a feature may sit from where its tag says
PLANE_DEG = 1.0     # degrees between a face normal and the tag's normal
AXES = {"X": 0, "Y": 1, "Z": 2}
NORMALS = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)


def _normal(spec):
    if isinstance(spec, str):
        if spec.upper() not in NORMALS:
            raise ValueError(f"normal {spec!r}: use +X, -X, +Y, -Y, +Z, -Z or [x, y, z]")
        return NORMALS[spec.upper()]
    return _unit(tuple(float(x) for x in spec))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _axis(spec):
    a = AXES.get(str(spec).upper().lstrip("+-"))
    if a is None:
        raise ValueError(f"axis {spec!r}: use X, Y or Z")
    return a, [i for i in range(3) if i != a]


def _planes(faces, n):
    cos = math.cos(math.radians(PLANE_DEG))
    return [f for f in faces if f["type"] == "plane" and _dot(f["normal"], n) >= cos]


def _span(fs, i):
    return min(f["bbox"][i] for f in fs), max(f["bbox"][i + 3] for f in fs)


def _through(ctx, a, u, v, cu, cv, a0, a1):
    """Open from end to end: the centre line of the hole never passes through material. Asked of the solid itself
    when there is one (ctx["inside"]); from descriptors alone, a hole that spans the part is taken to be through."""
    box, inside = ctx["box"], ctx.get("inside")
    if inside is None:
        return bool(a0 <= box[a] + TOL and a1 >= box[a + 3] - TOL)
    n = max(2, min(400, int(box[a + 3] - box[a])))
    for k in range(n + 1):
        p = [0.0, 0.0, 0.0]
        p[a], p[u], p[v] = box[a] + 0.01 + (box[a + 3] - box[a] - 0.02) * k / n, cu, cv
        if inside(p):
            return False
    return True


def _planar_face(tag, faces, _ctx):
    spec = tag.get("normal", "+Z")
    n = _normal(spec)
    # where a face is: its coordinate along the axis ("-Z" at -16.72 is the face at z = -16.72);
    # for a slanted normal, its distance from the origin along that normal
    along = tuple(abs(x) for x in n) if isinstance(spec, str) else n
    cands = _planes(faces, n)
    if not cands:
        return None
    at = tag.get("at")
    if at is None:   # the outermost one, looking along the normal
        at = _dot(max(cands, key=lambda f: _dot(f["center"], n))["center"], along)
    hit = [f for f in cands if abs(_dot(f["center"], along) - float(at)) <= TOL]
    if not hit:
        # the nearest parallel face, so a moved face reads as "moved 2 mm", not as gone
        pos = _dot(min(cands, key=lambda f: abs(_dot(f["center"], along) - float(at)))["center"], along)
        hit = [f for f in cands if abs(_dot(f["center"], along) - pos) <= TOL]
        return {"resolved": False, "faces": [f["i"] for f in hit], "why": f"no face at {at}; the nearest parallel face is at {round(pos, 3)}",
                "measure": {"at": round(pos, 4), "moved": round(pos - float(at), 4)}}
    pos = sum(_dot(f["center"], along) for f in hit) / len(hit)
    return {"resolved": True, "faces": [f["i"] for f in hit],
            "measure": {"at": round(pos, 4), "area": round(sum(f["area"] for f in hit), 3), "count": len(hit)}}


def _first(faces, i, c, t, a):
    """Looking both ways along axis i from the centre line, at position t along the hole: the first flat face on
    each side, if it faces back at us (a wall of the void we stand in). Otherwise we stand in material, or outside."""
    live = [f for f in faces if f["bbox"][a] - 1e-6 <= t <= f["bbox"][a + 3] + 1e-6]
    below = max((f for f in live if f["center"][i] < c - 1e-6), key=lambda f: f["center"][i], default=None)
    above = min((f for f in live if f["center"][i] > c + 1e-6), key=lambda f: f["center"][i], default=None)
    if below is None or above is None or below["normal"][i] < 0 or above["normal"][i] > 0:
        return None
    return below, above


def _square_at(faces, ctx, a, u, v, cu, cv):
    """The square void around the line (cu, cv) running along axis a: its four walls, wherever along a it has all four."""
    cos = math.cos(math.radians(PLANE_DEG))
    across = {u: [f for f in faces if f["type"] == "plane" and abs(f["normal"][u]) >= cos and f["bbox"][v] - TOL <= cv <= f["bbox"][v + 3] + TOL],
              v: [f for f in faces if f["type"] == "plane" and abs(f["normal"][v]) >= cos and f["bbox"][u] - TOL <= cu <= f["bbox"][u + 3] + TOL]}
    cuts = sorted({round(f["bbox"][k], 4) for fs in across.values() for f in fs for k in (a, a + 3)})
    found = {}   # (lo_u, hi_u, lo_v, hi_v) -> [length, a0, a1, face ids]
    for t0, t1 in zip(cuts, cuts[1:]):
        t = (t0 + t1) / 2
        wu, wv = _first(across[u], u, cu, t, a), _first(across[v], v, cv, t, a)
        if not wu or not wv:
            continue
        key = tuple(round(f["center"][i], 3) for i, w in ((u, wu), (v, wv)) for f in w)
        row = found.setdefault(key, [0.0, t0, t1, set()])
        row[0] += t1 - t0
        row[1], row[2] = min(row[1], t0), max(row[2], t1)
        row[3].update(f["i"] for f in wu + wv)
    if not found:
        return None
    (lo_u, hi_u, lo_v, hi_v), (_, a0, a1, ids) = max(found.items(), key=lambda kv: kv[1][0])
    return {"faces": sorted(ids),
            "measure": {"width": round(hi_u - lo_u, 4), "height": round(hi_v - lo_v, 4),
                        "at": [round((lo_u + hi_u) / 2, 4), round((lo_v + hi_v) / 2, 4)],
                        "length": round(a1 - a0, 3),
                        "through": _through(ctx, a, u, v, (lo_u + hi_u) / 2, (lo_v + hi_v) / 2, a0, a1)}}


def _square_hole(tag, faces, ctx):
    a, (u, v) = _axis(tag.get("axis", "X"))
    size, at = tag.get("size"), tag.get("at")
    if at is not None:
        r = _square_at(faces, ctx, a, u, v, float(at[0]), float(at[1]))
        if r:
            return {"resolved": True, **r}
    if size is None:
        return None

    # not where the tag says (or no place given): look for a void of that size anywhere
    def floors(i):
        """Positions of planes facing +i that have a plane facing -i exactly `size` further on."""
        up = {round(f["center"][i], 2) for f in _planes(faces, tuple(1 if k == i else 0 for k in range(3)))}
        down = {round(f["center"][i], 2) for f in _planes(faces, tuple(-1 if k == i else 0 for k in range(3)))}
        return [p for p in up if any(abs(p + size - d) <= TOL for d in down)]

    best = None
    for pu in floors(u):
        for pv in floors(v):
            r = _square_at(faces, ctx, a, u, v, pu + size / 2, pv + size / 2)
            if not r or abs(r["measure"]["width"] - size) > TOL or abs(r["measure"]["height"] - size) > TOL:
                continue
            d = math.dist(r["measure"]["at"], at) if at is not None else 0.0
            if best is None or d < best[0]:
                best = (d, r)
    if best is None:
        return None
    d, r = best
    if at is None:
        return {"resolved": True, **r}
    r["measure"]["moved"] = [round(r["measure"]["at"][0] - at[0], 4), round(r["measure"]["at"][1] - at[1], 4)]
    return {"resolved": False, "why": f"no square hole at {list(at)}; one of size {size} is at {r['measure']['at']}", **r}


def _cylinder(concave):
    def resolve(tag, faces, ctx):
        a, (u, v) = _axis(tag.get("axis", "Z"))
        at, dia = tag.get("at"), tag.get("diameter")
        cands = [f for f in faces if f["type"] == "cylinder" and f["concave"] == concave and abs(abs(f["axis"][a]) - 1) < 1e-4]
        if dia is not None and at is None:
            cands = [f for f in cands if abs(2 * f["radius"] - dia) <= TOL]
        if not cands:
            return None
        if at is not None:
            near = min(cands, key=lambda f: math.dist((f["origin"][u], f["origin"][v]), at))
        else:
            near = cands[0]
        centre = (near["origin"][u], near["origin"][v])
        hit = [f for f in cands if math.dist((f["origin"][u], f["origin"][v]), centre) <= 0.01 and abs(f["radius"] - near["radius"]) <= 0.01]
        a0, a1 = _span(hit, a)
        measure = {"diameter": round(2 * near["radius"], 4), "at": [round(centre[0], 4), round(centre[1], 4)],
                   "length": round(a1 - a0, 3), "through": _through(ctx, a, u, v, *centre, a0, a1)}
        out = {"faces": [f["i"] for f in hit], "measure": measure}
        if at is not None and math.dist(centre, at) > TOL:
            measure["moved"] = [round(centre[0] - at[0], 4), round(centre[1] - at[1], 4)]
            return {"resolved": False, "why": f"nothing at {list(at)}; the nearest is at {measure['at']}", **out}
        return {"resolved": True, **out}
    return resolve


def _face_at(tag, faces, _ctx):
    p = [float(x) for x in tag.get("point", (0, 0, 0))]
    inside = [f for f in faces if all(f["bbox"][i] - TOL <= p[i] <= f["bbox"][i + 3] + TOL for i in range(3))]
    if not inside:
        return None
    f = min(inside, key=lambda f: math.dist(f["center"], p))
    return {"resolved": True, "faces": [f["i"]], "measure": {"area": round(f["area"], 3), "type": f["type"]}}


KINDS = {"planar_face": _planar_face, "square_hole": _square_hole, "round_hole": _cylinder(True),
         "boss": _cylinder(False), "face_at": _face_at}


def resolve(tags: dict, faces: list, box: list, inside=None) -> dict:
    """Find every tag on this build. box = [minx, miny, minz, maxx, maxy, maxz] of the part; inside(point) says
    whether a point is in material (the runner passes the solid's own test)."""
    ctx = {"box": box, "inside": inside}
    out = {}
    for name, tag in (tags or {}).items():
        try:
            fn = KINDS.get(tag.get("kind"))
            if fn is None:
                out[name] = {"resolved": False, "faces": [], "measure": {}, "why": f"unknown kind {tag.get('kind')!r}: use one of {', '.join(KINDS)}"}
                continue
            r = fn(tag, faces, ctx)
            out[name] = r or {"resolved": False, "faces": [], "measure": {}, "why": "nothing on the part matches this description"}
        except (ValueError, TypeError, KeyError, IndexError) as e:
            out[name] = {"resolved": False, "faces": [], "measure": {}, "why": f"bad tag: {e}"}
    return out


def _axis_name(v):
    for name, n in NORMALS.items():
        if _dot(v, n) > 0.9999:
            return name
    return None


def propose(face: dict) -> dict:
    """The selector for a face someone clicked: how to find it again after a rebuild."""
    if face["type"] == "plane":
        name = _axis_name(face["normal"])
        along = tuple(abs(x) for x in face["normal"]) if name else face["normal"]
        return {"kind": "planar_face", "normal": name or [round(x, 4) for x in face["normal"]],
                "at": round(_dot(face["center"], along), 2)}
    if face["type"] == "cylinder":
        name = _axis_name(face["axis"]) or _axis_name(tuple(-x for x in face["axis"]))
        if name:
            a, (u, v) = _axis(name)
            return {"kind": "round_hole" if face["concave"] else "boss", "axis": "XYZ"[a],
                    "at": [round(face["origin"][u], 2), round(face["origin"][v], 2)], "diameter": round(2 * face["radius"], 2)}
    return {"kind": "face_at", "point": [round(x, 2) for x in face["center"]]}
