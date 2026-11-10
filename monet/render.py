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
PALETTE = [(226, 111, 40), (40, 150, 200), (60, 170, 90), (190, 70, 170), (210, 170, 30), (90, 100, 220), (220, 70, 80), (20, 160, 150),
           (150, 120, 90), (120, 190, 60), (230, 130, 170), (110, 130, 150), (170, 90, 60), (70, 200, 190), (160, 150, 230), (200, 200, 90)]
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


def _view(verts, tris, segs, tri_colour, eye, up, size, pad=26, fit=None):
    """fit: (lo, hi) of the view in the camera's x and y, to hold it still over several pictures (an animation)."""
    r, u, d = _camera(eye, up)
    basis = np.stack([r, u, d], axis=1)
    p = verts @ basis                                   # x right, y up, z towards the camera
    lo, hi = (p[:, :2].min(0), p[:, :2].max(0)) if fit is None else (np.asarray(fit[0]), np.asarray(fit[1]))
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


def posed(verts, tris, segs, parts, frames):
    """The mesh with each part moved by its frame ({part name: 4x4}): an assembly at a pose of its joints. Parts are
    ranges of the triangles and edges (faces.json); no vertex is shared between parts."""
    verts, segs = verts.copy(), segs.copy()
    for part in parts:
        T = frames.get(part["name"])
        if T is None or np.allclose(T, np.eye(4)):
            continue
        T = np.asarray(T, dtype=np.float64)
        start, n = part["tris"]
        idx = np.unique(tris[start:start + n].reshape(-1))
        verts[idx] = verts[idx] @ T[:3, :3].T + T[:3, 3]
        if "edges" in part and len(segs):
            a, m = part["edges"]
            segs[a:a + m] = segs[a:a + m] @ T[:3, :3].T + T[:3, 3]
    return verts, segs


def png(glb: Path, views=("iso", "top", "front", "right"), size=560, faces=None, highlight=None, title="", parts=None, frames=None) -> bytes:
    """highlight: {tag name: [face indices]}, needs faces (the faces.json list of the same build). parts and frames:
    the assembly's parts (faces.json) and where each is moved to ({name: 4x4}), to see it at a pose of its joints."""
    verts, tris, segs = load(glb)
    if parts and frames:
        verts, segs = posed(verts, tris, segs, parts, frames)
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


def animation(glb: Path, parts: list, poses: list, view: str = "iso", size: int = 480, fps: float = 15, hide=(), title: str = "",
              format: str = "gif") -> bytes:
    """A GIF or an MP4 of an assembly moving: one picture per pose (poses: [{part: 4x4}]), all from one camera that
    holds the whole motion. hide: parts left out of the picture (keep-outs). Every part in its own colour, as look()
    paints an assembly. An MP4 is H.264, made by ffmpeg."""
    size += size % 2          # a video's sides are even
    verts, tris, segs = load(glb)
    colour = np.tile(BODY, (len(tris), 1))
    keep_t, keep_s = np.ones(len(tris), dtype=bool), np.ones(len(segs), dtype=bool)
    for n, q in enumerate(parts):
        a, m = q["tris"]
        if q["name"] in hide:
            keep_t[a:a + m] = False
            if "edges" in q:
                keep_s[q["edges"][0]:q["edges"][0] + q["edges"][1]] = False
        elif len(parts) > 1:
            colour[a:a + m] = PALETTE[n % len(PALETTE)]
    eye, up = VIEWS[view if view in VIEWS else "iso"]
    r, u, d = _camera(eye, up)
    basis = np.stack([r, u, d], axis=1)
    shown = np.unique(tris[keep_t].reshape(-1))
    moved = [posed(verts, tris, segs, parts, frames) for frames in poses]
    lo = np.min([(v[shown] @ basis)[:, :2].min(0) for v, _ in moved], axis=0)
    hi = np.max([(v[shown] @ basis)[:, :2].max(0) for v, _ in moved], axis=0)
    images = []
    for n, (v, sg) in enumerate(moved):
        img, _ = _view(v, tris[keep_t], sg[keep_s], colour[keep_t], eye, up, size, fit=(lo, hi))
        pic = Image.fromarray(img)
        ImageDraw.Draw(pic).text((8, 6), f"{title}  {n + 1}/{len(moved)}".strip(), fill=(70, 74, 90))
        images.append(pic if format == "mp4" else pic.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))
    if format == "mp4":
        return mp4(images, fps)
    out = io.BytesIO()
    images[0].save(out, format="GIF", save_all=True, append_images=images[1:], duration=max(20, round(1000 / fps)), loop=0, optimize=False)
    return out.getvalue()


def mp4(images: list, fps: float) -> bytes:
    """RGB pictures of one size as an H.264 MP4 that plays anywhere (yuv420p, the index at the front), by ffmpeg."""
    import shutil
    import subprocess
    import tempfile
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this server: a video cannot be made (a GIF can)")
    w, h = images[0].size
    raw = b"".join(np.asarray(im.convert("RGB"), dtype=np.uint8).tobytes() for im in images)
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "out.mp4"
        done = subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps:g}",
                               "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
                               "-movflags", "+faststart", str(out)], input=raw, capture_output=True, timeout=600)
        if done.returncode != 0 or not out.exists():
            raise RuntimeError(f"ffmpeg could not make the video: {done.stderr.decode(errors='replace')[-300:]}")
        return out.read_bytes()
