# build123d for Notes: cheat sheet and traps

The server runs build123d 0.13. `from build123d import *` at the top of every Note. Millimetres,
Z up. Return one shape from `build()`.

## Two styles; pick one per Note

**Builder** (reads like steps; good for most parts):

```python
with BuildPart() as part:
    Box(60, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))     # sits on z = 0
    with Locations((20, 0, 10)):
        Cylinder(5, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))  # a post on top
    with GridLocations(40, 20, 2, 2):
        Hole(1.7)                                                      # through holes, radius 1.7
    with BuildSketch(Plane.XY.offset(10)):
        RectangleRounded(30, 20, 3)
    extrude(amount=-4, mode=Mode.SUBTRACT)                             # a pocket, 4 deep
return part.part
```

**Algebra** (reads like a formula; good for small parts and for placing things):

```python
plate = Pos(0, 0, 5) * Box(60, 40, 10)
part = plate - Pos(20, 0, 5) * Cylinder(3, 10) + Pos(-20, 0, 14) * Box(8, 8, 8)
return part
```

## What you will reach for

- Solids: `Box(x, y, z)`, `Cylinder(radius, height)`, `Sphere(r)`, `Cone(r1, r2, h)`.
- `align=(Align.CENTER, Align.CENTER, Align.MIN)` puts the bottom on the current plane. The
  default centres on all three axes, which is rarely what a printed part wants in Z.
- Placing: `with Locations((x, y, z), ...)`, `GridLocations(x_spacing, y_spacing, x_count, y_count)`,
  `PolarLocations(radius, count)`; in algebra `Pos(x, y, z) * shape`, `Rot(0, 0, 90) * shape`.
- Removing: `mode=Mode.SUBTRACT` on any object; `Hole(radius, depth)` (no depth = through).
- Sketch and extrude: `BuildSketch(plane)` with `Rectangle`, `RectangleRounded(w, h, r)`, `Circle`,
  `SlotOverall(length, width)`, `Polygon(...)`, then `extrude(amount=..., taper=...)`.
- Planes: `Plane.XY`, `Plane.XZ`, `Plane.YZ`, `Plane.XY.offset(z)`.
- Edges: `fillet(part.edges().filter_by(Axis.Z), radius=2)`,
  `chamfer(part.edges().group_by(Axis.Z)[0], length=0.6)` (the lowest edges),
  `.sort_by(Axis.X)[-1]` (the one furthest along X).
- Measuring while you work: `shape.volume`, `shape.area`, `shape.bounding_box()`,
  `shape.is_valid`. The server measures the result anyway; these are for reasoning in the Note.

## Traps

- **Return the solid, not the builder**: `return part.part`.
- **Mirror with the method**: `shape.mirror(Plane.YZ)`. The free function `mirror(obj, about=...)`
  on a finished Part nests compounds, and mirroring twice has produced a Part reporting volume 0.
- **Taper direction**: `extrude(face, amount, dir=(0, 0, -1), taper=angle)` with a positive angle
  narrows in the direction of extrusion. Do not trust the sign from memory: after a tapered cut,
  check with `look` (and a check on a size) that the pocket widens the way it should.
- **Many identical cuts**: build one cutter, place it at all the `Locations`, subtract once. A
  boolean per cell on a large body is slow and can time out.
- **Fillets fail on tiny or tangent edges.** Select the edges precisely (`filter_by`, `group_by`)
  rather than filleting everything; if a fillet fails, try a chamfer or a smaller radius.
- **Sliver faces**: two cuts that almost touch leave walls of 0.01 mm. Give neighbouring features
  a real wall between them or let them overlap properly.
- **One solid**: a printed part should be a single connected solid. Pieces that only touch at an
  edge are separate solids; overlap them by a little so the union joins.
- **Where is zero?** Decide the part's frame once (what sits at z = 0, which way is front), write
  it in the docstring, and tag the faces that define it. Tags use these coordinates.
- **Shared numbers** go in a helper module (a `.py` without `build()`), imported by every Note
  that needs them, so two parts that must fit together cannot drift apart.
