"""
Rakis: the MG400 work table, assembled in the model frame (origin = J1 axis at the robot floor, +X back, Z up).

Rules
- printed parts: nest_back, nest_front, four grid tiles, four L brackets
- bought parts: two 16 mm long pipes (670 mm), two 16 mm dowels (70 mm), drawn as plain cylinders
- the long pipes tie each nest half to the grid; the dowels join the grid halves across y = 0
- every grid cell has a snap point at its centre on the grid top (A1 … J7, as RAKIS_SYSTEM.md names them):
  a Gridfinity block put there sits in that cell's pocket
- the table is 700 mm deep along the pipes: back edge at x = 163.5, front edge at x = -536.5
- children carry the body names of the Fusion model (label)

Motion
- the L brackets clamp to the table and hold the long pipes: together they are the rails, and they stay put
- the nest halves, the grid tiles and the dowels are one rigid top that slides along the pipes
- as built the back L brackets butt against the nest; the top can slide 79 mm forward before the
  grid meets the front L brackets (the table is 700 mm deep, the top 621 mm)
"""
from build123d import *
from rakis_common import P, cell_snaps, levels
import nest_back, nest_front, grid_pos_0, grid_pos_1, grid_neg_0, grid_neg_1, l_bracket

PARAMS = dict(P)

TAGS = {
    "pipe_tunnel": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "role": "the tunnel the +Y long pipe runs in: the top slides along it"},
}

GROUND = "rails"

# where a Gridfinity block may be put: the centre of every cell, on the grid top (A1 … J7)
SNAPS = cell_snaps(P)

JOINTS = {
    "rails": {"kind": "rigid", "parts": ["L_back_pos", "L_back_neg", "L_front_pos", "L_front_neg", "pipe_long_pos", "pipe_long_neg"]},
    "top": {"kind": "rigid", "parts": ["nest_back", "nest_front", "grid_pos_0", "grid_pos_1", "grid_neg_0", "grid_neg_1", "pipe_dowel_0", "pipe_dowel_1"]},
    "slide": {"kind": "slider", "moves": "top", "on": "rails", "axis": "pipe_tunnel", "range": [-79.0, 0.0]},
}


def build(p=PARAMS):
    L = levels(p)
    r = p["pipe_d"] / 2
    parts = {
        "nest_front": nest_front.build(p),
        "nest_back": nest_back.build(p),
        "grid_pos_0": grid_pos_0.build(p),
        "grid_neg_0": grid_neg_0.build(p),
        "grid_pos_1": grid_pos_1.build(p),
        "grid_neg_1": grid_neg_1.build(p),
    }

    # long pipes along X, in the tunnels
    x_mid, length = (L.pipe_x0 + L.pipe_x1) / 2, L.pipe_x1 - L.pipe_x0
    for s, side in ((1, "pos"), (-1, "neg")):
        parts["pipe_long_" + side] = Pos(x_mid, s * L.y_long, L.zc) * Rot(0, 90, 0) * Cylinder(r, length)

    # L brackets: back ones against the nest, front ones mirrored to the other table edge
    back = l_bracket.build(p)
    front = back.mirror(Plane.YZ.offset((L.x_edge_b + L.x_edge_f) / 2))
    for tag, part in (("back", back), ("front", front)):
        parts["L_%s_pos" % tag] = part
        parts["L_%s_neg" % tag] = part.mirror(Plane.XZ)

    # dowels along Y, across the y = 0 joint
    for j, xc in enumerate(L.dowel_x):
        parts["pipe_dowel_%d" % j] = Pos(xc, 0, L.zc) * Rot(90, 0, 0) * Cylinder(r, p["dowel"])

    for name, part in parts.items():
        part.label = name
    return Compound(children=list(parts.values()), label="rakis")
