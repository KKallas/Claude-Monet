"""
Grid tile, chunk 1, -Y side: open-bottom Gridfinity baseplate, 3 x 5 cells; mirror image of grid_pos_1.

Rules
- exact mirror of grid_pos_1 across the XZ plane (y -> -y); change grid_pos_0, not this file
- joint_face at y = 0 meets grid_pos_1; the dowel tunnels of the two tiles line up
"""
from build123d import *
from grid_pos_1 import PARAMS, build as build_pos

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "stands on the table"},
    "top_face": {"kind": "planar_face", "normal": "+Z", "at": 7.28, "role": "top of the lattice, level with the nest rim"},
    "seam_face": {"kind": "planar_face", "normal": "+X", "at": -286.5, "role": "butts against grid_neg_0"},
    "front_face": {"kind": "planar_face", "normal": "-X", "at": -412.5, "role": "front edge of the rig"},
    "joint_face": {"kind": "planar_face", "normal": "+Y", "at": 0.0, "role": "meets grid_pos_1 on the centre line"},
    "pipe_tunnel": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [-110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe"},
    "dowel_tunnel": {"kind": "square_hole", "axis": "Y", "size": 16.4, "at": [-349.5, -6.92], "through": False, "role": "takes half of the 70 mm dowel across the joint"},
}


def build(p=PARAMS):
    return build_pos(p).mirror(Plane.XZ)
