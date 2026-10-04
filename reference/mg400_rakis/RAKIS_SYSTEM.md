# MG400 rakis — system description (version F)

Reference for anyone (human or AI) designing parts that live on this rig:
input holders, workpiece fixtures, output holders, and powered "smart" modules.
Source of truth: `build_rakis_F.py` in this folder (Fusion 360 API script) and the
`F_report.json` it writes. If the script parameters change, regenerate this file.

## 1. What the rig is

A portable, shippable work table for a **Dobot MG400** desktop cobot, used as a
rental kit in schools. Everything is 3D printed (PLA, Bambu Lab X1C, bed 256 × 256 mm)
except two 16 mm pipes and two short pipe dowels. Nothing is glued; it assembles
from flat-packed parts with no tools.

Three functional zones, all on one flat top surface:

1. **Nest**: the plate the robot stands in. A self-centering pocket with a 20°
   ramp wall: if the robot is shoved it climbs the ramp and slides out; pushed back
   roughly, gravity drops it into exactly the same place. Students should not
   design anything that touches or fills the nest pocket or ramp.
2. **Grid**: a 7 × 10 Gridfinity baseplate (42 mm pitch) in front of the robot.
   **Every holder, fixture or module is a Gridfinity bin** that drops into this grid.
   This is the only interface students design against.
3. **Under-grid cable space**: the grid is an open-bottom ("lite") lattice standing
   on the table, with arches through every wall, so cables from powered modules run
   underneath and exit at the grid edges.

## 2. Coordinate system (model frame, mm)

- Origin: J1 axis of the robot, at the robot's bottom face (robot floor).
- **+X points to the back** (behind the robot). **The working area is at −X** (in front).
- **+Y is the operator's left** when standing in front of the rig facing the robot;
  −Y is the operator's right.
- +Z up. Key heights:

| level | z (mm) |
|---|---|
| table surface | −16.72 |
| robot floor (nest pocket floor) | 0.00 |
| top surface of grid and nest rim | **+7.28** |
| bottom of Gridfinity pocket profile | +2.63 |
| pipe tunnels (square, 16.4 mm) | −15.12 … +1.28 |

All rig parts are 24 mm tall (table to top surface).

**Robot frame:** assumed `X_robot = −x`, `Y_robot = −y` (robot rotated 180° about Z
relative to the model). The MG400's own Z zero is **not** at the base bottom.
This mapping is **unverified**: always calibrate with one touch-off on a known cell
(see §7) before trusting computed coordinates.

## 3. The robot (Dobot MG400)

- 4 axes (J1 base rotation, J2/J3 arm, J4 tool rotation), tool flange points straight down.
- Max reach 440 mm from J1 axis (less near table height; treat **≤ 400 mm** as safe).
  J1 range ±160°.
- Payload 500 g rated, 750 g max, **including** the end effector.
- Repeatability ±0.05 mm. The rig's position repeatability (nest, printed parts,
  Gridfinity fit) is about ±0.3–0.5 mm, so **holders must guide parts in** with
  chamfers/lead-ins; don't design for zero clearance.
- Collision detection stops the arm at roughly 12 N of contact force.
- Base footprint 190 × 190 mm, centred on J1.

## 4. The grid, cell addressing and coordinates

- Pitch 42 mm. 7 columns (depth) × 10 rows (width) = 70 cells, 294 × 420 mm.
- **Columns 1–7**: 1 is nearest the robot, 7 is farthest (front edge of rig).
- **Rows A–J**: A is the operator's right (−Y), J the operator's left (+Y).
- Cell centre: `x = −139.5 − 42·(col − 1)`, `y = −189 + 42·(row_index)` with A = 0 … J = 9.
- Grid edges: x from −118.5 (touching the nest) to −412.5; y from −210 to +210.

Practical reach zones (radius from J1):

- **Best accuracy / work zone**: r ≤ 300 mm: columns 1–3, rows C–H. Put the
  workpiece fixture (where the actual operation happens) here.
- **Normal**: 300–400 mm: fine for input/output holders.
- **Near the limit**: > 400 mm: cells A7, B7, C7, H7, I7, J7 (radii 405–435 mm);
  avoid for anything that needs depth or accuracy.

Recommended layout convention for lessons:
**input holder on one side (rows A–C), workpiece fixture in the middle (rows D–G,
columns 1–3), output holder on the other side (rows H–J).** The arm then sweeps
in one direction through the process.

### Cell table (model frame)

| cell | x (mm) | y (mm) | r from J1 (mm) | note |
|---|---|---|---|---|
| A1 | -139.5 | -189.0 | 235 |  |
| B1 | -139.5 | -147.0 | 203 |  |
| C1 | -139.5 | -105.0 | 175 | pipe beam under part of the opening |
| D1 | -139.5 | -63.0 | 153 |  |
| E1 | -139.5 | -21.0 | 141 |  |
| F1 | -139.5 | 21.0 | 141 |  |
| G1 | -139.5 | 63.0 | 153 |  |
| H1 | -139.5 | 105.0 | 175 | pipe beam under part of the opening |
| I1 | -139.5 | 147.0 | 203 |  |
| J1 | -139.5 | 189.0 | 235 |  |
| A2 | -181.5 | -189.0 | 262 |  |
| B2 | -181.5 | -147.0 | 234 |  |
| C2 | -181.5 | -105.0 | 210 | pipe beam under part of the opening |
| D2 | -181.5 | -63.0 | 192 |  |
| E2 | -181.5 | -21.0 | 183 | dowel beam under/next to cell |
| F2 | -181.5 | 21.0 | 183 | dowel beam under/next to cell |
| G2 | -181.5 | 63.0 | 192 |  |
| H2 | -181.5 | 105.0 | 210 | pipe beam under part of the opening |
| I2 | -181.5 | 147.0 | 234 |  |
| J2 | -181.5 | 189.0 | 262 |  |
| A3 | -223.5 | -189.0 | 293 |  |
| B3 | -223.5 | -147.0 | 268 |  |
| C3 | -223.5 | -105.0 | 247 | pipe beam under part of the opening |
| D3 | -223.5 | -63.0 | 232 |  |
| E3 | -223.5 | -21.0 | 224 | dowel beam under/next to cell |
| F3 | -223.5 | 21.0 | 224 | dowel beam under/next to cell |
| G3 | -223.5 | 63.0 | 232 |  |
| H3 | -223.5 | 105.0 | 247 | pipe beam under part of the opening |
| I3 | -223.5 | 147.0 | 268 |  |
| J3 | -223.5 | 189.0 | 293 |  |
| A4 | -265.5 | -189.0 | 326 |  |
| B4 | -265.5 | -147.0 | 303 |  |
| C4 | -265.5 | -105.0 | 286 | pipe beam under part of the opening |
| D4 | -265.5 | -63.0 | 273 |  |
| E4 | -265.5 | -21.0 | 266 |  |
| F4 | -265.5 | 21.0 | 266 |  |
| G4 | -265.5 | 63.0 | 273 |  |
| H4 | -265.5 | 105.0 | 286 | pipe beam under part of the opening |
| I4 | -265.5 | 147.0 | 303 |  |
| J4 | -265.5 | 189.0 | 326 |  |
| A5 | -307.5 | -189.0 | 361 |  |
| B5 | -307.5 | -147.0 | 341 |  |
| C5 | -307.5 | -105.0 | 325 | pipe beam under part of the opening |
| D5 | -307.5 | -63.0 | 314 |  |
| E5 | -307.5 | -21.0 | 308 |  |
| F5 | -307.5 | 21.0 | 308 |  |
| G5 | -307.5 | 63.0 | 314 |  |
| H5 | -307.5 | 105.0 | 325 | pipe beam under part of the opening |
| I5 | -307.5 | 147.0 | 341 |  |
| J5 | -307.5 | 189.0 | 361 |  |
| A6 | -349.5 | -189.0 | 397 |  |
| B6 | -349.5 | -147.0 | 379 |  |
| C6 | -349.5 | -105.0 | 365 | pipe beam under part of the opening |
| D6 | -349.5 | -63.0 | 355 |  |
| E6 | -349.5 | -21.0 | 350 | dowel beam under/next to cell |
| F6 | -349.5 | 21.0 | 350 | dowel beam under/next to cell |
| G6 | -349.5 | 63.0 | 355 |  |
| H6 | -349.5 | 105.0 | 365 | pipe beam under part of the opening |
| I6 | -349.5 | 147.0 | 379 |  |
| J6 | -349.5 | 189.0 | 397 |  |
| A7 | -391.5 | -189.0 | 435 | near reach limit |
| B7 | -391.5 | -147.0 | 418 | near reach limit |
| C7 | -391.5 | -105.0 | 405 | near reach limit; pipe beam under part of the opening |
| D7 | -391.5 | -63.0 | 397 |  |
| E7 | -391.5 | -21.0 | 392 |  |
| F7 | -391.5 | 21.0 | 392 |  |
| G7 | -391.5 | 63.0 | 397 |  |
| H7 | -391.5 | 105.0 | 405 | near reach limit; pipe beam under part of the opening |
| I7 | -391.5 | 147.0 | 418 | near reach limit |
| J7 | -391.5 | 189.0 | 435 | near reach limit |

## 5. Designing a holder (Gridfinity bin rules)

Every holder is a standard **Gridfinity bin**, so it inherits the grid's position.

- Footprint per unit: 42 mm pitch, bin outer size `42·n − 0.5` mm (41.5 mm for 1 unit),
  outer corner radius 3.75 mm.
- Bin base (bottom foot of each unit): standard Gridfinity foot, profile
  0.8 / 1.8 / 2.15 mm (45° / vertical / 45°), 4.75 mm tall. Use an existing
  Gridfinity generator or library for the foot; do not redraw it by eye.
- The bin's underside sits at about z = +2.6 and the top of its foot about 0.1 mm above
  the grid top (z ≈ +7.4). Measure on the real rig before relying on Z.
- Height in Gridfinity units of 7 mm is conventional but not required.
- Multi-cell bins (2×1, 2×2, 3×2…) are fine and stiffer. Keep any single printed part
  ≤ 250 × 250 mm.
- Optional 6 × 2 mm magnets in the foot for extra hold.
- Holders must not rise into the arm's path between other cells: keep tall features
  (> 60 mm) away from the robot's sweep, and check clearance for the tool and the
  part it carries.

What each holder type must do:

- **Input holder** presents raw parts at a known, repeatable pick pose:
  pocket or tray with 1–2 mm clearance and 45° lead-in chamfers at the top, a
  defined datum (corner or centre) the robot picks from, optionally a gravity-feed
  stack or ramp so the pick point never moves.
- **Workpiece fixture** holds a part still while the robot works on it (gluing,
  drawing, pressing, inspecting): locate the part on 3 points or 2 edges plus a
  floor, so it can only sit one way; resist the tool's force (the robot can push
  a few N); leave access for the tool from above; make the fixture's datum easy to touch
  off with the robot.
- **Output holder** receives finished parts: generous lead-ins (the robot places
  less precisely than it picks), or a chute/bin the part can simply be dropped into.

## 6. Powered and "smart" modules

- Cells are open underneath down to the table: free height under a cell is
  about **19 mm** (table z −16.72 to profile bottom z +2.63); the opening in each
  cell bottom is 36.3 × 36.3 mm.
- Every grid wall has a **24 mm wide × 12 mm high arch** at table level, so cables
  can run under the whole grid in any direction and exit at the grid edges.
- Cables are routed down through the cell under the module, then along the arches.
  Keep connectors small enough to pass a 24 × 12 mm arch (JST, Dupont, USB-C cable
  fine; full-size USB-A plugs are borderline).
- Obstructions under the grid (no free passage there):
  - pipe beams at y = ±110.5 (22.4 mm wide, from the table up to z +2.48), running the
    whole grid depth. They partly block the openings of rows C and H.
  - two short dowel beams across the centre line (y −40 … +40, 22.4 mm wide):
    one on the boundary between columns 2 and 3, one under the middle of column 6.
- Electronics that sit in the module go above the grid (inside the bin); only wires go
  below. Typical boards: ESP32 / M5Stack Atom (the course standard), sensors, servos,
  pressure sensors for the syringe dispenser, etc.

## 7. Calibration procedure (for instructions to include)

1. Put a 1×1 "calibration bin" with a sharp centre point or cross-hair in a known cell
   (suggested **D2**, close and accurate).
2. Jog the robot tool tip onto it and record the robot coordinates.
3. Offset = recorded − computed (from §4 with the frame mapping in §2).
4. Apply the same offset to every cell. Check one far cell (e.g. H5) to verify the
   rotation/mapping; if it's off by more than ~1 mm the frame mapping in §2 is wrong
   and must be fixed (rotation sign or axis swap).
5. Z: touch the grid top surface once; bins sit at a known height relative to it.

## 8. Physical build of the rig (for context)

- **Nest**: two halves (`nest_front`, `nest_back`, split at x = 0), each
  128.5 × 253 mm. Made of 2 mm slices on a 12 mm pitch joined only by square tubes
  around the pipes; 20 mm hollow end blocks carry the front/back ramp. Pocket =
  robot outline + 0.5 mm; ramp 20° over 20 mm; 3 mm flat rim.
- **Grid**: four tiles (`grid_pos_0`, `grid_neg_0` 168 × 210 mm; `grid_pos_1`,
  `grid_neg_1` 126 × 210 mm), split at y = 0 and between columns 4 and 5.
- **Pipes**: two 16 mm OD pipes at y = ±110.5, length = table depth − 30 mm
  (670 mm for a 700 mm table), through square 16.4 mm tunnels in nest and grid.
  Two 70 mm dowels of the same pipe join the left and right grid tiles.
- **L brackets**: printed L at each pipe end hook over the front and back table edges;
  the back pair presses against the nest, fixing the robot to the back table edge.
  Clamps go on the L's flat top.
- Printing: all parts top-up, no supports. Lesson learned: large solid blocks warp
  (PLA); keep holders hollow/ribbed, avoid solid masses > ~20 mm thick, use brims or
  mouse ears on parts > ~150 mm.

## 9. Constraints checklist for any student part

- [ ] Fits in whole Gridfinity units; standard foot; outer `42n − 0.5`.
- [ ] Sits inside the safe reach (≤ 400 mm) and the J1 ±160° sweep.
- [ ] Part + holder datum defined; lead-in chamfers on every receiving surface.
- [ ] Gripper/tool approach path clear from above; no tall walls on the robot side.
- [ ] Mass the robot moves (tool + part) ≤ 500 g.
- [ ] Printable on 256 × 256 bed without supports; no thick solid blocks.
- [ ] Cables (if any) go down through the cell and along the 24 × 12 mm arches,
      avoiding the pipe beams (rows C/H edge) and dowel beams.
- [ ] Calibrated position written down as cell name + offset, not raw coordinates.
