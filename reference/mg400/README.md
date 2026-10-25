# MG400: Dobot's own description of the robot

- `mg400_description.urdf`: the robot description from [Dobot-Arm/MG400_ROS](https://github.com/Dobot-Arm/MG400_ROS)
  (`mg400_description/urdf`), MIT licence (`LICENSE`). Lengths in metres, as ROS has them. Its joint origins
  are the pivots of `notes/mg400_rakis/mg400.py`; its mimic rules (which joint follows which) are that Note's
  `follows`.
- `links.json`: each link mesh of that package (`mg400_description/meshes/*.STL`) measured in its own URDF
  frame, in mm: the box the Note's simplified link is held to (within 6 mm), its volume and triangle count.
  The meshes themselves are not kept here.

`tests/test_motion.py` moves the Note's joints and the URDF's joints to the same poses and asks that every
link land in the same place.
