"""
Rod foot: holds the end of a 16 mm aluminium rod on the table edge.

Rules
- rod_bore: square tunnel, 16.4 mm, runs through the part along X
- base: flat, sits on the table
- printable on a 256 x 256 mm bed without supports
- no solid section thicker than 20 mm (PLA warps)
"""
from build123d import *

PARAMS = dict(rod=16.0, clearance=0.2, wall=3.0, length=45.0)

TAGS = {
    "rod_bore": {"kind": "square_hole", "axis": "X", "at": [0, 11.2], "size": 16.4, "role": "takes the 16 mm rod"},
    "base": {"kind": "planar_face", "normal": "-Z", "at": 0, "role": "sits on the table"},
}


def build(p=PARAMS):
    s = p["rod"] + 2 * p["clearance"]
    outer = s + 2 * p["wall"]
    with BuildPart() as part:
        Box(p["length"], outer, outer, align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, p["wall"] + s / 2)):
            Box(p["length"], s, s, mode=Mode.SUBTRACT)
    return part.part
