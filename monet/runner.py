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
    out = {}
    for name in ("build123d", "cadquery-ocp", "cadquery-ocp-novtk"):
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            pass
    return out


def _vec(v):
    return [round(float(x), 6) for x in (v.X, v.Y, v.Z)]


def describe(shape):
    """Faces as plain data, and one mesh whose triangles are grouped face by face."""
    from build123d import GeomType, Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    shape.mesh(LINEAR, ANGULAR)
    faces, verts, tris = [], [], []
    for i, f in enumerate(shape.faces()):
        v, t = f.tessellate(LINEAR, ANGULAR)
        bb = f.bounding_box()
        d = {"i": i, "type": "other", "area": round(f.area, 4), "center": _vec(f.center()),
             "bbox": [round(x, 4) for x in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)],
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
    return faces, verts, tris


def edge_segments(shape):
    """The real edges of the part as line segments, so the preview is drawn like a drawing, not like a mesh."""
    from build123d import GeomType
    segs = []
    for e in shape.edges():
        if e.geom_type == GeomType.LINE:
            pts = [e.position_at(0), e.position_at(1)]
        else:
            n = max(6, min(48, int(e.length / 1.5)))
            pts = [e.position_at(k / n) for k in range(n + 1)]
        segs.extend(((a.X, a.Y, a.Z), (b.X, b.Y, b.Z)) for a, b in zip(pts, pts[1:]))
    return segs


def write_glb(path: Path, verts, tris, segs):
    import numpy as np
    import trimesh
    scene = trimesh.Scene()
    mesh = trimesh.Trimesh(np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int64), process=False)
    mesh.visual = trimesh.visual.ColorVisuals(mesh)
    scene.add_geometry(mesh, geom_name="part", node_name="part")
    if segs:
        scene.add_geometry(trimesh.load_path(np.array(segs, dtype=np.float64)), geom_name="edges", node_name="edges")
    path.write_bytes(scene.export(file_type="glb"))


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
        faces, verts, tris = describe(shape)
        from build123d import Vector
        solids = shape.solids()
        result["tags"] = tags.resolve(getattr(mod, "TAGS", {}) or {}, faces, result["fingerprint"]["bbox"],
                                      inside=lambda p: any(s.is_inside(Vector(*p)) for s in solids))
        result["params"] = getattr(mod, "PARAMS", {})
        result["doc"] = (mod.__doc__ or "").strip()
        result["triangles"] = len(tris)
        write_glb(out_dir / "model.glb", verts, tris, edge_segments(shape))
        (out_dir / "faces.json").write_text(json.dumps({"faces": faces}))
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
