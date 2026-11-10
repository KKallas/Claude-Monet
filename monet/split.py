"""Parts bigger than the bed, printed in pieces: cut at planes, holes for dowels on both faces of every cut (lined up),
and each piece laid on its cut face, as it prints. A Note uses it in pieces(), beside build():

    from monet.split import split

    def build(p=PARAMS):          # the whole part: what an assembly puts together
        ...

    def pieces(p=PARAMS):         # what is printed: the export gives these, and fits_bed and solids hold for each
        return split(build(p), planes=[Plane.XY], dowel=(4, 12))

Each piece's `place` puts it back where it is in the whole (`piece.place * piece.shape`). Without planes, split cuts
the part across its longest side, evenly, into as few pieces as fit the bed.

The cut goes where a seam does least harm: on a strip, across it at a gap or along a rib; never through a hole or a
thin wall. A doubly curved sheet prints best upright on its cut face, which is how a piece is laid.
"""
import math
from dataclasses import dataclass, field

from build123d import Cylinder, Keep, Location, Plane, Pos, Shape, Vector


@dataclass
class Piece:
    name: str
    shape: Shape            # lying as it prints: on its biggest cut face, on z = 0, centred on x = y = 0
    place: Location         # place * shape is the piece where it is in the whole part
    dowels: list = field(default_factory=list)      # the dowel holes in it: [x, y, z] in the whole part's frame


def _planes_for(part, bed, margin=4.0):
    """Planes across the longest side of the part, evenly spaced, so that every piece is shorter than the bed."""
    bb = part.bounding_box()
    sizes = [bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z]
    lows = [bb.min.X, bb.min.Y, bb.min.Z]
    a = max(range(3), key=lambda k: sizes[k])
    room = max(bed) - margin
    n = max(1, math.ceil(sizes[a] / room))
    normal = [Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1)][a]
    out = []
    for k in range(1, n):
        o = [0.0, 0.0, 0.0]
        o[a] = lows[a] + sizes[a] * k / n
        out.append(Plane(origin=tuple(o), z_dir=normal))
    return out


def _solids(shape):
    return [s for s in (shape.solids() if shape is not None else []) if s.volume > 1e-6]


def _cut_faces(piece, plane):
    """The faces of a piece that lie in the cut plane."""
    n, o = plane.z_dir, plane.origin
    out = []
    for f in piece.faces():
        c = f.center()
        if abs((c - o).dot(n)) < 1e-4 and f.geom_type.name == "PLANE" and abs(abs(f.normal_at(c).dot(n)) - 1) < 1e-6:
            out.append(f)
    return out


def _dowel_points(face, plane, count, keep_off):
    """Where dowels go on one cut face: along its longest direction, as far apart as they can be while keeping
    `keep_off` from every edge."""
    pts = [plane.to_local_coords(v) for v in face.vertices()] or [plane.to_local_coords(face.center())]
    c = face.center()
    local = plane.to_local_coords(c)
    # the longest direction of the face, in the plane: from its outline's spread
    xs, ys = [p.X - local.X for p in pts], [p.Y - local.Y for p in pts]
    sxx, syy, sxy = sum(x * x for x in xs), sum(y * y for y in ys), sum(x * y for x, y in zip(xs, ys))
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    d = (math.cos(angle), math.sin(angle))
    span = max(abs(x * d[0] + y * d[1]) for x, y in zip(xs, ys)) if pts else 0.0

    def fits(u, v):
        q = plane.from_local_coords((u, v, 0))
        return face.is_inside(q) and min(w.distance_to(q) for w in face.wires()) >= keep_off

    if count == 1:
        return [plane.from_local_coords((local.X, local.Y, 0))] if fits(local.X, local.Y) else []
    for frac in (0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1):
        ts = [-frac * span + 2 * frac * span * k / (count - 1) for k in range(count)]
        cand = [(local.X + t * d[0], local.Y + t * d[1]) for t in ts]
        if all(fits(u, v) for u, v in cand):
            return [plane.from_local_coords((u, v, 0)) for u, v in cand]
    return []


def _lay(piece, normal_out):
    """The piece turned so that normal_out points down, then put on z = 0, centred on x = y = 0: (laid, place)."""
    down = Vector(0, 0, -1)
    n = Vector(normal_out).normalized()
    turn = Location()
    dot = max(-1.0, min(1.0, n.dot(down)))
    if dot < 1 - 1e-9:
        axis = n.cross(down)
        if axis.length < 1e-9:                      # pointing straight up: half a turn about X
            axis = Vector(1, 0, 0)
        turn = Location((0, 0, 0), tuple(axis.normalized()), math.degrees(math.acos(dot)))
    turned = turn * piece
    bb = turned.bounding_box()
    move = Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z)
    laid = move * turned
    return laid, (move * turn).inverse()


def split(part, planes=None, bed=(256, 256, 256), joint="dowel", dowel=(4.0, 12.0), clearance=0.15, count=2,
          wall=1.6, name="piece") -> list:
    """The part cut at these planes (build123d Planes; their z_dir is the cut's normal), or across its longest side
    to fit the bed when none are given. joint "dowel": `count` holes on each cut face, lined up across the cut, for
    dowels of dowel = (diameter, length) mm, `clearance` mm wider than the dowel all round, each hole half the
    dowel's length deep and 0.5 mm more; kept `wall` mm off every edge (a face too small for that gets none, and the
    piece says so in `dowels` being empty). joint None: plain cuts. Returns [Piece], each laid on its biggest cut face."""
    if joint not in ("dowel", None):
        raise ValueError("joint is 'dowel' or None (laps, dovetails and bolt tabs are not made yet)")
    planes = list(planes) if planes is not None else _planes_for(part, bed)
    bits = _solids(part) or [part]
    cuts = []           # (plane, faces of the cut)
    for plane in planes:
        nxt, faces = [], []
        for b in bits:
            top, bottom = b.split(plane, keep=Keep.BOTH)
            sides = _solids(top) + _solids(bottom)
            if len(sides) < 2:
                nxt.append(b)
                continue
            nxt += sides
            faces += [f for s in _solids(top) for f in _cut_faces(s, plane)]
        bits = nxt
        cuts.append((plane, faces))
    holes = []          # (point, normal)
    if joint == "dowel":
        dia, length = dowel
        for plane, faces in cuts:
            for f in faces:
                for q in _dowel_points(f, plane, count, dia / 2 + clearance + wall):
                    holes.append((q, plane.z_dir))
    out = []
    for i, b in enumerate(bits):
        mine = []
        for q, n in holes:
            if b.distance_to(q) > 1e-3:          # a hole only in the pieces on either side of its cut
                continue
            r, depth = dowel[0] / 2 + clearance, dowel[1] / 2 + 0.5
            b = b - Plane(origin=tuple(q), z_dir=tuple(n)) * Cylinder(r, 2 * depth)
            mine.append([round(q.X, 4), round(q.Y, 4), round(q.Z, 4)])
        # lay it on its biggest cut face, looking down out of the piece
        best, out_n = None, None
        for plane, _ in cuts:
            for f in _cut_faces(b, plane):
                if best is None or f.area > best.area:
                    side = (b.center() - plane.origin).dot(plane.z_dir)
                    best, out_n = f, plane.z_dir * (-1 if side > 0 else 1)
        laid, place = _lay(b, out_n) if best is not None else (b, Location())
        out.append(Piece(f"{name}_{i + 1}", laid, place, mine))
    return out
