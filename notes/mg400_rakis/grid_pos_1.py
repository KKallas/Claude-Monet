"""
Grid tile, chunk 1, +Y side: open-bottom Gridfinity baseplate, 3 x 5 cells, the front tile.

Rules
- same tile as grid_pos_0 with chunk = 1 (3 columns): 126 x 210 mm; change grid_pos_0, not this file
- seam_face at x = -286.5 butts against grid_pos_0; joint_face at y = 0 meets grid_neg_1
- pipe_tunnel: square 16.4 mm tunnel along X, right through, in line with grid_pos_0's
- dowel_tunnel: square 16.4 mm tunnel along Y, open at the y = 0 joint, 37 mm deep
"""
from build123d import *
from grid_pos_0 import PARAMS as _TILE, build as build_tile

PARAMS = dict(_TILE, chunk=1)

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "stands on the table"},
    "top_face": {"kind": "planar_face", "normal": "+Z", "at": 7.28, "role": "top of the lattice, level with the nest rim"},
    "seam_face": {"kind": "planar_face", "normal": "+X", "at": -286.5, "role": "butts against grid_pos_0"},
    "front_face": {"kind": "planar_face", "normal": "-X", "at": -412.5, "role": "front edge of the rig"},
    "joint_face": {"kind": "planar_face", "normal": "-Y", "at": 0.0, "role": "meets grid_neg_1 on the centre line"},
    "pipe_tunnel": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe"},
    "dowel_tunnel": {"kind": "square_hole", "axis": "Y", "size": 16.4, "at": [-349.5, -6.92], "through": False, "role": "takes half of the 70 mm dowel across the joint"},
}


def build(p=PARAMS):
    return build_tile(dict(p, chunk=1))
