"""
Grid tile, chunk 0, +Y side: open-bottom Gridfinity baseplate, 4 x 5 cells, the tile touching the nest.

Rules
- 168 x 210 mm, 24 mm tall, stands on the table; top level with the nest rim
- Gridfinity pocket profile per 42 mm cell, widening upwards (bins drop in from above)
- open bottom ("lite"): below the profile every cell is a straight hole down to the table
- cable arches 24 x 12 mm through every lattice wall at table level
- pipe_tunnel: square 16.4 mm tunnel along X, right through, in a solid beam; ties the tile to the nest
- dowel_tunnel: square 16.4 mm tunnel along Y, open at the y = 0 joint, 37 mm deep; half of a 70 mm dowel
- seam_face at x = -118.5 butts against the nest; joint_face at y = 0 meets grid_neg_0
- prints flat, top up, no supports (tunnel roofs are flat bridges), on a 256 x 256 mm bed
"""
from build123d import *
from rakis_common import P, levels, box, rrect

PARAMS = dict(P, chunk=0)   # chunk: index into P["chunks"]; 0 = next to the nest

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "stands on the table"},
    "top_face": {"kind": "planar_face", "normal": "+Z", "at": 7.28, "role": "top of the lattice, level with the nest rim"},
    "seam_face": {"kind": "planar_face", "normal": "+X", "at": -118.5, "role": "butts against the nest front"},
    "front_face": {"kind": "planar_face", "normal": "-X", "at": -286.5, "role": "butts against grid_pos_1"},
    "joint_face": {"kind": "planar_face", "normal": "-Y", "at": 0.0, "role": "meets grid_neg_0 on the centre line"},
    "pipe_tunnel": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe"},
    "dowel_tunnel": {"kind": "square_hole", "axis": "Y", "size": 16.4, "at": [-202.5, -6.92], "through": False, "role": "takes half of the 70 mm dowel across the joint"},
}


def cell_cutter(p, L):
    """Gridfinity pocket profile for one cell centred on x = y = 0, as one cutter.

    Four steps, each sketched at its top and cut downwards, narrowing going down
    (45 degree steps) or straight; the last one runs out through the bottom.
    """
    e, h = p["eps"], p["pitch"] / 2
    steps = [  # (z at the top of the step, depth, taper, half size, corner radius)
        (L.z_top, 2.15, 45.0, h - e, 4.0 - e),
        (L.z_top - 2.15, 1.8, 0.0, h - e - 2.15, 1.85 - e),
        (L.z_top - 3.95, 0.7, 45.0, h - e - 2.15, 1.85 - e),
        (L.z_pb, L.z_pb - L.T + 1, 0.0, h - e - 2.85, 1.15 - e),
    ]
    cutter = None
    for zs, d, taper, hh, r in steps:
        step = extrude(rrect(-hh, -hh, hh, hh, r, z=zs), amount=d, dir=(0, 0, -1), taper=taper)
        cutter = step if cutter is None else cutter + step
    return cutter


def build(p=PARAMS):
    L = levels(p)
    pt, T = p["pitch"], L.T
    chunk = p.get("chunk", 0)
    xa, xb = L.bounds[chunk]
    y0, y1 = 0.0, p["half_w"]

    tile = box(xa, xb, y0, y1, T, L.z_top)

    # Gridfinity pockets: one cutter, placed at every cell of this tile
    xs = [xa + pt / 2 + pt * i for i in range(round((xb - xa) / pt))]
    ys = [y0 + pt / 2 + pt * k for k in range(int(p["half_w"] // pt))]
    cell = cell_cutter(p, L)
    tile -= [Pos(cx, cy) * cell for cx in xs for cy in ys]

    # cable arches through every wall segment (the beams fill them back where needed)
    nw, tw = p["notch_w"] / 2, 4.0
    arches = []
    for cy in ys:                                 # walls across X (running along Y)
        for mx in [xa + pt * i for i in range(len(xs) + 1)]:
            arches.append(box(mx - tw, mx + tw, cy - nw, cy + nw, T - 1, T + p["notch_h"]))
    for cx in xs:                                 # walls across Y (running along X)
        for my in [y0 + pt * k for k in range(len(ys) + 1)]:
            arches.append(box(cx - nw, cx + nw, my - tw, my + tw, T - 1, T + p["notch_h"]))
    tile -= arches

    # beams: long one under the pipe line, short dowel beam at the y = 0 joint
    yl, xc = L.y_long, L.dowel_x[chunk]
    tile += [
        box(xa, xb, yl - L.bw, yl + L.bw, T, L.beam_top),
        box(xc - L.bw, xc + L.bw, 0.0, p["dowel_beam"] / 2, T, L.beam_top),
    ]

    # square tunnels, last, through everything
    dt = p["dowel"] / 2 + 2.0
    tile -= [
        box(xa - 1, xb + 1, yl - L.ht, yl + L.ht, L.t0, L.t1),
        box(xc - L.ht, xc + L.ht, -dt, dt, L.t0, L.t1),
    ]
    return tile

