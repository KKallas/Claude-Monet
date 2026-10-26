"""A build's tags and joints, found from what the build left: its faces, edges, points and parts (faces.json), its
bounding box and its preview mesh. No CAD kernel and no Note: the runner asks this right after a build, and the
server asks it again when the person tags a face or makes a joint in the canvas, which changes no geometry."""
import time

from . import joints, rays, tags


def found(literals: dict, bbox, geo: dict, verts, tris) -> tuple:
    """(tags found, motion or None). literals: the Note's {"tags", "joints", "ground", "tips"}; geo: faces.json."""
    parts = geo["parts"]
    got = tags.resolve(literals.get("tags") or {}, geo["faces"], bbox, blocked=rays.crossing(verts, tris),
                       edges=geo.get("edges"), points=geo.get("points"), parts=parts)
    spec = literals.get("joints") or {}
    if len(parts) < 2 and not spec:
        return got, None
    t0 = time.time()
    model = joints.resolve(spec, literals.get("ground"), [p["name"] for p in parts], literals.get("tags") or {}, got,
                           geo["faces"], literals.get("tips") or {})
    model.update(joints.analyse(model, joints.solids(verts, tris, parts)))
    model["seconds"] = round(time.time() - t0, 2)
    return got, model
