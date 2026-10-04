---
name: monet
description: Design 3D-printable parts in Monet, a CAD workspace where each part is a small build123d Python file (a "Note") that a Monet server builds, checks and shows in a browser canvas. Use this whenever the user mentions Monet, a Note, their Monet workspace, canvas or workspace link, or asks to design, change, check, compare or export a printed part, jig, fixture, bracket or holder while Monet tools (status, write_note, look, save and the like) or a Monet workspace link are available. Also use it when the user says "this face" or "that hole" about a part shown in Monet.
---

# Monet

Monet is CAD for people who would rather say what they want than click through a feature tree.
The work is split three ways:

- **The user** describes the part and points at faces in a browser canvas. They own the checks.
- **You** write the part as a *Note*: one Python file with the intent, the parameters, the named
  features and a `build()` function. You think and write on the user's computer.
- **The Monet server** runs the Note, measures the result, runs the user's checks, renders
  pictures, keeps the saved versions and exports files for printing.

There is no feature tree and no history of operations. The Note plus its written intent is the
whole state, so when something changes you re-derive the geometry from the intent rather than
patching the previous shape.

## Getting connected

Your tools, in whichever form the harness gives them:

- **MCP tools** from a connector usually called Monet: `guide`, `status`, `new_project`,
  `read_note`, `write_note`, `check`, `look`, `selection`, `add_check`, `load_check`, `save`,
  `versions`, `diff`, `export`.
- **A shell but no MCP tools**: `scripts/monet.py` in this skill does the same over HTTP. Set
  `MONET_URL` to the user's workspace link (it looks like `https://host/w/AbC123…`), then
  `python scripts/monet.py status`.
- **Only the ability to fetch web addresses** (a chat interface with internet access): every tool
  is also a plain HTTPS address, `GET <workspace link>/agent/<tool>?arg=value`. Read
  `<the Monet site>/api` first: it explains how to register a workspace id and lists every tool.
- **None of these**: ask the user to open their Monet site, press Start, and use "Connect your
  agent" there. It shows the exact addresses for them to give you.

Start every session with `status()`. It lists the projects and gives the canvas link: pass that
link to the user so they can watch the part change and point at it.

## The user's own folder, with git

History lives with the user, not on the server. If you can write files and run commands on the
user's computer (Claude Code, Cowork, a harness with file and shell tools), set this up before
the first edit and tell the user where it is:

```bash
mkdir -p ~/monet/<project> && cd ~/monet/<project>
git init                       # only if it is not a repository yet
```

Keep every Note there as `<note>.py`, exactly as you send it to the server. For a project that
already exists on the server, fetch each Note first (`read_note`, or `monet.py pull <project>`)
and commit that as the starting point.

**Commit after every successful attempt**, meaning after `save` answered `saved: true`:

```bash
git add -A && git commit -m "v<version>: <the message you gave save>"
```

Do not commit red attempts; the point of the history is that every commit is a part that built
and passed its checks. If you have a shell, `monet.py pull <project>` also brings the saved
preview (`<note>.glb`) and fingerprint (`<note>.fingerprint.json`) next to each Note so they are
committed with it.

If you cannot write files or run git (plain chat with only the connector), say so once: the
server still keeps numbered versions, but the user's own history needs a harness with file
access. Then carry on.

## The loop

Follow this for every change. Each step exists because skipping it has burned someone.

1. **Read before you write.** `read_note` gives the source as the server has it; the user may have
   added tags from the canvas since you last saw it. For a Note that has been saved before, run
   `load_check`: green means the saved part still rebuilds to exactly what was saved. Yellow
   (within print tolerance, usually a library update): tell the user and continue. **Red: stop.**
   Do not edit; ask the user to look at it in the canvas and acknowledge. Only they can.
2. **Find out what they mean.** When the user says "this face", "these edges", "here", "that
   hole", call `selection`. In the canvas they select points, lines (edges), faces or whole
   objects, one or many, and you get them as `items`: a face with its kind, place, size and a
   `selector` that would find it again as a tag; an edge with its type, length and ends; a point
   with its coordinates; an object (a part of an assembly) with its name. `measure` carries what
   the canvas worked out: the distance between two points or two parallel faces, total length,
   total area. Coordinates are the part's own, in millimetres.
3. **Edit the Note** in the local folder, then send the whole file with `write_note`. The answer
   is the report: does it build, does every tag still find its feature, does every check pass.
4. **Look at it.** Call `look` and study the picture; "it ran without errors" is not success. Use
   `views` such as `iso_under` or `bottom` when the change is underneath, and `tags=true` to see
   what each tag points at.
5. **Red? Fix the geometry.** Never the checks. If a check and the request truly conflict, stop
   and tell the user which check and why; changing it is their decision, in the canvas.
6. **Green: save, then commit.** `save(project, message)` builds every Note in the project and
   refuses if any is red. On success commit in the local folder as above.
7. **Report plainly**: what changed, the numbers that matter, the canvas link, and that they can
   click a version in the canvas to see the colour-map diff. `diff` gives you the same comparison
   in numbers.

## The Note

One Python file per part. Nothing else describes the part.

```python
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
```

- **The docstring is the intent**: what the part is for, then `Rules`, one per line, in words the
  user would use. Update it when the intent changes; it is what you and the next agent read first.
- **`PARAMS`**: the numbers people are likely to change. `build()` derives everything else.
- **`TAGS`**: the features that matter, named and described by *geometry*, never by face number
  (face numbers change on every rebuild). It must be a plain literal dict: the server reads and
  rewrites it without running the file. See `references/tags-and-checks.md`.
- **`build(p=PARAMS)`** returns one build123d solid. Millimetres, Z up.
- A Note's file name is its name: lowercase letters, digits, underscores.
- A file without `build()` is a helper module that Notes import (shared parameters, shared
  functions).
- Notes run on the server in their own process with a time limit. Use only `build123d`, `math`
  and the project's own files: a Note describes a part, it has no business reading files or
  reaching the network.

`references/build123d.md` has the modelling cheat sheet and the mistakes that cost time.

### Assemblies

An assembly is just another Note: it imports the Notes of its parts, puts them where they belong
and returns them as one compound with a name on each.

```python
"""
Stand: two feet and the rod between them.

Rules
- the rod sits in both bores
"""
from build123d import *
import rod_foot

PARAMS = dict(span=300.0)

TAGS = {}


def build(p=PARAMS):
    left = Pos(-p["span"] / 2, 0, 0) * rod_foot.build()
    right = Pos(p["span"] / 2, 0, 0) * rod_foot.build()
    rod = Pos(0, 0, 11.2) * Rot(0, 90, 0) * Box(16, 16, p["span"] + 45)
    left.label, right.label, rod.label = "foot_left", "foot_right", "rod"
    return Compound(children=[left, right, rod], label="stand")
```

- **Name every child** (`.label`): that name is what the user sees in the canvas's parts list and
  what you get back. Do not fuse the parts (`+`): fused, they are one solid and no assembly.
- The canvas shows an assembly with each part in its own colour, a parts list (hide, show only
  one) and an Explode slider. A project opens on its assembly.
- For you: the report of an assembly has `parts` (name, volume, size, where it is); `look`
  paints the parts in their own colours with a legend; every item of `selection` says which
  `part` it belongs to, and whole parts can be selected as objects.
- A part that only exists in the assembly (a bought rod, a screw) can be made right there.
  Anything printed should be a Note of its own, so it has its own checks and exports.
- Parts that must fit each other should take their numbers from one shared helper module, and
  be modelled in the frame they have in the assembly when that is simpler than placing them.
- Checks on an assembly: `solids` equals the number of parts, and its overall size. Whether
  parts collide is not measured yet: look, with `look` and the section view.

## Tags and checks

A **tag** says which feature is which: "the square tunnel along X at this place", "the flat face
that sits on the table". Every tag must still find its feature after every rebuild; one that does
not turns the Note red. When you move a feature on purpose, update the tag's `at` in the same
edit. When the user tags a face in the canvas it is written into `TAGS` for you: keep it.

A **check** is a measurement and the range it must stay in, for example
`tag.rod_bore.width` between 16.2 and 16.4. Checks belong to the user:

- You can **add** checks with `add_check`, and you should: when a Note has rules in its docstring
  that no check covers, propose a check for each and tell the user what you added.
- You cannot change or remove a check, and you must not work around one (for example by
  retagging a different face so the number comes out right). The user does that in the canvas.

## Printing is real

`status(project)` returns the project's printer and material profiles. Design for them:

- The part must fit the bed (`fits_bed`), in the orientation it prints.
- No supports: square tunnels with flat roofs bridge fine; round holes on their side do not.
  Prefer chamfers to fillets on edges that touch the bed.
- Big solid blocks of PLA warp and lift. Keep sections hollow or ribbed; respect the material's
  `max_solid_thickness`.
- Fits are designed, not hoped for: a 16 mm rod wants about 0.2 mm clearance per side. Put the
  clearance in `PARAMS` and a check on the result.

## When something goes wrong

- **Build error**: the report's `error` names the exception and the line in your Note. Fix and
  resend. Three failed attempts at the same thing means the approach is wrong, not the syntax:
  step back and rebuild the feature a simpler way.
- **A tag is "not found"**: read its `why`. Usually you moved or resized the feature; the report
  often says where the nearest match is.
- **`save` refuses**: it lists every red Note. A change in a shared module can break a Note you
  were not looking at; run `check` on those.
- **The tools answer "no such workspace"**: the workspace link is wrong or the workspace was
  removed. Ask the user for the link shown in their canvas.
