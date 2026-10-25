"""
MG400: the Dobot desktop robot arm, as links that move as the real one does.

In the robot's own frame, as Dobot's URDF has it (Dobot-Arm/MG400_ROS, MIT licence):
origin at the middle of the base's underside, +X forward (towards the work), Z up, mm.
On the rakis table the robot stands in the nest turned half round: robot +X is model -X.

Rules
- pivots where the URDF puts them, to the hundredth of a mm; links are simplified, each within a few mm
  of the real link's size (reference/mg400/links.json)
- J1 turns the turret about Z, 5 mm behind the middle of the base (as the URDF has it)
- J2 tilts the upper arm forward; J3 is the forearm's angle below horizontal, whatever J2 is:
  two parallelograms keep it so, and keep the tool pointing straight down
- the links that close the parallelograms follow J2 and J3 (follows), so no loop has to be solved
- J4 turns the tool about its own axis
- ranges from Dobot's datasheet: J1 ±160°, J2 -25…85°, J3 -25…105°, J4 ±180°
- links sit side by side across the arm (y), so nothing overlaps as built
"""
from build123d import *

PARAMS = dict(base=190.0, base_r=10.0, base_h=109.0)

TAGS = {
    "base_floor": {"kind": "planar_face", "normal": "-Z", "at": 0.0, "role": "the underside of the base: stands in the nest"},
}

GROUND = "base"

JOINTS = {
    "j1": {"kind": "revolute", "moves": "turret", "on": "base", "axis": {"origin": [-5.0, 0.0, 109.0], "dir": "Z"}, "range": [-160.0, 160.0]},
    "j2": {"kind": "revolute", "moves": "upper_arm", "on": "turret", "axis": {"origin": [-0.4711, -30.5, 250.5], "dir": "Y"}, "range": [-25.0, 85.0]},
    "j2_rod": {"kind": "revolute", "moves": "upper_rod", "on": "turret", "axis": {"origin": [38.5008, -35.7749, 227.9957], "dir": "Y"}, "follows": {"j2": 1.0}},
    "elbow": {"kind": "revolute", "moves": "elbow", "on": "upper_arm", "axis": {"origin": [-1.5216, -24.0, 425.4968], "dir": "Y"}, "follows": {"j2": -1.0}},
    "j3": {"kind": "revolute", "moves": "forearm", "on": "elbow", "axis": {"origin": [66.375, -23.5, 437.4688], "dir": "Y"}, "range": [-25.0, 105.0]},
    "j3_rod": {"kind": "revolute", "moves": "forearm_rod", "on": "upper_rod", "axis": {"origin": [37.4495, 0.0, 402.9969], "dir": "Y"}, "follows": {"j3": 1.0, "j2": -1.0}},
    "wrist": {"kind": "revolute", "moves": "wrist", "on": "forearm_rod", "axis": {"origin": [212.4193, -17.0, 406.2488], "dir": "Y"}, "follows": {"j3": -1.0}},
    "j4": {"kind": "revolute", "moves": "tool", "on": "wrist", "axis": {"origin": [278.4189, 0.0, 437.2496], "dir": "Z"}, "range": [-180.0, 180.0]},
}

# where each link's frame is as built (all joints at 0), from the URDF's joint origins
AT = {
    "base": (0.0, 0.0, 0.0),
    "turret": (-5.0, 0.0, 109.0),
    "upper_arm": (-0.4711, -30.5, 250.5),
    "upper_rod": (38.5008, -35.7749, 227.9957),
    "elbow": (-1.5216, -24.0, 425.4968),
    "forearm": (66.375, -23.5, 437.4688),
    "forearm_rod": (37.4495, 0.0, 402.9969),
    "wrist": (212.4193, -17.0, 406.2488),
    "tool": (278.4189, 0.0, 437.2496),
}


def plate(points, r, y0, y1):
    """A flat link: the hull of circles of radius r about points (x, z), from y0 to y1 (link frame)."""
    edges = []
    for x, z, *rr in points:
        edges += (Pos(x, z) * Circle(rr[0] if rr else r)).edges()
    return Pos(0, y1, 0) * Rot(90, 0, 0) * extrude(make_hull(edges), y1 - y0)


def pin(x, z, r, y0, y1):
    """A round pin across the arm (along y), link frame."""
    return Pos(x, (y0 + y1) / 2, z) * Rot(90, 0, 0) * Cylinder(r, y1 - y0)


def pair(points, r, y_mid, inner, outer):
    """Two plates, either side of y_mid, between inner and outer off it."""
    return plate(points, r, y_mid - outer, y_mid - inner) + plate(points, r, y_mid + inner, y_mid + outer)


def links(p):
    """Every link in its own frame (the URDF's), as built."""
    out = {}
    b = p["base"]
    out["base"] = extrude(RectangleRounded(b, b, p["base_r"]), p["base_h"])

    # the turret: a block, with a cheek each side holding the arm's axles; the arms work in the slot between
    block = Pos(4, 0, 47.5) * Box(160, 80, 95)
    cheek = [(-75.5, 0.5, 0.5), (83.5, 0.5, 0.5), (-75.5, 95, 0.5), (83.5, 60, 0.5), (42, 110, 42)]
    out["turret"] = block + plate(cheek, 1, -75.5, -40) + plate(cheek, 1, 40, 79)

    # upper arm: two side plates and a web behind; at the top the elbow plate hangs between them
    arm = [(0, 0, 10), (-1.0505, 174.9968, 10), (-36, 25, 0.5), (-36, 150, 0.5)]
    web = Pos(-33, 30.5, 87.5) * Box(6, 49, 125)
    out["upper_arm"] = plate(arm, 10, 0, 6) + plate(arm, 10, 55, 61) + web

    # the rod of the rear parallelogram: an axle from cheek to cheek, a hub on it between the upper arm's plates
    # (they swing past it), two thin plates up to the forearm rod's pivot
    y = 35.7749
    rod = [(0, 0), (-1.0513, 175.0012)]
    out["upper_rod"] = pin(0, 0, 9, 0, 75.7) + pin(0, 0, 20, y - 23, y + 23) + pair(rod, 8, y, 4.5, 9.5)

    # the elbow plate: stays level; holds the forearm and the top of the rear rod. Two halves, as the real one:
    # the pins of its pivots hold them together, and a spacer would stand where the forearm rod's tail swings
    elbow = [(0, 0, 10), (67.8966, 11.972, 10), (38.9711, -22.4999, 10), (35, 22.5, 10)]
    out["elbow"] = pair(elbow, 10, 24.0, 18, 24)

    # forearm: two side plates, deeper in the middle, and a web over them; at its far end the wrist hangs on a pin
    fore = [(0, 0, 10), (174.9698, 3.2519, 10), (70, -11.7, 8), (120, -11.7, 8)]
    out["forearm"] = pair(fore, 10, 23.5, 24.5, 30.5) + Pos(100, 23.5, 16) * Box(120, 61, 8)

    # the rod of the front parallelogram, with its short tail behind the pivot
    out["forearm_rod"] = plate([(0, 0, 8), (174.9698, 3.2519, 8), (-43, 0, 5), (80, -8.9, 5)], 8, -4, 4)

    # the wrist: stays level; plates either side of the rod's end, a pin for the forearm, the tool's housing
    d = (28.9255, 34.4719)
    wrist = [(0, 0, 9), (d[0], d[1], 9), (44, -30, 0.5), (44, 40, 0.5)]
    housing = Pos(66, 17, 2.25) * Box(44, 44, 86.5) - Pos(66, 17, -1.25) * Box(41, 41, 79.5)
    out["wrist"] = pair(wrist, 9, 17.0, 5.5, 11) + pin(d[0], d[1], 5, 17 - 24, 17 + 24) + housing

    # the tool: round, so it turns inside its housing; a flange under it shows which way it is turned
    out["tool"] = Pos(0, 0, -35) * Cylinder(19, 70) + Pos(0, 0, -77.5) * Cylinder(6, 15) + Pos(6, 0, -83) * Box(30, 12, 4)
    return out


def build(p=PARAMS):
    parts = []
    for name, shape in links(p).items():
        part = Pos(*AT[name]) * shape
        part.label = name
        parts.append(part)
    return Compound(children=parts, label="mg400")
