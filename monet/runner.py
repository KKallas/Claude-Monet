"""The runner: the one place a Note is executed.

    python -m monet.runner <project_dir> <note> <out_dir> [stl,3mf,step]

Runs in its own process (a Note is code: it can loop forever, eat memory or crash the
CAD kernel) and leaves in out_dir:

    result.json   fingerprint, faces, tags found, parameters, what was imported, or the error
    model.glb     preview: one mesh, triangles grouped by face, plus the edges as lines
    model.stl / model.3mf / model.step   on request
"""
import hashlib
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

LINEAR = 0.05     # mm, preview mesh
ANGULAR = 0.3     # rad
EXPORT_LINEAR, EXPORT_ANGULAR = 0.01, 0.2


def versions() -> dict:
    from importlib.metadata import version, PackageNotFoundError
    from . import __version__
    out = {"monet": __version__}      # what a build leaves behind changes with Monet too
    for name in ("build123d", "cadquery-ocp", "cadquery-ocp-novtk"):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            pass
    return out


def _vec(v):
    return [round(float(x), 6) for x in (v.X, v.Y, v.Z)]


def leaves(shape, prefix="", unnamed="part"):
    """The parts of what build() returned: the labelled children of a compound, down to those without children of
    their own. A plain part is its own single leaf."""
    kids = list(getattr(shape, "children", ()) or ())
    if not kids:
        return [(prefix or getattr(shape, "label", "") or unnamed, shape)]
    out = []
    for i, kid in enumerate(kids):
        name = getattr(kid, "label", "") or f"part_{i + 1}"
        out += leaves(kid, f"{prefix}/{name}" if prefix else name)
    return out


def parts_of(shape, note="part"):
    """[(name, shape)] with unique names. Several loose solids without names are parts too; a plain part goes by
    the name of its Note."""
    found = leaves(shape, unnamed=note)
    if len(found) == 1 and len(found[0][1].solids()) > 1:
        found = [(f"solid_{i + 1}", s) for i, s in enumerate(found[0][1].solids())]
    seen, out = {}, []
    for name, sub in found:
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else f"{name}_{seen[name]}", sub))
    return out


def describe(shape, groups):
    """Faces as plain data, and one mesh whose triangles are grouped face by face, the faces part by part."""
    from build123d import GeomType, Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    shape.mesh(LINEAR, ANGULAR)
    faces, verts, tris, parts = [], [], [], []
    for name, sub in groups:
        bb = sub.bounding_box()
        part = {"name": name, "faces": [len(faces), 0], "tris": [len(tris), 0], "volume": round(sub.volume, 3),
                "bbox": [round(x, 4) for x in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)]}
        for f in sub.faces():
            v, t = f.tessellate(LINEAR, ANGULAR)
            fb = f.bounding_box()
            d = {"i": len(faces), "type": "other", "area": round(f.area, 4), "center": _vec(f.center()),
                 "bbox": [round(x, 4) for x in (fb.min.X, fb.min.Y, fb.min.Z, fb.max.X, fb.max.Y, fb.max.Z)],
                 "tris": [len(tris), len(t)]}
            if f.geom_type == GeomType.PLANE:
                d.update(type="plane", normal=_vec(f.normal_at()))
            elif f.geom_type == GeomType.CYLINDER:
                cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
                loc, way = cyl.Axis().Location(), cyl.Axis().Direction()
                origin, axis = Vector(loc.X(), loc.Y(), loc.Z()), Vector(way.X(), way.Y(), way.Z())
                mid = f.position_at(0.5, 0.5)
                to_axis = (origin + axis * ((mid - origin).dot(axis))) - mid
                d.update(type="cylinder", axis=_vec(axis), origin=_vec(origin), radius=round(cyl.Radius(), 5),
                         concave=bool(f.normal_at(mid).dot(to_axis) > 0))
            faces.append(d)
            base = len(verts)
            verts.extend((p.X, p.Y, p.Z) for p in v)
            tris.extend((a + base, b + base, c + base) for a, b, c in t)
        part["faces"][1] = len(faces) - part["faces"][0]
        part["tris"][1] = len(tris) - part["tris"][0]
        parts.append(part)
    return faces, verts, tris, parts


def edges_and_points(groups, parts):
    """The real edges of the part as line segments, so the preview is drawn like a drawing, not like a mesh; and
    each edge and each corner point as plain data, so they can be pointed at. Part by part, like the triangles,
    so a part can be moved or hidden with its edges."""
    from build123d import GeomType
    at = lambda v: [round(v.X, 4), round(v.Y, 4), round(v.Z, 4)]
    segs, edges, points = [], [], []
    for index, ((_, sub), part) in enumerate(zip(groups, parts)):
        start = len(segs)
        for e in sub.edges():
            first, a, b = len(segs), e.position_at(0), e.position_at(1)
            d = {"i": len(edges), "p": index, "type": "other", "len": round(e.length, 3), "a": at(a), "b": at(b)}
            if e.geom_type == GeomType.LINE:
                d["type"] = "line"
                pts = [a, b]
            else:
                n = max(6, min(48, int(e.length / 1.5)))
                pts = [e.position_at(k / n) for k in range(n + 1)]
                if e.geom_type == GeomType.CIRCLE:
                    try:
                        d.update(type="circle", r=round(e.radius, 4), c=at(e.arc_center))
                    except Exception:   # an arc the kernel will not describe: it stays "other"
                        pass
            segs.extend(((p.X, p.Y, p.Z), (q.X, q.Y, q.Z)) for p, q in zip(pts, pts[1:]))
            d["segs"] = [first, len(segs) - first]
            edges.append(d)
        part["edges"] = [start, len(segs) - start]
        base = len(points)
        points.extend({"i": base + k, "p": index, "at": at(v)} for k, v in enumerate(sub.vertices()))
    return segs, edges, points


def write_glb(path: Path, verts, tris, segs):
    """The preview, written out by hand: one triangle mesh, and the edges as separate line segments, both in exactly
    the order they were made in (the parts of an assembly are ranges of them)."""
    import struct

    import numpy as np
    blobs, views, accessors = [], [], []

    def add(array, target, component, kind):
        data = array.tobytes()
        views.append({"buffer": 0, "byteOffset": sum(len(x) for x in blobs), "byteLength": len(data), "target": target})
        blobs.append(data + b"\x00" * (-len(data) % 4))
        acc = {"bufferView": len(views) - 1, "componentType": component, "count": len(array), "type": kind}
        if kind == "VEC3":
            acc.update(min=array.min(0).tolist(), max=array.max(0).tolist())
        accessors.append(acc)
        return len(accessors) - 1

    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    doc = {"asset": {"version": "2.0", "generator": "monet"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"name": "part", "mesh": 0}],
           "meshes": [{"name": "part", "primitives": [{"attributes": {"POSITION": add(v, 34962, 5126, "VEC3")},
                                                       "indices": add(np.asarray(tris, dtype=np.uint32).reshape(-1), 34963, 5125, "SCALAR"),
                                                       "mode": 4}]}]}
    if len(segs):
        e = np.asarray(segs, dtype=np.float32).reshape(-1, 3)
        doc["scenes"][0]["nodes"].append(1)
        doc["nodes"].append({"name": "edges", "mesh": 1})
        doc["meshes"].append({"name": "edges", "primitives": [{"attributes": {"POSITION": add(e, 34962, 5126, "VEC3")}, "mode": 1}]})
    binary = b"".join(blobs)
    doc.update(buffers=[{"byteLength": len(binary)}], bufferViews=views, accessors=accessors)
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(text) + 8 + len(binary))
                     + struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


def load_note(project_dir: Path, note: str):
    sys.path.insert(0, str(project_dir))
    spec = importlib.util.spec_from_file_location(note, project_dir / f"{note}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[note] = mod
    spec.loader.exec_module(mod)
    return mod


def as_shape(obj):
    from build123d import Compound, Shape
    if hasattr(obj, "part") and not isinstance(obj, Shape):   # a BuildPart handed back as it is
        obj = obj.part
    if isinstance(obj, (list, tuple)):
        obj = Compound(children=list(obj))
    if not isinstance(obj, Shape):
        raise TypeError(f"build() returned {type(obj).__name__}: it must return a build123d shape")
    return obj


def imported(project_dir: Path) -> dict:
    """The project files this build read, with their hashes: what the result depends on."""
    root = str(project_dir.resolve())
    out = {}
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and str(Path(f).resolve()).startswith(root + "/") and f.endswith(".py"):
            p = Path(f).resolve()
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run(project_dir: Path, note: str, out_dir: Path, exports=()) -> dict:
    from . import semmelweis, tags
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"note": note, "ok": False, "libs": versions()}
    try:
        mod = load_note(project_dir, note)
        if not callable(getattr(mod, "build", None)):
            raise TypeError("a Note needs a build() function that returns the solid")
        shape = as_shape(mod.build())
        result["build_seconds"] = round(time.time() - t0, 2)
        result["fingerprint"] = semmelweis.fingerprint(shape)
        result["valid"] = bool(shape.is_valid)
        groups = parts_of(shape, note)
        faces, verts, tris, parts = describe(shape, groups)
        from build123d import Vector
        solids = shape.solids()
        result["tags"] = tags.resolve(getattr(mod, "TAGS", {}) or {}, faces, result["fingerprint"]["bbox"],
                                      inside=lambda p: any(s.is_inside(Vector(*p)) for s in solids))
        result["params"] = getattr(mod, "PARAMS", {})
        result["doc"] = (mod.__doc__ or "").strip()
        result["triangles"] = len(tris)
        segs, edges, points = edges_and_points(groups, parts)
        write_glb(out_dir / "model.glb", verts, tris, segs)
        (out_dir / "faces.json").write_text(json.dumps({"faces": faces, "parts": parts, "edges": edges, "points": points}, separators=(",", ":")))
        result["parts"] = [{k: part[k] for k in ("name", "volume", "bbox", "faces")} for part in parts]
        if "stl" in exports:
            from build123d import export_stl
            export_stl(shape, str(out_dir / "model.stl"), tolerance=EXPORT_LINEAR, angular_tolerance=EXPORT_ANGULAR)
        if "step" in exports:
            from build123d import export_step
            export_step(shape, str(out_dir / "model.step"))
        if "3mf" in exports:
            from build123d import Mesher
            mesher = Mesher()
            mesher.add_shape(shape.solids() or shape, linear_deflection=EXPORT_LINEAR, angular_deflection=EXPORT_ANGULAR)
            mesher.write(str(out_dir / "model.3mf"))
        result["ok"] = True
    except BaseException as e:   # also SystemExit and the like: a Note may do anything
        tb = traceback.extract_tb(e.__traceback__)
        mine = [f for f in tb if str(project_dir) in f.filename]
        where = f" ({Path(mine[-1].filename).name}, line {mine[-1].lineno})" if mine else ""
        result["error"] = f"{type(e).__name__}: {e}{where}"
        result["traceback"] = "".join(traceback.format_exception(e))[-4000:]
    result["deps"] = imported(project_dir)
    result["seconds"] = round(time.time() - t0, 2)
    (out_dir / "result.json").write_text(json.dumps(result, default=str))
    return result


def main(argv=None):
    argv = argv or sys.argv[1:]
    exports = tuple(argv[3].split(",")) if len(argv) > 3 and argv[3] else ()
    result = run(Path(argv[0]), argv[1], Path(argv[2]), exports)
    print(json.dumps({"ok": result["ok"], "error": result.get("error")}))


if __name__ == "__main__":
    main()
