# Monet

**Impressionist on the surface, exact underneath.**

Monet is a CAD tool for people who would rather say what they want than click
through a feature tree. You describe a part, point at faces and edges in a browser
view to say *which* ones you mean, and an AI agent writes and rebuilds the geometry.
It's aimed at 3D-printed jigs, fixtures and brackets for hobby workshops, schools and
small shops, where parts have to fit real plywood, real rods and real printers.

Status: **bare bones, running**. A Python server builds Notes, runs checks, shows the part
in a browser canvas where you click faces, keeps versions, diffs them and exports
3MF / STL / STEP. Your own agent connects to it over MCP or plain HTTPS. The first real
project, the MG400 work table, is ported from Fusion 360 and matches it to six digits.
What is not built yet is listed under [What is missing](#what-is-missing).

## Try it

```bash
uv sync                      # Python 3.11+, build123d and OCP pinned in uv.lock
uv run monet                 # http://localhost:8000, working files in ./storage
uv run pytest                # every Note builds, keeps its tags, passes its checks
```

People are let in by an admin, as in Adam Designer: a username, a card (a login link, also
as a QR) and a password they choose on their first visit. The first time the server starts
it prints a link for the built-in admin to choose a password; the admin then adds users on
`/users` and sends each their card link. `MONET_MAX_USERS` (default 20) is how many there
may be. Every user has one workspace, which starts with two projects: `starter` (the rod
foot below) and `mg400_rakis` (the sample).

**The thinking happens on your computer, with your own model.** Monet has no LLM inside. It
gives your agent structure (the Note format, tags, checks), a preview, an interface for
pointing, and export. An agent cannot log in as a person does, so it comes with an **agent
link** that has the user's agent key in it (`/w/<agent key>`): treat it as a password. Press
**Connect your agent** in the canvas for the exact lines, and for a new key when one got out:

| your harness | how it connects |
|---|---|
| Claude Desktop | Settings → Connectors → Add custom connector → `https://<host>/w/<agent key>/mcp`, then add the skill (`/skill.zip`) under Settings → Capabilities → Skills. For a server on your own machine use `npx mcp-remote http://localhost:8000/w/<agent key>/mcp` in `claude_desktop_config.json`. |
| Claude Code | `claude mcp add --transport http monet http://localhost:8000/w/<agent key>/mcp` |
| any LLM that can open web addresses | tell it: "Read `https://<host>/api` and work in my Monet workspace; my agent link is `https://<host>/w/<agent key>`". Every tool is a plain GET or POST. |
| a shell | `skill/monet/scripts/monet.py` (standard library only) |

**History is your own git.** Make a folder for the project on your computer and let the
agent keep the Notes there. It commits after every successful attempt (built, checks green,
saved). The server keeps numbered versions for comparing and exporting; the history is yours
and survives the server.

---

## Why

Parametric CAD (Fusion, SolidWorks, Onshape) stores *how* a part was built, as a
history of features, but not *why*. Change one dimension and something downstream
breaks, because the intent was never written down. Everyone is now adding a chat
assistant on top of that tree. Monet goes the other way:

- **Build towards Paint, not SolidWorks.** Students already prefer text to action.
  Most of a CAD feature set goes unused, not because it isn't needed but because
  asking is easier than operating it.
- **Throw the history away.** No feature tree, no sketch constraints. The geometry
  plus a written description of intent is the whole state. The agent re-derives
  geometry whenever needed.
- **Keep the intent where the agent can read it**: in tags on the geometry and in
  plain-language rules, each backed by a check.
- **Make every change visible**: a colour-mapped diff between versions, so you trust
  the change by looking at it, not by trusting a history tree.
- **Punk engineering.** Duct tape and chewing gum: build123d, git, a three.js
  viewer, an MCP server and an LLM agent, tied together. Write as little new code as
  possible.

## The pieces

### Note: the part file

One Python file per part is the whole format. The name is a nod to Ada Lovelace's
*Note G*, a note that tells a machine how to make something.

- The **docstring** is the intent: what the part is for, the rules it must keep.
- `PARAMS` holds the numbers people are likely to change.
- `TAGS` names the features that matter, by *description*, not by face number
  (face numbers change on every rebuild).
- `build()` returns the solid, written with [build123d](https://github.com/gumyr/build123d).
- Running the file writes the printable (3MF/STL) and preview (GLB) files next to it.

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

TAGS = {  # format not final
    "rod_bore": {"kind": "square_hole", "axis": "X", "size": 16.4, "through": True},
    "base":     {"kind": "planar_face", "normal": "-Z", "role": "sits on table"},
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

An **assembly** is just another Python file that imports Notes and places them.
**Git** is the history, and it lives with the user: the agent keeps the Notes in a local
folder and commits after every successful save. The server keeps each save as a numbered
version (the sources, and per Note a GLB and a fingerprint) so versions can be opened,
compared and exported.

### Canvas: the browser view

Three places to work, as tabs: **Sketch** (a drawing on a face), **Part** (one object) and
**Assembly** (objects put together). Opening an assembly goes to Assembly, opening one of its
parts goes to Part, starting a drawing goes to Sketch.

- Orbit, section plane and X-ray, to see inside parts (tunnels, pockets, cable channels).
- **Three ways to draw the part**: *Rendered* with its material, *Shaded* plainly (an assembly
  with a colour per part), *Hidden line*: only the lines, the hidden ones left out. Edges can be
  drawn over any of them.
- **Materials**: aluminium, POM and printed PLA, each in any colour, set per part. PLA is
  drawn as a perfect 0.4 mm nozzle would leave it: 0.2 mm layers on the walls, 0.4 mm lines on
  tops and bottoms. The rendered look is Adam Designer's world (its room light, sun, tone
  mapping and material values) on plain three.js.
- **Selecting**: points, lines, faces or whole objects, chosen in the toolbar. A click
  selects, Shift adds, Ctrl (or Cmd) takes away; a drag with Shift or Ctrl held, or any
  drag with Box on, selects with a box (left to right takes what it touches, right to
  left only what is wholly inside).
- **Measuring**, as Inspect does in Fusion: with Measure on, click one thing and then
  another, of any kind. One thing shows its own facts (length, diameter, area, where it
  is); two show the shortest distance between them, how it splits along x, y and z, and
  the angle, with the distance drawn in the view. The agent sees the same numbers.
- **Tagging**: name what is selected: a face, a line, a point, an object, or several of
  them together ("these two faces are the width"). The tag is written into the Note. Two
  faces or two points tagged together also carry their distance, which a check can hold.
  A tag picked in the panel shows through the part, like a hologram.
- **Planes**: every part has three ready, through its origin: Front, Top and Left. With one
  flat face selected in Part, New plane puts another on that face (or a typed distance off
  it); + beside a ready plane makes one a distance off that. A plane stays with the part as a
  tag, and its distance can be changed at any time: what is drawn on it moves with it.
- **Sketching**: choose a plane on the left (or a flat face) and draw on it: lines,
  rectangles, circles and ovals, in millimetres, lining up with the part's corners and a 1 mm
  grid. Offset copies a curve a set distance off it; Trim takes a stretch away up to where
  other curves cross it; Fillet rounds a corner. Undo goes back.
- **Sketch lines in Part**: what was drawn stays in sight on the part, and each line can be
  selected and named by itself ("cut along this one"), for the agent to act on. The drawing is saved as a tag with what
  you want done with it ("cut 3 deep"); your agent turns it into geometry.
- **Panels fold**: every panel on either side shuts on a click on its head and stays as
  it was left.
- **Projects**: the name at the top left opens all of them: open one, start one, **Download**
  one as an archive (a zip of its Notes, their checks and the saved versions), **Upload** such
  an archive as a project of its own, here or on another Monet, or delete one. Deleting is for
  good: the server keeps no copy, so download first what you may want back.
- **Diff**: model A coloured by its distance to B (what was removed) and B by
  its distance to A (what was added). The colour scale is clamped to the printer's
  tolerance, so only changes that matter for printing show up. Tagged features are
  matched between versions, so a moved hole reads "moved 2 mm along X", not as damage.
- **Compare tools**: crossfade A→B, a wipe plane (A on one side, B on the other),
  and a blink comparator (flick between A and B; the eye catches small jumps).
- **Series**: versions side by side, like Monet painting the same haystacks in
  different light.
- **Assembly**: a Note that puts other Notes together is shown as what it is: every part
  in its own colour or material, a parts list (hide one, show only one, open its Note), and
  an Explode slider that pulls the parts apart.

Candidate starting point: [yet-another-cad-viewer](https://github.com/yeicor-3d/yet-another-cad-viewer),
which already shows build123d models in the browser with face, edge and vertex
selection, or a plain three.js page loading the GLB files.

### Chat: the agent

The agent is the user's own: Claude Desktop, Claude Code, or any LLM that can call a web
address. It connects over **MCP** or plain HTTPS to tools like: write a Note (which builds
it and runs the checks), look (a rendered picture), selection (what the user is pointing
at), add a check, load check, diff two versions, save, export. The agent writes and edits
Notes; the user describes and points. There is no chat pane and no model in Monet itself.

### Feynman: the checks

Named after Feynman's first principle: you must not fool yourself, and you are
the easiest person to fool.

- Every tag can carry a check ("still a through hole, 16.2–16.4 mm").
- Rules in the docstring map to checks (fits the bed, minimum wall, maximum solid thickness).
- **The agent may not edit or loosen checks** to make them pass. Checks belong to
  the user.
- Every edit ends in a check run. Nothing is saved on red.

### Semmelweis: the load check

Named after the doctor who made colleagues wash their hands before touching the
next patient. Before the agent touches a part, the part is rebuilt from its Note and
compared with what was saved:

1. Fingerprint first (volume, surface area, bounding box, centre of mass): milliseconds.
2. Then every tag must still resolve with the same measurements.
3. Only on a mismatch, the full colour-map diff against the stored GLB.

Green: identical. Yellow: within print tolerance (usually a library update), so show
the map and ask. Red: something changed, so the agent may not edit until the user has
looked. This one check also catches library-update drift and verifies translations.

### Translation

When someone wants the part in Fusion 360 or Onshape, the **agent translates the
Note on demand**: Fusion Python API or Onshape FeatureScript, written fresh each time,
so new features of those tools come for free as models improve. Every translation is
verified against the stored render of the original Note (never against an earlier
translation), using the same diff. Parts come in from anywhere as STEP ("step 0": the
agent proposes tags, the user confirms, the agent writes the first Note). STL/meshes
are reference geometry only.

### Profiles: the real world

What actually decides whether a jig works, kept as data the agent must respect:
- printer: bed size, hole/shaft compensation from a printed calibration coupon,
  nozzle and layer limits
- material: shrinkage and warping tendency (big solid PLA blocks lift), creep under clamps
- stock: measured plywood thickness (12 mm sheet is often ~11.6 mm), rod diameters,
  fasteners

## Layout

```
monet/        note.py        read a Note without running it; rewrite its TAGS
              runner.py      the one place a Note is executed: its own process, a time limit;
                             writes the preview GLB and what the parts of an assembly are
              warm.py        what a build needs, loaded once: builds are forked from a process that
                             has the CAD kernel in it already, instead of loading it every time
              tags.py        find tagged features on a build (planar faces, square and round holes)
              feynman.py     the checks
              semmelweis.py  fingerprint + load check
              diff.py        distance colour maps between two versions
              render.py      PNG views without a GPU: the agent's eyes
              workspace.py   workspaces, projects, versions: the working files in a folder
              store.py       the accounts and the audit log, as files (from Adam Designer)
              auth.py        users, cards, passwords, the cookie, agent keys (from Adam Designer)
              buildd.py      the runner as a service: where Notes are built when online
              agent.py       the agent's tools, served over MCP and over plain HTTP
              app.py         the web app (Starlette): logins, canvas API, agent door, /api for LLMs
canvas/       the browser view (three.js), no build step:
              canvas.js      the page: the three areas, selection, panels, compare
              measure.js     shortest distances and angles (plain arrays; tested in node)
              look.js        the styles and materials, printed PLA
              sketch.js      drawing on a plane
              sketch2d.js    what the sketch tools do to curves: offset, trim, fillet (tested in node)
profiles/     printer and material profiles
notes/        templates a new workspace starts with: starter, mg400_rakis
skill/monet/  the skill for Claude: how to work in Monet (also served as /skill.zip and by guide())
deploy/       Dockerfile's companions: compose, Caddy, droplet setup (docs/SETUP-ONLINE.md)
reference/    material from the Fusion prototype (see below)
tests/        pytest: the core, every Note, the Fusion acceptance numbers, both agent doors
```

## Running it for other people

**Monet runs the Notes people send it, and a Note is Python.** Whoever may send one may run
code on the server. Three things keep that in hand:

- **Accounts.** Only people an admin let in have a workspace, and only their agent links
  work. `/users` shows who there is, when each was last seen, when their agent was last
  there, and what agents changed lately.
- **The person and their agent are told apart.** What comes in with the agent key can write
  Notes and add checks. Changing or removing a check, acknowledging a load check and
  everything about accounts need the login.
- **Notes are built somewhere that has nothing to steal.** Online (`deploy/compose.yml`) the
  web app never runs a Note: it asks a second container, which holds the working files and
  nothing else: no accounts, no session secret, no route to the internet. Both containers
  run without root, on a read-only file system, under ceilings on memory, CPU, processes
  and build time.

What a hostile Note can still do: read or spoil the working files of other users of the same
instance (they share one folder), and keep its CPU busy. So let in people you would lend the
machine to, and back up `storage/` if the work matters. A sandbox per build is the step after.

## What is missing

- Tag kinds: flat faces, square and round holes, bosses, edges, points, objects, groups,
  planes, sketches and single sketch lines. No slots or patterns yet; a curved face is only found by a point near it.
- Checks that need more geometry than a fingerprint: minimum wall, maximum solid
  thickness, overhangs, interference between the parts of an assembly (in the sample the
  nest's mouse ears overlap their neighbours by about 55 mm³ each; nothing reports it yet).
- Canvas: Series (versions side by side), section caps, screen-space reflections (Adam
  Designer has them on WebGPU). A sketch's points cannot be dragged yet: remove a curve
  and draw it again. Dimensions and constraints in a sketch. Offsetting an outline that has
  arcs turns them into short lines. Measuring whole objects against each
  other is approximate.
- Translation to Fusion / Onshape, and STEP import ("step 0").
- Profiles are data only: hole and shaft compensation is not applied to geometry yet.
- The ten-edit experiment below has not been run.

## First milestone: the MG400 work table

`reference/mg400_rakis/` holds a real project built this way, the hard way: a
3D-printed work table for a Dobot MG400 robot arm (self-centering robot nest, sliced
plate on 16 mm pipes, open-bottom Gridfinity grid, L brackets clamping to the table).
It was designed by an agent writing **Fusion 360 API scripts** with built-in checks
and a JSON report.

1. ~~Port `build_rakis_F.py` to Notes in build123d, part by part (start with the nest).~~
   Done: `notes/mg400_rakis/` (nest halves, four grid tiles, L bracket, the assembly).
2. ~~Match the numbers in `F_report.json` (sizes, volumes, heights) as the acceptance test.~~
   Done: sizes exact; volume and surface area agree with the Fusion bodies to six digits
   (`tests/test_notes.py`, numbers in `reference/mg400_rakis/`).
3. ~~Minimal canvas: load the GLBs, click to tag, write tags back into the Note.~~ Done.
4. Experiment: ten real edits through the agent. Count how many tags survive
   without help and how many checks catch real breakage. Those two numbers decide
   whether this is a product.

## Prior art

- [Adam / CADAM](https://www.developersdigest.tech/blog/adam-ai-cad-yc-w25-open-source-text-to-cad): text to OpenSCAD with sliders, "AI TinkerCAD" (GPLv3)
- [Zoo Text-to-CAD](https://zoo.dev), CADAgent (agent inside the Fusion timeline), Autodesk's Fusion MCP server
- [mcp-build123d](https://github.com/Casys-AI/mcp-build123d), [agentcad](https://github.com/jdilla1277/agentcad): agents driving build123d
- [yet-another-cad-viewer](https://github.com/yeicor-3d/yet-another-cad-viewer): browser viewer for build123d
- CloudCompare / GOM Inspect: the deviation colour map, borrowed from metrology

What none of them focus on: tags that survive rebuilds, checks the agent can't
loosen, and a visual diff as the thing you trust instead of a history tree.

## Names

*Monet. Named after Claude, painted by Claude.*

Monet (the canvas and the series of versions), Note (Lovelace's Note G),
Feynman (don't fool yourself), Semmelweis (clean hands before the next patient).

## License

[AGPL-3.0-or-later](LICENSE). Use it freely: run it, host it, change it. If you change it
and let others use your version, over a network included, publish your changes under the
same licence. Every instance links to its source from the start page and `/api/version`.
