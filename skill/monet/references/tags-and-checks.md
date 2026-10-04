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
- `selection()` returns a ready `selector` for whatever the user clicked. Use it as the tag and
  add a `role`.

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
