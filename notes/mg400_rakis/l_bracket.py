"""
L bracket (L_back_pos): holds the end of a long pipe on the table and hooks over the table edge.

Rules
- foot: 45 x 24.4 mm block on the table, butts against the back of the nest (x = 118.5)
- lip: 5 mm thick, hangs 30 mm below the table surface, hooks over the table edge (x = 163.5)
- socket: square 16.4 mm blind hole along X, 30 mm deep, open towards the nest; takes the pipe end
- 4 mm wall around and above the socket, 15 mm solid between the socket end and the table edge
- the other three brackets are mirror images (see rakis.py)
- fits a 256 x 256 mm bed (50 x 24.4 x 52 mm)
"""
from build123d import *
from rakis_common import P, levels, box

PARAMS = dict(P)

TAGS = {
    "table_face": {"kind": "planar_face", "normal": "-Z", "at": -16.72, "role": "foot sits on the table"},
    "nest_stop": {"kind": "planar_face", "normal": "-X", "at": 118.5, "role": "butts against the back of the nest"},
    "edge_hook": {"kind": "planar_face", "normal": "-X", "at": 163.5, "role": "lip face that hooks over the table edge"},
    "socket": {"kind": "square_hole", "axis": "X", "size": 16.4, "at": [110.51, -6.92], "through": False, "role": "takes the end of the 16 mm long pipe"},
}


def build(p=PARAMS):
    L = levels(p)
    edge, y0, y1 = L.x_edge_b, L.y_long - L.L_hw, L.y_long + L.L_hw
    foot = box(edge - p["L_len"], edge, y0, y1, L.T, L.L_top)
    lip = box(edge, edge + p["L_lip"], y0, y1, L.T - p["L_drop"], L.L_top)
    socket = box(edge - p["L_len"] - 1, edge - p["L_len"] + p["socket"],
                 L.y_long - L.ht, L.y_long + L.ht, L.t0, L.t1)
    return foot + lip - socket
