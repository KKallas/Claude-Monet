# Monet

**Impressionist on the surface, exact underneath.**

Monet is a CAD tool for people who would rather say what they want than click
through a feature tree. You describe a part, point at faces and edges in a browser
view to say *which* ones you mean, and an AI agent writes and rebuilds the geometry.
It's aimed at 3D-printed jigs, fixtures and brackets for hobby workshops, schools and
small shops, where parts have to fit real plywood, real rods and real printers.

Status: **bare bones, running**. Your own agent writes Notes and builds them on your computer;
a Python server takes what it built, runs the checks, shows the part in a browser canvas where
you click faces, keeps versions, diffs them and serves 3MF / STL / STEP. The server never runs a
Note. Your agent connects to it with the skill's script (a shell with uv) and over MCP. The first real
project, the MG400 work table, is ported from Fusion 360 and matches it to six digits.
What is not built yet is listed under [What is missing](#what-is-missing).

## Try it

```bash
uv sync                      # Python 3.11+, build123d and OCP pinned in uv.lock
uv run monet                 # http://localhost:8000, working files in ./storage
uv run python -m monet.prebuild   # Monet's own templates, built once, so new projects open built
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
**Connect your agent** in the canvas for the exact lines, and for a new key when one got out.

The link opens nothing until you switch **remote control** on, there (as in Adam Designer). It
ends by itself after 15 minutes in which neither you nor your agent did anything, and when you
log out; the header counts it down. The same link works again when you switch it on again, and an
MCP connector stays connected while it is off. While it is on, your agent also reaches the canvas
you have open: what it shows (`screen`), a picture of your view (`view`) and taking it to a part
or an area (`goto`). It runs no code in your page: every change goes through its tools, on the
server, under the same rules. What it changes is listed under Connect your agent and kept in the
server's log.

| your harness | how it connects |
|---|---|
| one download | **your skill**, from Connect your agent: the skill with your agent link in it (`link.txt`, which its script reads). Claude Code: unzip it into `~/.claude/skills/` and that is all. Claude Desktop: upload it under Settings → Capabilities → Skills; it reaches Monet where Claude's code sandbox may reach your host, else add the connector too. It holds your key: after a new key, download it again. |
| Claude Desktop | Settings → Connectors → Add custom connector → `https://<host>/w/<agent key>/mcp`, then add the skill under Settings → Capabilities → Skills. For a server on your own machine use `npx mcp-remote http://localhost:8000/w/<agent key>/mcp` in `claude_desktop_config.json`. |
| Claude Code | `claude mcp add --transport http monet http://localhost:8000/w/<agent key>/mcp` |
| a shell | `skill/monet/scripts/monet.py` (standard library only; building runs Monet's builder with [uv](https://docs.astral.sh/uv/)) |
| the canvas's own terminal | `monet.py link <agent link>` once, then `monet.py local <project>` in the project's folder: see below |

**Monet local: the canvas shows the folder, and has a terminal in it.** `monet.py local <project>`
stays running on your computer. A Note changed in the folder is sent, built there and shown; what
you change in the canvas is written into the folder; a file changed on both sides is left alone and
said (nothing is merged yet). It prints a link to open once: after that the **Terminal** button in
the canvas opens Claude Code, Codex or a shell in that folder. The page talks straight to
`127.0.0.1` on your own computer: the server is not in between and never sees the terminal. Monet
local answers only a page of the Monet it is linked to, with the token of your computer, and starts
only what is on its own short list. This is the first step of [docs/REWIRE.md](docs/REWIRE.md).

**Your agent builds; the server never runs a Note.** Building needs a shell on your computer with
uv: `monet.py push <project> <note>.py` sends a Note, builds it there with the same Monet and CAD
kernel as the server (the skill pins them) and uploads what the build left; `monet.py build
<project>` builds whatever is not built for its source. The server takes a build only if it is of
the files it has, with its own Monet and kernel. Tags, joints and the ground you make in the canvas
change no geometry: the server works them out from the last build. A Note your agent has not built
since it changed is shown as its last build, marked *waiting for your agent*. MCP alone can look,
point, add checks and save, not build.

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

An **assembly** is just another Python file that imports Notes and places them. It can say how
its parts still move from there, with `JOINTS` and `GROUND`: plain literals beside `TAGS`, read
and rewritten without running the Note.

**One design, one project.** Its main assembly is the Note named as the project is (`orb` in the
project `orb`). The project opens on it, and the canvas lists every Note as a tree under it: what
each imports and what its `PLACED` puts in it (read with `ast`, nothing run), the helper modules
apart. What nothing uses sits below as *Other designs*; until there is a Note of the project's
name, the server guesses the design with the most under it (`workspace.main_of`) and the canvas
says it is a guess. The person makes a project of another design with one click (⇱,
`Workspace.project_of`): it takes that Note, everything it uses, their checks, current builds and
animations, and leaves the old project as it was.

```python
GROUND = "rails"
JOINTS = {
    "rails": {"kind": "rigid", "parts": ["L_back_pos", "L_front_pos", "pipe_long_pos"]},   # these move as one
    "slide": {"kind": "slider", "moves": "top", "on": "rails", "axis": "pipe_tunnel", "range": [-79, 0]},
    "lid": {"kind": "revolute", "moves": "lid", "on": "box", "axis": "hinge_pin", "range": [0, 110]},
    "rod": {"kind": "revolute", "moves": "rod", "on": "crank", "axis": "rod_pin", "follows": {"lid": -1}},
}
```

Every joint is an *as-built* joint: 0 is where `build()` put the parts, so nothing is snapped
together and nothing is solved. A joint turns or slides about an axis taken from a tag (so it
follows the geometry when it changes) or given as origin and direction. A part no joint names is
free; `GROUND` never moves. The joints form a tree from the ground; a loop (a parallelogram, a
four-bar, gears) is written as `follows`: the follower's value is a sum of other joints' values
times factors. The MG400 robot arm is built so, two parallelograms and all, and moves to the
hundredth of a millimetre as Dobot's own robot description says (`reference/mg400/`, tested at six
poses). Twice: `mg400.py` is its nine links as Dobot drew them, `mg400_blocks.py` the same arm
drawn as plates, pins and boxes (light, and every face a true plane or cylinder to tag).

A **tip** is a point on a part that can be led somewhere, as a robot's nose: `TIPS = {"nose": {"on":
"tool", "at": [x, y, z]}}` (where it is as built). Put the tip at a point and the joints moved by hand
are solved for it, within their ranges (inverse kinematics: damped least squares on the joints' own
frames, the same in the server and the canvas, a few milliseconds). Out of reach, the tip comes as near
as it can and says how far that is. Both MG400s have a nose; led to where Dobot's URDF puts it at a
pose, the solver finds that pose's J1…J3 to a hundredth of a degree.

A part can come **from a mesh**: `mg400_mesh.py` holds Dobot's link meshes (simplified to 0.4 mm
with manifold3d, which keeps them closed), and the kernel makes a solid of each, a flat face per
triangle (`BRepBuilderAPI_MakeShapeOnMesh`). The runner leaves the seams between such triangles out
of the drawing and out of what can be pointed at, so a mesh part is drawn like a part.

Every build of an assembly also measures where its parts **overlap as built**, and moves each
joint alone through its range and past it: where it first hits something each way, and the worst
new overlap inside its range. Two parts that overlap as built and turn against each other about a line
through that overlap are a pin in its hole, whether a joint joins them or the pin closes a loop: their
turning is not a clash. Those are numbers a check can hold (`joint.slide.stop_min`,
`joint.lid.clash_mm3`, `interference_mm3`). Meshes in, volumes out: the parts' own preview
meshes, intersected with [manifold3d](https://github.com/elalish/manifold), about 3 ms a pose.
**Git** is the history, and it lives with the user: the agent keeps the Notes in a local
folder and commits after every successful save. The server keeps each save as a numbered
version (the sources, and per Note a GLB and a fingerprint) so versions can be opened,
compared and exported.

### Canvas: the browser view

Four places to work, as tabs: **Sketch** (a drawing on a face), **Part** (one object),
**Assembly** (objects put together) and **Motion** (how they move). Opening an assembly goes to
Assembly, opening one of its parts goes to Part, starting a drawing goes to Sketch.

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
- **Motion**: the joints of an assembly, as in Fusion. Drag a part and it moves only as its
  joint lets it, round its axis or along it, up to the ends of its range; a free part goes
  anywhere. Every joint moved by hand has a slider and ▶, which moves it back and forth through
  its range; the joints that follow it go with it. What a pose runs into turns red, and the panel
  says which parts and by how much; what overlaps as built is listed apart, with each joint's
  stops. Make a joint by selecting the moving part and the hole, boss or face to turn about or
  slide along (it is tagged for the joint), group parts that move as one, lock a joint, choose
  the ground: all of it written into the Note's `JOINTS`. A tip (a robot's nose) is a pink ring: drag it and the
  joints follow it, or type where it should go. Along the bottom, a timeline: keys of the joints over frames,
  and an action line above them (a pause, or a goto to another frame) that playing meets and a video follows.

Candidate starting point: [yet-another-cad-viewer](https://github.com/yeicor-3d/yet-another-cad-viewer),
which already shows build123d models in the browser with face, edge and vertex
selection, or a plain three.js page loading the GLB files.

### Chat: the agent

The agent is the user's own: Claude Code, Claude Desktop or another harness with a shell. It
connects over **MCP** or HTTPS (POST) to tools like: write a Note (which it then builds on the
user's computer and uploads; the server runs the checks), look (a rendered picture), selection (what the user is pointing
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
next patient. Before the agent touches a part, the part is rebuilt from its saved Note, with the
server's Monet and kernel as they are now, and compared with what was saved. The agent builds it
(the load check is *waiting* until it has); the server compares:

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
- material: density (so mass), where it softens (`max_temp_c`), whether it is printed at all
  (aluminium tube and steel rod are not), shrinkage and warping tendency (big solid PLA blocks
  lift), creep under clamps. A project has one; a Note can say its own (`MATERIAL`), an assembly
  per part (`MATERIALS`), and what is bought weighs what `MASS` says
- stock: measured plywood thickness (12 mm sheet is often ~11.6 mm), rod diameters,
  fasteners

### Showing it: lights, beams, a timeline and the finish

*Status: the action line (0.9.x) and lights and beams in the canvas (0.10.0) are built; the lights' facts and checks (lux,
blocked beams), lights in the server's videos, and the finish are the plan (Kaspar, 2026-11-11).*

Monet is a design tool and a sales tool in one. Until now a lamp or a projector piece was drawn in
Blender or made up by an image model (nano banana): a shell, with no inside and no mechanics. The
client said yes to that, and only then did anyone find out whether it could be built, and what the
look had to give up so it could be. With an agent designing real parts, the design is buildable from
the start: electronics, LEDs, lights and projectors inside, joints that move, pieces that fit the
bed. The client still needs a fancy photographic picture. So the pictures are made **from the
buildable design**: it works in the canvas, and then a picture model makes it look like a photograph.
What looks good in front of the client can be made.

**The action line** (built). Above the joint lines of the timeline in Motion there is a line of
actions, data and not code (the agent runs no code in the canvas): at a frame, a `pause` (▶ goes on
from there) or a `goto` to another frame (back: a loop). Playing meets them; a scrub never does. A
video follows the same path (`played` in `workspace.py`, the same steps as `advance` in
`canvas/timeline.js`, held together by `tests/advance.json`): it ends at a pause, held `hold` seconds,
and shows a loop once. New verbs come only when needed (`pose <name>`, `light`, `camera`, `wait`).

**Lights and beams** (built in 0.10.0: `monet/lights.py` checks them, `canvas/lights.js` draws them). A Note's `LIGHTS`, a plain literal
and no shape (`note.FACTS`):

```python
LIGHTS = {
  "led":   {"kind": "spot", "on": "head", "at": [0, 0, -12], "aim": [0, 0, -1],
            "angle": 60, "soft": 0.3, "lumens": 800, "color": "#ffd8a8", "glow": "diffuser"},
  "proj":  {"kind": "projector", "on": "head", "at": [40, 0, -5], "aim": [0, 0.3, -1], "up": [0, 1, 0],
            "throw": 1.2, "aspect": "16:9", "lumens": 300},
  "laser": {"kind": "laser", "on": "turret", "at": [0, 0, 20], "aim": [1, 0, 0], "fan": 40, "mw": 50, "color": "#2a4bff"},
}
```

- Kinds: `point`, `spot` (a cone: full beam angle, soft edge), `projector` (a rectangular beam from
  its throw ratio and aspect, a test picture on what it lands on, later an image of the user's own),
  `laser` (a line, or with `fan` a sheet). Strength in lumens, a laser's in mW. A light rides its
  part (`on`) through every joint, as a keep-out does (`derive.riding`); `glow` lights a part with it.
- The look is Blade Runner's searchlights and Alien's lasers in smoke: a beam is seen in the air (an
  additive shader, bright at the source, fading along and to its edges, slow 3D noise for smoke,
  specks of dust), with hard edges against a dark room; a laser a hot core in a halo, a fan a sheet
  that sweeps as its joint moves; bloom, and a short anamorphic streak where you look into a source.
  The beam is cut where it meets a part (a grid of rays from the source, again as the pose changes),
  so a part in the way leaves a dark shaft in the smoke. Light lands with shadows (three.js
  `SpotLight`, a projector's picture by `SpotLight.map`).
- The timeline gets a line for each light (intensity 0–100 %), and for the **room** (how much it is
  lit) and the **haze** (how much smoke is in the air): timing an animation by its light. Motion has
  a slider for each. **Render video** draws every frame of the timeline in the browser, at the
  canvas's quality, lights and all, as an H.264 MP4 (WebCodecs and mp4-muxer: `canvas/video.js`):
  a few frames between each picture of the view, from the camera as it stood when it began, so the
  person works on meanwhile. Playing keeps time on a slow computer by skipping frames; when it runs
  under 25 fps the video is rendered by itself, and when it is done it plays over the view, smooth.
  The frames are the server's (`played()`, in both, held by `tests/advance.json`). The server's
  GIF/MP4 stays the agent's quick look, with a plainer beam: a job of its own (`monet/jobs.py`,
  issue #9), one at a time in a process apart, answered with its progress until the file is there.
- **Pixels** (0.11.0, issue #10): `kind: "pixels"` makes every solid of the parts it names a pixel,
  lit from the LEDs the Note's `leds()` gives (the build finds each LED's pixel: `runner.pixels_of`,
  and reports the count, density, densest over sparsest and the current at full white, which checks
  hold). `canvas/pixels.js` shades each pixel from its LEDs in the parts' own materials, lights the
  white between them from a grid of the nearest pixels, and plays the animation's `patterns` (chase,
  wave, scan, rainbow, sparkle) on them: the look of the lamp agent's offline renderer, live.
- What the lights do, worked out on the server from the build, as torque is: how much of each beam
  the parts cut off at each pose, lux on a surface the Note names (centre, least, evenness), a
  projector's picture size at its throw and whether all of it lands; each one checkable
  (`lux.table.min >= 300`, `beam.led.blocked <= 0.05`). A beam can be a keep-out (`"keepout": true`):
  for a light or a projector, the beam *is* the room to keep clear.

**The finish** (plan). From Adam Designer's Finish and Generate rooms (its `docs/06-finish.md`,
`07-model-pass.md`, `12-generate.md`): a **shot** is a camera, a frame of the timeline (so a pose and
the lights), and optionally a photograph of where it will stand (Adam Designer's Place). The canvas
renders it as layers, each named in the text sent with them, so the model knows what is what:
1. the rendered picture, lights and beams in it: *what it looks like and where everything is*;
2. the parts alone on black, each in its own flat colour: *what must stay*: outlines, places, how many;
3. the lights and beams alone: *where the light comes from*;
4. depth and normals, for the models that take them; the background photo, untouched.

The instruction says the result is picture 1 made real: the same framing, every part where it is,
its outline and count kept, materials as the project says (`MATERIALS`, the canvas's Look), light only
from the lights shown. The person adds what this picture needs ("evening, a wooden sideboard, the
beam through a little haze"). As in Adam Designer's Generate it is a chat with the model, a turn at a
time; what comes back is laid on the shot as a layer, and the next turn starts from the picture.
**Videos** the same way, by a video model: a start and an end frame from the timeline's poses, or the
canvas's recording as the motion to follow.

- **The models are data**, as printers are: `profiles/models/<name>.json`: kind (image or video),
  what pictures it takes, sizes, cost per call. nano banana (Gemini image) first, others beside it to
  choose from; a fake model for the tests; each call's cost shown before it goes, and a budget.
- **A finish stays honest.** It carries the version of the Notes it was made from and is marked
  stale when the design changes. It is checked against layer 2: where a part's outline in the
  picture strays from the built part's (overlap of the two masks), or a part is missing or added, it
  says so, so a picture never shows a lamp that cannot be made. It is labelled an illustration of
  version n.
- **Decision open: who calls the models.** CLAUDE.md says there is no model in the server: the agent
  is the person's own. A picture model is a tool, not an agent, and Adam Designer calls Gemini from
  its server (a key, a cost, a budget). Either the server calls them, so the person can finish a
  picture in the canvas without an agent, with the key kept beside the accounts and not in `storage/`;
  or the agent calls them on the person's computer with the person's keys and uploads the result,
  as it uploads builds. To be decided before this is built.

## Layout

```
monet/        note.py        read a Note without running it; rewrite its TAGS and JOINTS; what of it
                             is its shape (geometry_key) and what the canvas changes (literals_key)
              runner.py      the one place a Note is executed, on the agent's computer: its own
                             process; writes the preview GLB and what the parts of an assembly are
              build.py       the agent's builder (in the skill, pinned): a Note built, zipped to upload
              prebuild.py    Monet's own templates, built when the image is made
              derive.py      a build's tags and joints found from what it left (no kernel): by the
                             runner, and by the server after a canvas edit
              rays.py        does a line meet the part: asked of the preview mesh, by both
              tags.py        find tagged features on a build (planar faces, square and round holes)
              materials.py   what each part is made of and weighs (MATERIAL, MATERIALS, MASS), by the server
              bom.py         the bill of materials of an assembly (BOM): print counts, cut list, what to buy
              lights.py      the lights of a Note (LIGHTS) checked against its parts, for the canvas to draw
              split.py       a part bigger than the bed cut into pieces with dowel holes (used in a Note's pieces())
              joints.py      an assembly's joints found on a build: where each part is at a pose,
                             what moving a joint hits (manifold3d), what overlaps as built
              feynman.py     the checks
              semmelweis.py  fingerprint + load check
              diff.py        distance colour maps between two versions
              render.py      PNG views without a GPU: the agent's eyes
              workspace.py   workspaces, projects, versions: the working files in a folder
              store.py       the accounts and the audit log, as files (from Adam Designer)
              auth.py        users, cards, passwords, the cookie, agent keys (from Adam Designer)
              agent.py       the agent's tools, served over MCP and over HTTPS (POST); the upload
              app.py         the web app (Starlette): logins, canvas API, agent door, /api for LLMs
canvas/       the browser view (three.js), no build step:
              canvas.js      the page: the four areas, selection, panels, compare, Motion
              lights.js      the Note's lights: where they land, beams in smoke, glow, bloom, the stage
              timeline.js    Motion's timeline: keys of joints and lights, the action line, playing
              tree.js        the Notes as a tree: the main assembly, the other designs, the modules
              terminal.js    the terminal: this page to Monet local on the person's own computer
              motion.js      where the parts are at a pose of the joints (tested in node, and
                             against joints.py)
              measure.js     shortest distances and angles (plain arrays; tested in node)
              look.js        the styles and materials, printed PLA
              sketch.js      drawing on a plane
              sketch2d.js    what the sketch tools do to curves: offset, trim, fillet (tested in node)
profiles/     printer and material profiles
notes/        templates a new workspace starts with: starter, mg400_rakis
skill/monet/  the skill for Claude: how to work in Monet (also served as /skill.zip and by guide());
              scripts/monet.py the tools from a shell, scripts/local.py Monet local (the folder watched,
              the canvas's terminal)
deploy/       Dockerfile's companions: compose, Caddy, droplet setup (docs/SETUP-ONLINE.md)
reference/    material from the Fusion prototype (see below); mg400/: Dobot's robot description
              (URDF, MIT licence) and the sizes of its links, what the MG400 Note is held to
tests/        pytest: the core, every Note, the Fusion acceptance numbers, both agent doors, uploads
```

## Running it for other people

**Monet never runs the Notes people send it.** A Note is Python, so it is built where its author
is: by their own agent, on their own computer (`monet/build.py`, carried in the skill). The server
reads Notes as text (`ast`), takes what a build left only if it is a build of the files it has with
its own Monet and kernel, and works tags and joints out of it without a CAD kernel. Three things
keep the rest in hand:

- **Accounts.** Only people an admin let in have a workspace, and only their agent links
  work. `/users` shows who there is, when each was last seen, when their agent was last
  there, and what agents changed lately.
- **The person and their agent are told apart.** What comes in with the agent key can write
  Notes, upload builds and add checks. Changing or removing a check, acknowledging a load check
  and everything about accounts need the login.
- **An upload is data, taken by name.** A build arrives as a zip of known file names (result.json,
  faces.json, model.glb, exports), read into memory, checked for what the server reads in it, and
  written under those names: nothing in the zip says where a file goes.

What a key holder can still do: upload measurements of their own workspace that are not what the
Note would build. A build is a claim; the canvas says who built it, and a load check compares
the saved version with a build of it again. Back up `storage/` if the work matters.

## What is missing

- Tag kinds: flat faces, square and round holes, bosses, edges, points, objects, groups,
  planes, sketches and single sketch lines. No slots or patterns yet; a curved face is only found by a point near it.
- Checks that need more geometry than a fingerprint: minimum wall, maximum solid
  thickness, overhangs. (Overlap between the parts of an assembly is measured now: in the
  sample the nest's snap-off mouse ears overlap the first grid tiles by 59.7 mm³ and the back
  L brackets by 53.7 mm³ each.)
- Motion: joints are rigid, revolute and slider; no cylindrical, pin-slot, planar or ball yet.
  A loop is written as `follows` (linear), never solved: a toggle clamp or a four-bar whose
  links do not stay parallel needs a solver. A sweep moves one joint at a time, the others as
  built; several joints together are checked only at the named poses (`POSES`), not between them.
  No clearance (smallest distance) or reach checks, no traced path of a point. Torque is gravity
  alone: no friction, springs or acceleration, and no speed from a servo's deg/s yet. Free parts dragged in the canvas are not saved.
  A joint's axis drawn in the view is the only gizmo: no arrows to drag.
- Canvas: Series (versions side by side), section caps, screen-space reflections (Adam
  Designer has them on WebGPU). A sketch's points cannot be dragged yet: remove a curve
  and draw it again. Dimensions and constraints in a sketch. Offsetting an outline that has
  arcs turns them into short lines. Measuring whole objects against each
  other is approximate.
- Translation to Fusion / Onshape, and STEP import ("step 0"). A mesh comes in only as data in a
  helper module, made by hand (as `mg400_mesh.py` was); its triangles cannot be tagged as holes or
  bosses, so a joint on it takes its axis as origin and direction. Such a part is heavy for the canvas
  (the MG400's 21,700 faces are a 5.7 MB `faces.json`).
- Profiles are data only: hole and shaft compensation is not applied to geometry yet, and a
  material's `max_temp_c` is not checked against anything (there is no thermal check).
- Splitting a big part makes dowel joints only: no laps, dovetails or bolt tabs, and no cradle for a
  piece that will not stand on its cut face.
- Lights: no facts or checks of what they do yet (lux on a surface, how much of a beam is cut off, a
  projector's picture landing whole), no lights in the server's GIF/MP4, the stage (a floor, a wall
  before the projector) is the canvas's own guess, a projector throws a test picture only. The finish
  (photographic pictures and videos by picture and video models, checked against the build) is planned,
  in "Showing it" above. The action line has two verbs, pause and goto.
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
