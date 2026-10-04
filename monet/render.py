"""Render: the agent's eyes. A PNG of the part from the usual sides, with no GPU and no browser.

Orthographic views from the preview GLB: the triangles are sampled into a depth buffer
(numpy), the real edges of the part are drawn over them where they are not hidden, and
tagged faces can be painted so the agent sees what a tag points at.
"""
import io
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

VIEWS = {   # name: (where the camera stands, what is up on the page)
    "iso": ((1.0, -1.0, 0.8), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "front": ((0, -1, 0), (0, 0, 1)),
    "right": ((1, 0, 0), (0, 0, 1)),
    "back": ((0, 1, 0), (0, 0, 1)),
    "left": ((-1, 0, 0), (0, 0, 1)),
    "bottom": ((0, 0, -1), (0, 1, 0)),
    "iso_back": ((-1.0, 1.0, 0.8), (0, 0, 1)),
    "iso_under": ((1.0, -1.0, -0.8), (0, 0, 1)),
}
BG = np.array([247, 247, 250], dtype=np.uint8)
BODY = np.array([188, 196, 212], dtype=np.float64)
EDGE = np.array([40, 44, 56], dtype=np.uint8)
PALETTE = [(226, 111, 40), (40, 150, 200), (60, 170, 90), (190, 70, 170), (210, 170, 30), (90, 100, 220), (220, 70, 80), (20, 160, 150)]
LEVELS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536)
CHUNK = 1_500_000    # samples in memory at once


def load(path: Path):
    """(vertices, triangles, edge segments) of a preview GLB."""
    scene = trimesh.load(path, force="scene", process=False)
    mesh = next(g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh))
    segs = np.zeros((0, 2, 3))
    for g in scene.geometry.values():
        if isinstance(g, trimesh.path.Path3D) and len(g.entities):
            # the runner writes the edges as separate segments (glTF LINES): points in pairs
            pts = np.vstack([np.asarray(g.vertices)[e.points[:len(e.points) // 2 * 2]] for e in g.entities])
            segs = pts.reshape(-1, 2, 3)
    return np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces), segs


def _camera(eye, up):
    d = np.array(eye, dtype=np.float64)
    d /= np.linalg.norm(d)
    r = np.cross(np.array(up, dtype=np.float64), d)
    r /= np.linalg.norm(r)
    return r, np.cross(d, r), d      # right, up, towards the camera


def _view(verts, tris, segs, tri_colour, eye, up, size, pad=26):
    r, u, d = _camera(eye, up)
    basis = np.stack([r, u, d], axis=1)
    p = verts @ basis                                   # x right, y up, z towards the camera
    lo, hi = p[:, :2].min(0), p[:, :2].max(0)
    scale = (size - 2 * pad) / max(1e-9, float((hi - lo).max()))
    off = (size - (hi - lo) * scale) / 2
    px = np.column_stack([(p[:, 0] - lo[0]) * scale + off[0], size - 1 - ((p[:, 1] - lo[1]) * scale + off[1]), p[:, 2]])

    t = px[tris]                                        # (T, 3, 3)
    normal = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    length = np.linalg.norm(normal, axis=1)
    keep = (length > 1e-12) & ((normal @ d) > 0)        # facing the camera
    normal = normal[keep] / length[keep, None]
    t, colour = t[keep], tri_colour[keep]
    light = (d + 0.35 * r + 0.55 * u)
    light /= np.linalg.norm(light)
    shade = 0.42 + 0.58 * np.clip(normal @ light, 0, 1)
    rgb = np.clip(colour * shade[:, None], 0, 255).astype(np.uint8)

    # sample every triangle on a grid finer than a pixel, a bounded number of samples at a time: an assembly has
    # tens of millions of them, and this runs inside the server
    e = np.linalg.norm(t[:, [1, 2, 0], :2] - t[:, :, :2], axis=2).max(1)
    level = np.searchsorted(LEVELS, np.minimum(np.ceil(e / 0.7), LEVELS[-1]))
    t = t.astype(np.float32)
    img = np.empty((size, size, 3), dtype=np.uint8)
    img[:] = BG
    flat = img.reshape(-1, 3)
    zbuf = np.full(size * size, -np.inf, dtype=np.float32)
    near = np.empty(size * size, dtype=np.float32)
    who = np.empty(size * size, dtype=np.int64)
    for li in np.unique(level):
        n = LEVELS[li]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        m = (i + j) <= n
        w = (np.column_stack([i[m], j[m], n - i[m] - j[m]]) / n).astype(np.float32)      # (S, 3) barycentric
        sel = np.nonzero(level == li)[0]
        step = max(1, CHUNK // len(w))
        for k in range(0, len(sel), step):
            part = sel[k:k + step]
            pts = np.einsum("sk,tkc->tsc", w, t[part]).reshape(-1, 3)
            xi, yi = np.rint(pts[:, 0]).astype(np.int64), np.rint(pts[:, 1]).astype(np.int64)
            ok = (xi >= 0) & (xi < size) & (yi >= 0) & (yi < size)
            pix, z, c = (yi[ok] * size + xi[ok]), pts[ok, 2], np.repeat(part, len(w))[ok]
            order = np.argsort(z, kind="stable")                # far first: the nearest of this lot is written last
            near[:] = -np.inf
            near[pix[order]] = z[order]
            who[pix[order]] = c[order]
            won = near > zbuf                                   # and it only stays where it beats what is there
            zbuf[won] = near[won]
            flat[won] = rgb[who[won]]

    # the real edges, where nothing is in front of them
    if len(segs):
        s = segs @ basis
        a = np.column_stack([(s[:, 0, 0] - lo[0]) * scale + off[0], size - 1 - ((s[:, 0, 1] - lo[1]) * scale + off[1]), s[:, 0, 2]])
        b = np.column_stack([(s[:, 1, 0] - lo[0]) * scale + off[0], size - 1 - ((s[:, 1, 1] - lo[1]) * scale + off[1]), s[:, 1, 2]])
        steps = np.maximum(1, np.ceil(np.linalg.norm(b[:, :2] - a[:, :2], axis=1) / 0.6)).astype(np.int64)
        steps = np.minimum(steps, 4 * size)
        which = np.repeat(np.arange(len(a)), steps + 1)
        k = np.arange(len(which)) - np.repeat(np.cumsum(steps + 1) - (steps + 1), steps + 1)
        f = (k / np.repeat(steps, steps + 1))[:, None]
        pts = a[which] * (1 - f) + b[which] * f
        xi, yi = np.rint(pts[:, 0]).astype(np.int64), np.rint(pts[:, 1]).astype(np.int64)
        ok = (xi >= 0) & (xi < size) & (yi >= 0) & (yi < size)
        pix = yi[ok] * size + xi[ok]
        seen = pts[ok, 2] >= zbuf[pix] - max(0.35, 1.5 / scale)
        img.reshape(-1, 3)[pix[seen]] = EDGE
    return img, scale


def png(glb: Path, views=("iso", "top", "front", "right"), size=560, faces=None, highlight=None, title="") -> bytes:
    """highlight: {tag name: [face indices]}, needs faces (the faces.json list of the same build)."""
    verts, tris, segs = load(glb)
    colour = np.tile(BODY, (len(tris), 1))
    legend = []
    if faces and highlight:
        for n, (name, ids) in enumerate(highlight.items()):
            c = PALETTE[n % len(PALETTE)]
            for i in ids:
                if 0 <= i < len(faces):
                    start, count = faces[i]["tris"]
                    colour[start:start + count] = c
            legend.append((name, c))
    views = [v for v in views if v in VIEWS] or ["iso"]
    cols = 1 if len(views) == 1 else 2
    rows = (len(views) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * size, rows * size + 26), tuple(BG))
    draw = ImageDraw.Draw(sheet)
    lo, hi = verts.min(0), verts.max(0)
    for n, name in enumerate(views):
        img, scale = _view(verts, tris, segs, colour, *VIEWS[name], size)
        x0, y0 = (n % cols) * size, (n // cols) * size
        sheet.paste(Image.fromarray(img), (x0, y0))
        draw.rectangle([x0, y0, x0 + size - 1, y0 + size - 1], outline=(214, 216, 224))
        draw.text((x0 + 8, y0 + 6), f"{name}  ·  {10 / scale:.1f} mm per 10 px", fill=(70, 74, 90))
    dims = " x ".join(f"{v:.2f}" for v in (hi - lo))
    draw.text((8, rows * size + 7), f"{title}   {dims} mm   x {lo[0]:.2f}..{hi[0]:.2f}  y {lo[1]:.2f}..{hi[1]:.2f}  z {lo[2]:.2f}..{hi[2]:.2f}   (Z up)".strip(),
              fill=(40, 44, 56))
    for n, (name, c) in enumerate(legend):
        y = 24 + n * 16
        draw.rectangle([8, y, 20, y + 10], fill=c)
        draw.text((26, y - 1), name, fill=(40, 44, 56))
    out = io.BytesIO()
    sheet.save(out, format="PNG", optimize=True)
    return out.getvalue()
