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
    """Faces as plain data, and one mesh whose triangles are grouped face by face, the faces part by part.

    Straight from the kernel's own mesh (one meshing of the whole shape, then each face's triangles read out):
    asking build123d face by face is several times slower, and this is most of what a build spends its time on."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    faces, verts, tris, parts = [], [], [], []
    r4, r6 = (lambda v: round(v, 4)), (lambda v: round(v, 6))
    # the size of each part first: asking for a bounding box throws the mesh away
    sized = []
    for name, sub in groups:
        bb = sub.bounding_box()
        sized.append((round(sub.volume, 3), [round(x, 4) for x in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)]))
    BRepMesh_IncrementalMesh(shape.wrapped, LINEAR, False, ANGULAR, True)
    for (name, sub), (volume, bbox) in zip(groups, sized):
        part = {"name": name, "faces": [len(faces), 0], "tris": [len(tris), 0], "volume": volume, "bbox": bbox}
        for f in sub.faces():
            w = f.wrapped
            loc = TopLoc_Location()
            mesh = BRep_Tool.Triangulation_s(w, loc)
            if mesh is None:      # a face the kernel could not mesh: nothing to show of it
                continue
            move, flipped = loc.Transformation(), w.Orientation() == TopAbs_REVERSED
            pts = []
            for k in range(1, mesh.NbNodes() + 1):
                q = mesh.Node(k).Transformed(move)
                pts.append((q.X(), q.Y(), q.Z()))
            local = []
            for k in range(1, mesh.NbTriangles() + 1):
                i, j, l = mesh.Triangle(k).Get()
                local.append((i - 1, l - 1, j - 1) if flipped else (i - 1, j - 1, l - 1))
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(w, props)
            c = props.CentreOfMass()
            xs, ys, zs = zip(*pts)
            d = {"i": len(faces), "type": "other", "area": r4(props.Mass()), "center": [r6(c.X()), r6(c.Y()), r6(c.Z())],
                 "bbox": [r4(min(xs)), r4(min(ys)), r4(min(zs)), r4(max(xs)), r4(max(ys)), r4(max(zs))],
                 "tris": [len(tris), len(local)]}
            surface = BRepAdaptor_Surface(w)
            kind = surface.GetType()
            if kind in (GeomAbs_Plane, GeomAbs_Cylinder) and local:
                # which way the face looks: from its largest triangle, wound as the face is turned
                def normal_of(t):
                    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = pts[t[0]], pts[t[1]], pts[t[2]]
                    ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
                    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
                t = max(local, key=lambda t: sum(x * x for x in normal_of(t)))
                nx, ny, nz = normal_of(t)
                size = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
                nx, ny, nz = nx / size, ny / size, nz / size
                if kind == GeomAbs_Plane:
                    d.update(type="plane", normal=[r6(nx), r6(ny), r6(nz)])
                else:
                    cyl = surface.Cylinder()
                    o, way = cyl.Axis().Location(), cyl.Axis().Direction()
                    mid = [sum(pts[i][k] for i in t) / 3 for k in range(3)]
                    along = (mid[0] - o.X()) * way.X() + (mid[1] - o.Y()) * way.Y() + (mid[2] - o.Z()) * way.Z()
                    to_axis = (o.X() + way.X() * along - mid[0], o.Y() + way.Y() * along - mid[1], o.Z() + way.Z() * along - mid[2])
                    d.update(type="cylinder", axis=[r6(way.X()), r6(way.Y()), r6(way.Z())], origin=[r6(o.X()), r6(o.Y()), r6(o.Z())],
                             radius=round(cyl.Radius(), 5), concave=bool(nx * to_axis[0] + ny * to_axis[1] + nz * to_axis[2] > 0))
            faces.append(d)
            base = len(verts)
            verts.extend(pts)
            tris.extend((i + base, j + base, l + base) for i, j, l in local)
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


def crossing(shape):
    """blocked(p, q): does the straight way from p to q meet the part anywhere? One question to the kernel, where
    asking point by point whether each is inside took a second and more on a part with many faces."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    probe = IntCurvesFace_ShapeIntersector()
    probe.Load(shape.wrapped, 1e-7)

    def blocked(p, q):
        d = [b - a for a, b in zip(p, q)]
        length = sum(x * x for x in d) ** 0.5
        if length < 1e-9:
            return False
        probe.Perform(gp_Lin(gp_Pnt(*p), gp_Dir(*d)), 0.0, length)
        return probe.NbPnt() > 0
    return blocked


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
        result["params"] = getattr(mod, "PARAMS", {})
        result["doc"] = (mod.__doc__ or "").strip()
        result["triangles"] = len(tris)
        segs, edges, points = edges_and_points(groups, parts)
        result["tags"] = tags.resolve(getattr(mod, "TAGS", {}) or {}, faces, result["fingerprint"]["bbox"],
                                      blocked=crossing(shape), edges=edges, points=points, parts=parts)
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


def limits(seconds: int, memory_mb: int = 0) -> None:
    """In the build process: a Note may not run for ever or take the server down with it.

    Memory is capped where it can be done honestly: by the container (deploy/compose.yml). Here the build is only
    marked as the first to go when that ceiling is hit, so the kernel kills the hungry Note and not the server.
    (An address-space limit, RLIMIT_AS, is not used unless asked for: the CAD kernel and numpy reserve far more
    address space than they use, and die under a limit that their real memory would fit in many times.)"""
    import os
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 5))
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/oom_score_adj", "w") as fh:
                fh.write("1000")
        except OSError:
            pass
        if memory_mb > 0:
            cap = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    os.setsid()


KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


def child(project_dir: str, note: str, out_dir: str, exports, seconds: int, memory_mb: int) -> None:
    """A build, in a process forked for it from one that has the kernel loaded already (monet/warm.py). It is held
    in like any other build, and sees none of the server's surroundings."""
    import os
    limits(seconds, memory_mb)
    # no bytecode kept: a Note written twice within a second, at the same length, would be run from the first one's
    sys.dont_write_bytecode = True
    for key in list(os.environ):
        if key not in KEPT:
            del os.environ[key]
    os.chdir(project_dir)
    run(Path(project_dir), note, Path(out_dir), tuple(exports))


def main(argv=None):
    argv = argv or sys.argv[1:]
    exports = tuple(argv[3].split(",")) if len(argv) > 3 and argv[3] else ()
    result = run(Path(argv[0]), argv[1], Path(argv[2]), exports)
    print(json.dumps({"ok": result["ok"], "error": result.get("error")}))


if __name__ == "__main__":
    main()
