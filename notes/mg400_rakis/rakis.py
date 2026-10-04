"""
Rakis: the MG400 work table, assembled in the model frame (origin = J1 axis at the robot floor, +X back, Z up).

Rules
- printed parts: nest_back, nest_front, four grid tiles, four L brackets
- bought parts: two 16 mm long pipes (670 mm), two 16 mm dowels (70 mm), drawn as plain cylinders
- the long pipes tie each nest half to the grid; the dowels join the grid halves across y = 0
- the table is 700 mm deep along the pipes: back edge at x = 163.5, front edge at x = -536.5
- children carry the body names of the Fusion model (label)
"""
from build123d import *
from rakis_common import P, levels
import nest_back, nest_front, grid_pos_0, grid_pos_1, grid_neg_0, grid_neg_1, l_bracket

PARAMS = dict(P)

TAGS = {}


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
