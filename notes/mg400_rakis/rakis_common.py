"""
Shared numbers and small helpers for the MG400 rakis (work table) Notes.

Not a Note. Ported from reference/mg400_rakis/build_rakis_F.py (Fusion 360, version F).
Model frame: origin = robot J1 axis at the robot floor, +X back, Z up, millimetres.
"""
import math
from build123d import Box, Plane, Pos, RectangleRounded

# The P dict of the Fusion script, plus the robot base outline the script
# projected from the robot model (base, base_r: measured_from_fusion.json).
P = dict(
    base=190.0, base_r=10.0,   # MG400 base outline, centred on J1
    clear=0.5, run=20.0, ramp_angle=20.0, rim=3.0,
    H=24.0,                    # total height, table to top surface
    plate_r=6.0,               # corner radius of the nest plate
    pitch=42.0, cols=7, chunks=(4, 3), half_w=210.0, eps=0.01,
    pipe_d=16.0, tunnel=16.4, tunnel_floor=1.6, skin=1.2, rail_wall=3.0,
    nest_skin=3.0,             # (unused in F) robot floor skin over the ribs
    slot=10.0, rib=2.0, end_solid=20.0, mid_rib=4.0,   # sliced nest plate
    notch_w=24.0, notch_h=12.0,                        # cable arches in the lattice walls
    dowel=70.0, dowel_beam=80.0,                       # short cross pipes over the centre joint
    reach=400.0,
    bed=(256.0, 256.0),        # Bambu X1C
    table_depth=700.0,         # table edge to table edge along the pipes
    L_len=45.0, L_lip=5.0, L_drop=30.0, L_wall=4.0, socket=30.0,
    end_wall=2.0, end_floor=0.8, end_skin=1.2, end_rib=2.0,   # hollow end blocks
    ear_r=10.0, ear_h=0.4,     # snap-off anchor discs under the plate corners
)


class Levels(dict):
    """dict of derived numbers, also readable as attributes (L.z_top)."""
    __getattr__ = dict.__getitem__


def levels(p=P):
    """The derived numbers, exactly as the Fusion script derives them."""
    th = math.radians(p["ramp_angle"])
    depth = p["run"] * math.tan(th)               # pocket depth = ramp rise
    z_top = depth                                 # top surface
    T = z_top - p["H"]                            # table
    z_pb = z_top - 4.65                           # bottom of the Gridfinity profile
    t0 = T + p["tunnel_floor"]                    # tunnel floor
    t1 = t0 + p["tunnel"]                         # tunnel roof
    beam_top = t1 + p["skin"]
    assert beam_top <= z_pb + 1e-6, "tunnel roof hits the bins: raise H"
    ht = p["tunnel"] / 2
    bw = ht + p["rail_wall"]                      # beam / rail half width
    pocket_edge = p["base"] / 2 + p["clear"]
    half_x = pocket_edge + p["run"] + p["rim"]    # nest half length (x)
    # tunnel as far in as the ramp allows: ramp height over its inner edge = roof + skin
    y_in = pocket_edge + max(0.0, beam_top) / math.tan(th)
    y_long = y_in + ht                            # pipe line
    half_y = max(y_in + p["tunnel"] + p["rail_wall"], half_x)
    x_seam = -half_x                              # nest front edge = grid back edge
    pt = p["pitch"]
    x_front = x_seam - pt * p["cols"]
    bounds, c0 = [], 0                            # grid chunks along x: (xa, xb)
    for n in p["chunks"]:
        bounds.append((x_seam - pt * (c0 + n), x_seam - pt * c0))
        c0 += n
    dowel_x = [(xa + xb) / 2 for (xa, xb) in bounds]
    zc = t0 + p["pipe_d"] / 2                     # pipe centre line
    x_edge_b = half_x + p["L_len"]                # table edges
    x_edge_f = x_edge_b - p["table_depth"]
    assert x_edge_f + p["L_len"] <= x_front + 1e-6, "table_depth too small"
    return Levels(
        th=th, depth=depth, z_top=z_top, T=T, z_pb=z_pb, t0=t0, t1=t1,
        beam_top=beam_top, ht=ht, bw=bw, pocket_edge=pocket_edge, half_x=half_x,
        y_in=y_in, y_long=y_long, half_y=half_y, x_seam=x_seam, x_front=x_front,
        bounds=bounds, dowel_x=dowel_x, zc=zc, tunnel_zc=(t0 + t1) / 2,
        x_edge_b=x_edge_b, x_edge_f=x_edge_f,
        pipe_x0=x_edge_f + (p["L_len"] - p["socket"]),
        pipe_x1=x_edge_b - (p["L_len"] - p["socket"]),
        L_top=t1 + p["L_wall"], L_hw=ht + p["L_wall"],
    )


def box(x0, x1, y0, y1, z0, z1):
    """Axis-aligned block between two corners."""
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def rrect(x0, y0, x1, y1, r, z=0.0):
    """Rounded rectangle face in the XY plane at height z (normal +Z)."""
    return Plane.XY.offset(z) * Pos((x0 + x1) / 2, (y0 + y1) / 2) * RectangleRounded(x1 - x0, y1 - y0, r)
