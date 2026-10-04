"""The diff: every change visible.

Model A coloured by its distance to B (what was removed), B by its distance to A (what
was added). The colour scale starts at the printer's tolerance, so only changes that
matter for printing show up. Borrowed from metrology (CloudCompare, GOM Inspect).
Tagged features are compared by their measurements, so a moved hole reads "moved 2 mm",
not as damage.
"""
from pathlib import Path

import numpy as np
import trimesh

GREY = np.array([196, 198, 204, 255], dtype=np.float64)
REMOVED = np.array([226, 61, 45, 255], dtype=np.float64)    # on A: material that is gone
ADDED = np.array([40, 168, 92, 255], dtype=np.float64)      # on B: material that is new
MAX_POINTS = 120_000


def load_mesh(path: Path) -> trimesh.Trimesh:
    scene = trimesh.load(path, force="scene", process=False)
    meshes = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
    return meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)


def _dense(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """A flat face is two triangles; a hole cut in its middle would not show on its four corners. Split until the
    points are close enough together to carry a colour map."""
    edge = max(1.0, float(np.sqrt(mesh.area / MAX_POINTS) * 1.6))
    v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge=edge, max_iter=12)
    return trimesh.Trimesh(v, f, process=False)


def _distances(points: np.ndarray, other: trimesh.Trimesh, other_dense: trimesh.Trimesh) -> np.ndarray:
    """Distance from each point to the surface of `other`. Where nothing changed the two tessellations share their
    points exactly, so only the points without a twin need the exact (slow) search."""
    from scipy.spatial import cKDTree
    near, _ = cKDTree(other_dense.vertices).query(points)
    d = np.zeros(len(points))
    todo = near > 1e-6
    if todo.any():
        _, exact, _ = trimesh.proximity.closest_point(other, points[todo])
        d[todo] = exact
    return d


def _paint(mesh: trimesh.Trimesh, d: np.ndarray, tol: float, colour: np.ndarray, path: Path) -> None:
    t = np.clip((d - tol) / (19.0 * tol), 0.0, 1.0)[:, None]      # full colour at 20 x tolerance
    rgba = np.where(d[:, None] > tol, GREY + (colour - GREY) * (0.35 + 0.65 * t), GREY)
    mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=rgba.astype(np.uint8))
    scene = trimesh.Scene()
    scene.add_geometry(mesh, geom_name="part", node_name="part")
    path.write_bytes(scene.export(file_type="glb"))


def _side(d: np.ndarray, points: np.ndarray, tol: float) -> dict:
    i = int(np.argmax(d)) if len(d) else 0
    return {"max_mm": round(float(d[i]), 3) if len(d) else 0.0,
            "at": [round(float(x), 2) for x in points[i]] if len(d) else None,
            "share_changed": round(float((d > tol).mean()), 4) if len(d) else 0.0}


def colour_maps(glb_a: Path, glb_b: Path, tol: float, out_a: Path, out_b: Path) -> dict:
    a, b = load_mesh(glb_a), load_mesh(glb_b)
    da_mesh, db_mesh = _dense(a), _dense(b)
    da = _distances(da_mesh.vertices, b, db_mesh)
    db = _distances(db_mesh.vertices, a, da_mesh)
    _paint(da_mesh, da, tol, REMOVED, out_a)
    _paint(db_mesh, db, tol, ADDED, out_b)
    removed, added = _side(da, da_mesh.vertices, tol), _side(db, db_mesh.vertices, tol)
    return {"tolerance": tol, "removed": removed, "added": added,
            "same": bool(removed["max_mm"] <= tol and added["max_mm"] <= tol)}


def numbers(sa: dict, sb: dict) -> dict:
    """The fingerprints side by side."""
    a, b = sa["fingerprint"], sb["fingerprint"]
    size = lambda f: [round(f["bbox"][i + 3] - f["bbox"][i], 3) for i in range(3)]
    return {"volume_cm3": [round(a["volume"] / 1000, 3), round(b["volume"] / 1000, 3)],
            "area_cm2": [round(a["area"] / 100, 3), round(b["area"] / 100, 3)],
            "size": [size(a), size(b)], "solids": [a["solids"], b["solids"]]}


def tag_changes(sa: dict, sb: dict, tol: float) -> list:
    """What happened to each tagged feature between A and B, in words a person would use."""
    out = []
    ta, tb = sa.get("tags") or {}, sb.get("tags") or {}
    for name in sorted(set(ta) | set(tb)):
        if name not in tb:
            out.append({"tag": name, "change": "tag removed"})
        elif name not in ta:
            out.append({"tag": name, "change": "new tag"})
        elif ta[name].get("resolved") and not tb[name].get("resolved"):
            out.append({"tag": name, "change": "no longer found" + (f": {tb[name]['why']}" if tb[name].get("why") else "")})
        else:
            ma, mb = ta[name].get("measure", {}), tb[name].get("measure", {})
            words = []
            for k in sorted(set(ma) & set(mb)):
                x, y = ma[k], mb[k]
                if isinstance(x, list) and isinstance(y, list):
                    d = [round(q - p, 3) for p, q in zip(x, y)]
                    if any(abs(v) > 1e-6 for v in d):
                        words.append(f"{k} moved by {d} mm")
                elif isinstance(x, bool) or isinstance(y, bool):
                    if x != y:
                        words.append(f"{k}: {x} -> {y}")
                elif isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(y - x) > 1e-6:
                    words.append(f"{k}: {x} -> {y} ({y - x:+.3f})")
            if words:
                out.append({"tag": name, "change": "; ".join(words)})
    return out
