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
- point: at [x, y, z] (a corner of the part)
- edge: a and b (the two ends of a line or curve), or center and radius (a circle or its arcs)
- object: name (a part of an assembly)
- group: of [selector, ...] (several features under one name: found when all of them are; with two
  points, two parallel flat faces or a point and a flat face it measures the distance between them)
- sketch: plane {origin, normal, x} and curves drawn on it by the user, optionally `on` a face selector
- plane: plane {origin, normal, x}: a plane the user made to draw on, `on` a face (and `offset` mm off it)
"""
import math
import re

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


def _near(p, q):
    return math.dist(p, q) <= TOL


def _point(tag, _faces, ctx):
    at = [float(x) for x in tag["at"]]
    points = ctx.get("points") or []
    if not points:
        return None
    v = min(points, key=lambda v: math.dist(v["at"], at))
    d = math.dist(v["at"], at)
    out = {"faces": [], "points": [v["i"]], "measure": {"at": v["at"]}}
    if d > TOL:
        out["measure"]["moved"] = round(d, 4)
        return {"resolved": False, "why": f"no corner at {at}; the nearest is {round(d, 3)} mm away, at {v['at']}", **out}
    return {"resolved": True, **out}


def _edge(tag, _faces, ctx):
    edges = ctx.get("edges") or []
    if "center" in tag:   # a circle, or the arcs that make one up
        c = [float(x) for x in tag["center"]]
        hit = [e for e in edges if e["type"] == "circle" and _near(e["c"], c)]
        if tag.get("radius") is not None and hit:
            same = [e for e in hit if abs(e["r"] - float(tag["radius"])) <= TOL]
            if not same:   # still there, with another radius: say which, so a check can fail on the number
                r = min((e["r"] for e in hit), key=lambda r: abs(r - float(tag["radius"])))
                hit = [e for e in hit if abs(e["r"] - r) <= 0.001]
            else:
                hit = same
        if not hit:
            return None
        return {"resolved": True, "faces": [], "edges": [e["i"] for e in hit],
                "measure": {"radius": hit[0]["r"], "diameter": round(2 * hit[0]["r"], 4), "length": round(sum(e["len"] for e in hit), 3),
                            "center": hit[0]["c"], "count": len(hit)}}
    a, b = [float(x) for x in tag["a"]], [float(x) for x in tag["b"]]
    hit = [e for e in edges if (_near(e["a"], a) and _near(e["b"], b)) or (_near(e["a"], b) and _near(e["b"], a))]
    if hit:
        return {"resolved": True, "faces": [], "edges": [e["i"] for e in hit],
                "measure": {"length": round(sum(e["len"] for e in hit), 3), "a": hit[0]["a"], "b": hit[0]["b"], "count": len(hit)}}
    if not edges:
        return None
    mid = [(x + y) / 2 for x, y in zip(a, b)]
    e = min(edges, key=lambda e: math.dist([(x + y) / 2 for x, y in zip(e["a"], e["b"])], mid))
    return {"resolved": False, "faces": [], "edges": [e["i"]], "why": f"no edge from {a} to {b}; the nearest runs from {e['a']} to {e['b']}",
            "measure": {"length": e["len"], "a": e["a"], "b": e["b"]}}


def _object(tag, _faces, ctx):
    part = next((q for q in ctx.get("parts") or [] if q["name"] == tag.get("name")), None)
    if part is None:
        return None
    b = part["bbox"]
    return {"resolved": True, "faces": [], "parts": [part["i"]],
            "measure": {"volume_cm3": round(part["volume"] / 1000, 3), "size": [round(b[k + 3] - b[k], 3) for k in range(3)],
                        "at": [round((b[k + 3] + b[k]) / 2, 3) for k in range(3)]}}


def _between(one, two, faces, ctx):
    """The distance between two found features, where it is one clear number: two points, two parallel flat faces,
    a point and a flat face."""
    points = {v["i"]: v for v in ctx.get("points") or []}

    def flat(r):
        fs = [faces[i] for i in r.get("faces", [])] if not r.get("points") and not r.get("edges") and not r.get("parts") else []
        return fs[0] if fs and all(f["type"] == "plane" and _dot(f["normal"], fs[0]["normal"]) > 0.9999 for f in fs) else None

    def corner(r):
        return points[r["points"][0]]["at"] if len(r.get("points", [])) == 1 and not r.get("faces") else None

    pa, pb, fa, fb = corner(one), corner(two), flat(one), flat(two)
    if pa and pb:
        return math.dist(pa, pb)
    if fa and fb and abs(abs(_dot(fa["normal"], fb["normal"])) - 1) < 1e-4:
        return abs(_dot([y - x for x, y in zip(fa["center"], fb["center"])], fa["normal"]))
    for p, f in ((pa, fb), (pb, fa)):
        if p and f:
            return abs(_dot([y - x for x, y in zip(f["center"], p)], f["normal"]))
    return None


def _group(tag, faces, ctx):
    members = []
    for sel in tag.get("of") or []:
        fn = KINDS.get(sel.get("kind"))
        if fn is None or fn in (_group, _sketch, _plane):
            raise ValueError(f"a group is made of plain selectors, not {sel.get('kind')!r}")
        members.append(fn(sel, faces, ctx) or {"resolved": False, "faces": []})
    if not members:
        raise ValueError("a group needs `of`: the selectors it is made of")
    out = {"resolved": all(m["resolved"] for m in members)}
    for key in ("faces", "edges", "points", "parts"):
        ids = sorted({i for m in members for i in m.get(key, [])})
        if ids or key == "faces":
            out[key] = ids
    measure = {"count": len(members)}
    area = sum(faces[i]["area"] for i in out["faces"])
    length = sum(e["len"] for e in ctx.get("edges") or [] if e["i"] in set(out.get("edges", [])))
    if area:
        measure["area"] = round(area, 3)
    if length:
        measure["length"] = round(length, 3)
    if len(members) == 2 and out["resolved"]:
        d = _between(members[0], members[1], faces, ctx)
        if d is not None:
            measure["distance"] = round(d, 4)
    out["measure"] = measure
    if not out["resolved"]:
        missing = [n + 1 for n, m in enumerate(members) if not m["resolved"]]
        out["why"] = f"member {', '.join(map(str, missing))} of {len(members)} is not found"
    return out


def _sketch(tag, faces, ctx):
    """A drawing the user made on a plane. It is found as long as the face it was drawn on is still there."""
    curves = tag.get("curves") or []
    plane = tag.get("plane") or {}
    if len(plane.get("origin", [])) != 3 or len(plane.get("normal", [])) != 3 or len(plane.get("x", [])) != 3:
        raise ValueError("a sketch needs a plane with origin, normal and x, each [x, y, z]")
    out = {"resolved": True, "faces": [], "measure": {"curves": len(curves), "closed": sum(1 for c in curves if c.get("closed") or c.get("type") in ("circle", "rect"))}}
    if tag.get("on"):
        fn = KINDS.get(tag["on"].get("kind"))
        on = fn(tag["on"], faces, ctx) if fn and fn not in (_group, _sketch, _plane) else None
        if not on or not on["resolved"]:
            return {**out, "resolved": False, "why": "the face this was drawn on is not found" + (f": {on['why']}" if on and on.get("why") else "")}
        out["faces"] = on["faces"]
    return out


def _plane(tag, faces, ctx):
    """A plane the user put on a face, to draw on. It is found as long as that face is still there."""
    plane = tag.get("plane") or {}
    if len(plane.get("origin", [])) != 3 or len(plane.get("normal", [])) != 3 or len(plane.get("x", [])) != 3:
        raise ValueError("a plane needs origin, normal and x, each [x, y, z]")
    out = {"resolved": True, "faces": [], "measure": {"offset": float(tag.get("offset") or 0)}}
    if tag.get("on"):
        fn = KINDS.get(tag["on"].get("kind"))
        on = fn(tag["on"], faces, ctx) if fn and fn not in (_group, _sketch, _plane) else None
        if not on or not on["resolved"]:
            return {**out, "resolved": False, "why": "the face this plane was put on is not found" + (f": {on['why']}" if on and on.get("why") else "")}
        out["faces"] = on["faces"]
    return out


KINDS = {"planar_face": _planar_face, "square_hole": _square_hole, "round_hole": _cylinder(True),
         "boss": _cylinder(False), "face_at": _face_at, "point": _point, "edge": _edge, "object": _object,
         "group": _group, "sketch": _sketch, "plane": _plane}


def resolve(tags: dict, faces: list, box: list, inside=None, edges=(), points=(), parts=()) -> dict:
    """Find every tag on this build. box = [minx, miny, minz, maxx, maxy, maxz] of the part; inside(point) says
    whether a point is in material (the runner passes the solid's own test); edges, points and parts are the
    other things a tag can name, as the runner describes them."""
    ctx = {"box": box, "inside": inside, "edges": list(edges), "points": list(points),
           "parts": [{**q, "i": n} for n, q in enumerate(parts)]}
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


def propose_item(item: dict) -> dict:
    """The selector for one selected thing, whatever it is: a face, a line, a point or an object."""
    kind = item.get("kind", "face")
    if kind == "vertex":
        return {"kind": "point", "at": [round(x, 3) for x in item["at"]]}
    if kind == "edge":
        if item.get("type") == "circle":
            return {"kind": "edge", "center": [round(x, 3) for x in item["c"]], "radius": round(item["r"], 3)}
        return {"kind": "edge", "a": [round(x, 3) for x in item["a"]], "b": [round(x, 3) for x in item["b"]]}
    if kind == "part":
        return {"kind": "object", "name": item["name"]}
    return propose(item)


def propose_many(items: list) -> dict:
    """One thing is its own selector; several become a group."""
    if not items:
        raise ValueError("nothing is selected")
    selectors = [propose_item(i) for i in items]
    return selectors[0] if len(selectors) == 1 else {"kind": "group", "of": selectors}


def _vec(v, n):
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
        raise ValueError(f"expected {n} numbers, got {v!r}")
    return [round(float(x), 3) for x in v]


def _clean_frame(plane) -> dict:
    plane = plane if isinstance(plane, dict) else {}
    out = {k: _vec(plane.get(k), 3) for k in ("origin", "normal", "x")}
    if abs(math.hypot(*out["normal"]) - 1) > 0.01 or abs(math.hypot(*out["x"]) - 1) > 0.01 or abs(_dot(out["normal"], out["x"])) > 0.01:
        raise ValueError("a plane's normal and x are unit vectors at right angles")
    return out


def clean_plane(spec: dict) -> dict:
    """A plane as it is kept in a tag. Raises ValueError on one that is not a plane."""
    offset = spec.get("offset") or 0
    if not isinstance(offset, (int, float)) or isinstance(offset, bool) or not math.isfinite(offset):
        raise ValueError("an offset is a number of millimetres")
    return {"plane": _clean_frame(spec.get("plane")), "offset": round(float(offset), 3)}


def clean_sketch(sketch: dict) -> dict:
    """A drawing as it is kept in a tag: checked, and rounded to a micron. Raises ValueError on one that is not."""
    vec = _vec
    out = {"plane": _clean_frame(sketch.get("plane")), "curves": []}
    if isinstance(sketch.get("plane_name"), str) and re.match(r"^[a-z][a-z0-9_]{0,39}$", sketch["plane_name"]):
        out["plane_name"] = sketch["plane_name"]       # which plane it was drawn on, for the reader
    curves = sketch.get("curves") or []
    if len(curves) > 200:
        raise ValueError("a sketch holds at most 200 curves")
    for c in curves:
        kind = c.get("type")
        if kind == "rect":
            size = vec(c.get("size"), 2)
            if min(size) <= 0:
                raise ValueError("a rectangle needs a width and a height")
            out["curves"].append({"type": "rect", "at": vec(c.get("at"), 2), "size": size})
        elif kind == "circle":
            r = c.get("r")
            if not isinstance(r, (int, float)) or r <= 0:
                raise ValueError("a circle needs a radius")
            out["curves"].append({"type": "circle", "center": vec(c.get("center"), 2), "r": round(float(r), 3)})
        elif kind == "polyline":
            points = [vec(q, 2) for q in c.get("points") or []]
            if not 2 <= len(points) <= 2000:
                raise ValueError("a line needs 2 to 2000 points")
            out["curves"].append({"type": "polyline", "points": points, "closed": bool(c.get("closed")) and len(points) > 2})
        else:
            raise ValueError(f"a curve is a polyline, a rect or a circle, not {kind!r}")
    if isinstance(sketch.get("on"), dict) and sketch["on"].get("kind") in KINDS and sketch["on"]["kind"] not in ("group", "sketch", "plane"):
        out["on"] = sketch["on"]
    return out
