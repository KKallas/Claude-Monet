"""
MG400: the Dobot desktop robot arm, its nine links as Dobot drew them, joined as the real one moves.

In the robot's own frame, as Dobot's URDF has it (Dobot-Arm/MG400_ROS, MIT licence): origin at the
middle of the base's underside, +X forward (towards the work), Z up, mm. On the rakis table the robot
stands in the nest turned half round: robot +X is model -X.

Rules
- each link is Dobot's own mesh of it (mg400_mesh.py), within 0.4 mm, in the frame the URDF gives it
- pivots where the URDF puts them, to the hundredth of a mm
- J1 turns the turret about Z, 5 mm behind the middle of the base (as the URDF has it)
- J2 tilts the upper arm forward; J3 is the forearm's angle below horizontal, whatever J2 is:
  two parallelograms keep it so, and keep the tool pointing straight down
- the links that close the parallelograms follow J2 and J3 (follows), so no loop has to be solved
- J4 turns the tool about its own axis
- ranges from Dobot's datasheet: J1 ±160°, J2 -25…85°, J3 -25…105°, J4 ±180°
- the pins sit in their holes as Dobot drew them: those overlaps, as built, are not clashes
"""
from build123d import *
import mg400_mesh

PARAMS = {}

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




def build(p=PARAMS):
    parts = []
    for name, where in AT.items():
        part = Pos(*where) * mg400_mesh.link(name)
        part.label = name
        parts.append(part)
    return Compound(children=parts, label="mg400")
