# Tags and checks: reference

## Tag selectors

A tag is `"name": {"kind": ..., ..., "role": "what it is for"}` in the Note's `TAGS`. The name is
lowercase letters, digits, underscores. Coordinates are millimetres in the part's own frame.

| kind | fields | finds | measures |
|---|---|---|---|
| `planar_face` | `normal`: `"+X"` `"-X"` `"+Y"` `"-Y"` `"+Z"` `"-Z"` (the face's outward normal) or `[x, y, z]`; `at`: the coordinate of the plane along that axis (omit for the outermost such face) | every flat face in that plane with that normal | `at`, `area` (mm², summed), `count` |
| `square_hole` | `axis`: `"X"`/`"Y"`/`"Z"` the tunnel runs along; `at`: its centre as the other two coordinates in axis order (axis X: `[y, z]`, axis Y: `[x, z]`, axis Z: `[x, y]`); `size` | the rectangular void around that centre line | `width`, `height`, `at`, `length`, `through` |
| `round_hole` | `axis`, `at` (as above), `diameter` | the cylindrical hole on that axis | `diameter`, `at`, `length`, `through` |
| `boss` | `axis`, `at`, `diameter` | a cylindrical pin or post (convex) | `diameter`, `at`, `length` |
| `face_at` | `point`: `[x, y, z]` | the face nearest that point: a fallback for curved surfaces | `area`, `type` |
| `point` | `at`: `[x, y, z]` | the corner of the part at that place | `at` |
| `edge` | `a` and `b`: its two ends (a line or a curve); or `center` and `radius` (a circle, or the arcs that make one) | that edge | line: `length`, `a`, `b`; circle: `radius`, `diameter`, `length`, `center` |
| `object` | `name`: the label of a part of an assembly | that part | `volume_cm3`, `size`, `at` (its middle) |
| `group` | `of`: a list of selectors of the kinds above | all of them, under one name; found only when every member is | `count`, `area` (faces), `length` (edges), and `distance` when it is made of two points, two parallel flat faces, or a point and a flat face |
| `sketch` | `plane`: `{origin, normal, x}`; `curves`: what the user drew on it; `on`: the selector of the face it lies on, if any; `plane_name`: which plane it was drawn on | found as long as that face is (always, on a plane through the origin) | `curves`, `closed` |
| `plane` | `plane`: `{origin, normal, x}`; `on`: the selector of the face it was put on (or `base`: the ready plane it is a copy of); `offset`: mm off that | a plane the user made to draw on; found as long as that face is | `offset` |
| `sketch_curve` | `sketch`: the name of a sketch tag; `curve`: one of its curves, as drawn | that curve; no longer found when it is redrawn or removed | `length`, `closed` |

How they behave:

- `"normal": "-Z", "at": -16.72` is the downward-facing flat face at z = -16.72. `at` is always
  the coordinate, whatever the sign of the normal.
- A `square_hole` is found by standing on its centre line and looking outwards for four flat
  walls. It measures what is there: if you make the tunnel 17 mm, the tag still resolves and
  reports `width: 17.0`, and the user's check on the width is what fails.
- `through` is true when the centre line of the hole never passes through material from one
  side of the part to the other. A hole that ends against a wall is `through: false`.
- `length` is how far the hole is enclosed on all sides.
- If nothing is at `at`, a hole of the given `size`/`diameter` elsewhere is reported with
  `moved: [du, dv]` and the tag is *not resolved*. Either the feature moved by mistake, or you
  moved it on purpose and must update `at`.
- `selection()` returns a ready `selector` for every face the user selected. Use it as the tag and
  add a `role`.
- **A group is how a dimension gets a name.** Two parallel faces tagged together as
  `"width": {"kind": "group", "of": [face, face]}` measure `tag.width.distance`, and a check on that
  number holds the dimension whatever else changes. The user makes such a tag by selecting the two
  things in the canvas and naming them; you can write one too.
- A circular `edge` whose radius changed is still found (by its centre) and reports the new
  `radius`, so a check on the diameter is what fails, as with `square_hole`.

### Sketches

A `sketch` tag is a drawing the user made in the canvas: their way of showing you a shape and a
place instead of describing it. They draw on a plane: one of the three every part has through
its origin (`front`: the XZ plane seen from -Y, u = +X, v = +Z; `top`: the XY plane seen from
above, u = +X, v = +Y; `left`: the YZ plane seen from -X, u = -Y, v = +Z), a plane they put on a
face (a `plane` tag, possibly offset off the face), or a flat face directly. `plane_name` says
which, when it was a named plane; the `plane` inside the sketch is always complete on its own. `plane` is where it lies (`origin` a point on the
face, `normal` out of the face, `x` the direction of the drawing's u axis; v is `normal × x`).
`curves` are in millimetres on that plane, as `[u, v]`:

| curve | fields |
|---|---|
| `polyline` | `points`: `[[u, v], ...]`, `closed`: true when it comes back to its start. A point may be `[u, v, bulge]`: the stretch from it to the next point is then an arc, `bulge = tan(angle / 4)`, positive when the arc turns left (as in DXF). Fillets and trimmed circles are kept this way |
| `rect` | `at`: `[u, v]` of one corner, `size`: `[w, h]` |
| `circle` | `center`: `[u, v]`, `r` |
| `ellipse` | `center`: `[u, v]`, `rx`, `ry`, `rotation`: degrees, of the `rx` axis from +u |

The user can also name one curve of a sketch by itself (a `sketch_curve` tag: `sketch` is the
sketch's name, `curve` the curve as drawn), for when the instruction is about that line and not
the whole drawing: "cut along `slot_line`", "this circle is the bolt hole".

The `role` says what the user wants done with it ("cut 3 deep", "raise a boss 5 high"). To use
one in `build()`:

```python
def sketch_wire(c):
    """One curve of a sketch as build123d edges, on the sketch plane that is current (inside BuildLine)."""
    pts = c["points"]
    n = len(pts)
    for i in range(n if c.get("closed") else n - 1):
        p, q = pts[i], pts[(i + 1) % n]
        bulge = p[2] if len(p) > 2 else 0
        if abs(bulge) < 1e-9:
            Line((p[0], p[1]), (q[0], q[1]))
        else:   # the point half way round the arc: off the middle of the chord, to its right when the arc turns left
            dx, dy = q[0] - p[0], q[1] - p[1]
            mid = ((p[0] + q[0]) / 2 + bulge * dy / 2, (p[1] + q[1]) / 2 - bulge * dx / 2)
            ThreePointArc((p[0], p[1]), mid, (q[0], q[1]))


def sketch_face(tag, only=None):
    """The closed curves of a sketch tag as a build123d sketch on its plane. only: a list of curves to use
    instead of all of them (for example [TAGS["slot_line"]["curve"]])."""
    pl = Plane(origin=tag["plane"]["origin"], x_dir=tag["plane"]["x"], z_dir=tag["plane"]["normal"])
    with BuildSketch(pl) as sk:
        for c in only or tag["curves"]:
            if c["type"] == "rect":
                with Locations((c["at"][0] + c["size"][0] / 2, c["at"][1] + c["size"][1] / 2)):
                    Rectangle(*c["size"])
            elif c["type"] == "circle":
                with Locations(tuple(c["center"])):
                    Circle(c["r"])
            elif c["type"] == "ellipse":
                with Locations(Location((c["center"][0], c["center"][1], 0), (0, 0, c.get("rotation", 0)))):
                    Ellipse(c["rx"], c["ry"])
            elif c.get("closed"):
                with BuildLine():
                    sketch_wire(c)
                make_face()
    return sk.sketch

# in build(), after the body exists:
#   extrude(sketch_face(TAGS["pocket"]), amount=-3, mode=Mode.SUBTRACT)     a pocket, 3 deep
#   extrude(sketch_face(TAGS["pad"]), amount=5)                             a boss, 5 high
```

An open line has no inside, so `sketch_face` leaves it out: use it as a path or a place (where a
slot runs, where a rib stands) and build that feature from its points.

That is the quick way and it keeps the user's drawing as the source of the shape. When the shape
is really a rule ("a 20 x 8 slot centred on the bore"), write it as geometry from `PARAMS` instead
and say so: a drawing has no intent in it, a rule does. Either way keep the tag unless the user
asks to drop it: it is theirs.


## Checks

`add_check(project, note, what, min, max, equals, why, id)`. Give `min` and/or `max`, or
`equals`. `why` is the rule in the user's words; it is shown next to the check in the canvas.

`what` can be:

| name | meaning |
|---|---|
| `volume_cm3`, `area_cm2` | volume and surface area |
| `size_x`, `size_y`, `size_z` | bounding box size, mm |
| `min_x` … `max_z` | bounding box position |
| `com_x`, `com_y`, `com_z` | centre of mass |
| `solids` | number of separate solids (a printed part should be 1) |
| `fits_bed` | fits the project printer's bed lying flat, either way round; no min/max needed |
| `tag.<name>.<measure>` | any measurement of a tag: `tag.rod_bore.width`, `tag.rod_bore.through` (use `equals: true`), `tag.base.at`, `tag.bore.at[0]` |

Always present, without being asked for: every tag must resolve, and the solid must be valid.

Good checks come straight from the rules in the docstring:

| rule | check |
|---|---|
| "square tunnel, 16.4 mm" | `tag.rod_bore.width` min 16.2 max 16.4, and the same for `height` |
| "runs through the part" | `tag.rod_bore.through` equals true |
| "sits on the table" | `tag.base.at` min -0.01 max 0.01 |
| "printable on a 256 x 256 bed" | `fits_bed` |
| "one piece" | `solids` equals 1 |
| "no more than 60 g of PLA" (1.24 g/cm³) | `volume_cm3` max 48 |

Rules that cannot be measured yet (maximum solid thickness, overhang angles, minimum wall): say
so to the user rather than inventing a check that sounds like it covers them.

## The load check

`load_check(project, note)` rebuilds the *saved* source and compares it with the saved
fingerprint (volume, surface, bounding box, centre of mass) and every tag's measurements.

- `green`: identical.
- `yellow`: differs, but within the printer's tolerance. Usually a library update on the server.
  Tell the user; you may continue.
- `red`: something changed. `write_note` on that Note is refused until the user has looked in
  the canvas and pressed "I have looked". Do not try to get around it.
- `new`: never saved; nothing to compare.

## Versions and diff

`save` makes a numbered version of the whole project. `versions(project, note)` lists them.
`diff(project, note, a, b)` compares two (`"draft"` is the Note as built now): `removed` and
`added` give the largest distance the surface moved in mm and where; `tags` says what happened to
each tagged feature in words ("length: 45.0 -> 60.0"). Distances below the printer's tolerance
count as unchanged.
