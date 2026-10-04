"""
Nest, front half: the x <= 0 half of the plate the MG400 stands in; mirror image of nest_back.

Rules
- exact mirror of nest_back across the YZ plane (x -> -x); change nest_back, not this file
- split_face at x = 0 mates with nest_back
- seam_face at x = -118.5 butts against the grid tiles
- pipe_tunnel_pos / pipe_tunnel_neg: square 16.4 mm tunnels along X, right through, in line with nest_back's
"""
from build123d import *
from nest_back import PARAMS, build as build_back

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "sits on the table"},
    "robot_floor": {"kind": "planar_face", "normal": "+Z", "at": 0.0, "role": "the robot base stands here"},
    "top_face": {"kind": "planar_face", "normal": "+Z", "at": 7.28, "role": "top surface, level with the grid"},
    "split_face": {"kind": "planar_face", "normal": "+X", "at": 0.0, "role": "mates with nest_back"},
    "seam_face": {"kind": "planar_face", "normal": "-X", "at": -118.5, "role": "butts against grid_pos_0 and grid_neg_0"},
    "pipe_tunnel_pos": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe, +Y side"},
    "pipe_tunnel_neg": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [-110.51, -6.92], "through": True, "role": "takes the 16 mm long pipe, -Y side"},
}


def build(p=PARAMS):
    return build_back(p).mirror(Plane.YZ)
