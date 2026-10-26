"""Does a straight line meet the part? Asked of a build's preview mesh, not of the solid: so the runner (where the
Note is built) and the server (which never runs a Note, and works tags out again from what a build left) answer it
the same way. The mesh is taken at the precision the preview keeps (float32), whoever asks.

A hole's centre line keeps well away from its walls, so the mesh, within 0.05 mm of the surface, answers as the
solid would."""
import numpy as np


def crossing(verts, tris):
    """blocked(p, q): does the segment from p to q meet any triangle of the mesh?"""
    v = np.asarray(verts, dtype=np.float32).astype(np.float64).reshape(-1, 3)
    t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    a = v[t[:, 0]]
    e1, e2 = v[t[:, 1]] - a, v[t[:, 2]] - a

    def blocked(p, q):
        p, q = np.asarray(p, dtype=np.float64), np.asarray(q, dtype=np.float64)
        d = q - p
        if not len(t) or float(d @ d) < 1e-18:
            return False
        # Möller–Trumbore against every triangle at once; s along the segment, 0 at p and 1 at q
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        w = p - a
        u = np.einsum("ij,ij->i", w, h) * inv
        qv = np.cross(w, e1)
        v_ = (qv @ d) * inv
        s = np.einsum("ij,ij->i", e2, qv) * inv
        hit = ok & (u >= 0) & (v_ >= 0) & (u + v_ <= 1) & (s >= 0) & (s <= 1)
        return bool(hit.any())
    return blocked
