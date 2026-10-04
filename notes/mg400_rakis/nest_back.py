"""
Nest, back half: the plate the MG400 stands in (x >= 0 half), strung on the two long pipes.

Rules
- robot_floor: flat pocket floor at z = 0, robot base outline (190 x 190, r 10) + 0.5 mm clearance
- the pocket wall is a 20 degree ramp, 20 mm run, widening upwards (the robot self-centres)
- 24 mm tall, table to top; the underside lies flat on the table
- split_face at x = 0 mates with nest_front (its mirror image)
- pipe_tunnel_pos / pipe_tunnel_neg: square 16.4 mm tunnels along X, right through, for the 16 mm pipes
- sliced plate: 2 mm slices, 10 mm gaps; only the square tubes around the pipes cross the gaps
- end block (last 22.5 mm) is hollow: 0.8 mm floor, 2 mm walls and ribs, 1.2 mm under the ramp
- mouse ears (r 10, 0.4 mm) under the corners; they overhang the plate, snap off after printing
- prints flat, top up, on a 256 x 256 mm bed (128.5 x 253.42 with ears)
"""
import math
from build123d import *
from rakis_common import P, levels, box, rrect

PARAMS = dict(P)

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "sits on the table"},
    "robot_floor": {"kind": "planar_face", "normal": "+Z", "at": 0.0, "role": "the robot base stands here"},
    "top_face": {"kind": "planar_face", "normal": "+Z", "at": 7.28, "role": "top surface, level with the grid"},
    "split_face": {"kind": "planar_face", "normal": "-X", "at": 0.0, "role": "mates with nest_front"},
    "back_face": {"kind": "planar_face", "normal": "+X", "at": 118.5, "role": "the back L brackets butt against it"},
    "pipe_tunnel_pos": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe, +Y side"},
    "pipe_tunnel_neg": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [-110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe, -Y side"},
}


def pocket_cutter(p, L):
    """Ramped pocket: outline + clear + run at the top, tapering down to outline + clear at z = 0."""
    grow = p["clear"] + p["run"]
    h = p["base"] / 2 + grow
    top = rrect(-h, -h, h, h, p["base_r"] + grow, z=L.z_top)
    return extrude(top, amount=L.depth, dir=(0, 0, -1), taper=90.0 - p["ramp_angle"])


def build(p=PARAMS):
    L = levels(p)
    hx, hy, T, top = L.half_x, L.half_y, L.T, L.z_top

    # rounded plate with the ramped pocket
    nest = extrude(rrect(-hx, -hy, hx, hy, p["plate_r"], z=T), amount=p["H"])
    nest -= pocket_cutter(p, L)

    # split at x = 0: keep the back half
    nest &= box(0, hx + 1, -hy - 1, hy + 1, T - 1, top + 1)

    # sliced plate: between the tubes full height, over the tubes above the tube roof
    y_tube_in = L.y_in - p["rail_wall"]
    cuts = []
    c = p["mid_rib"] / 2 + p["slot"] / 2
    while c + p["slot"] / 2 <= hx - p["end_solid"] + 1e-6:
        xa, xb = c - p["slot"] / 2, c + p["slot"] / 2
        cuts.append(box(xa, xb, -y_tube_in, y_tube_in, T - 1, top + 1))
        cuts.append(box(xa, xb, y_tube_in, hy + 1, L.beam_top, top + 1))
        cuts.append(box(xa, xb, -hy - 1, -y_tube_in, L.beam_top, top + 1))
        c += p["slot"] + p["rib"]

    # hollow end block: closed box, ribs across, roof end_skin under the lowest point of the ramp
    x0e = hx - p["end_solid"] + p["end_wall"]
    x1e = hx - p["end_wall"]
    z_cav_top = (x0e - L.pocket_edge) * math.tan(L.th) - p["end_skin"]
    y_cav = L.y_in - p["rail_wall"] - p["end_wall"]
    for ya, yb in [(-y_cav, -49.0), (-47.0, -1.0), (1.0, 47.0), (49.0, y_cav)]:
        cuts.append(box(x0e, x1e, ya, yb, T + p["end_floor"], z_cav_top))

    nest -= cuts

    # mouse ears under the corners of the half
    ears = [
        Pos(xc, yc, T) * Cylinder(p["ear_r"], p["ear_h"], align=(Align.CENTER, Align.CENTER, Align.MIN))
        for xc in (hx, p["ear_r"] + 1.0)
        for yc in (hy - 5.0, -(hy - 5.0))
    ]
    nest += ears

    # square pipe tunnels, last, through everything
    nest -= [box(-1, hx + 1, s * L.y_long - L.ht, s * L.y_long + L.ht, L.t0, L.t1) for s in (1, -1)]
    return nest

