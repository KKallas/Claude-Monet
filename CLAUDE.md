# CLAUDE.md: working on Monet

Read README.md first. It is the design. This file is how to work on it.

## Principles

- **The Note is the part.** One Python file per part: docstring = intent and rules,
  `PARAMS`, `TAGS`, `build()` returning a build123d solid. Generated files (3MF, STL,
  GLB) are outputs; don't hand-edit them.
- **No feature trees, no constraint solvers.** Re-derive geometry from intent.
- **Checks are owned by the user.** Never loosen, delete or skip a check to make it
  pass. If a check fails, fix the geometry or stop and report.
- **Verify, don't assume.** "It ran without errors" is not success. Success is: checks
  pass and, for an existing part, the load check (fingerprint + tags + diff) is green.
- **Punk engineering.** Prefer existing libraries (build123d, yet-another-cad-viewer,
  three.js, trimesh) over writing new ones. Small, readable modules.

## Conventions

- Python 3.11+, manage with `uv`; pin build123d and OCP versions in the lock file:
  geometry must not drift silently between machines.
- Units: millimetres everywhere. Z up.
- Tests: `pytest`. Each Note gets a test that builds it and runs its checks
  (`tests/test_notes.py` picks up every Note under `notes/`).
- Every saved version stores a GLB and a fingerprint JSON next to the Note.
- The MCP SDK is v2 (`mcp.server.mcpserver.MCPServer`, not `FastMCP`).

## Reference: the MG400 work table

`reference/mg400_rakis/` is the first real project, built in Fusion 360:
- `build_rakis_F.py`: Fusion API script (runs only inside Fusion, via
  `exec(open(path).read())` in Text Commands). Read it for geometry and intent; do not
  try to run it here.
- `F_report.json`: what that script produced (body sizes, volumes, heights). Use as
  acceptance numbers when porting.
- `RAKIS_SYSTEM.md`: system description for students' holder design (coordinate
  frame, Gridfinity grid, cell table, cable space).

Porting notes:
- Fusion API units are centimetres; F_report values are already mm.
- The nest pocket comes from projecting the MG400 base outline from the robot model:
  190 x 190 mm, corner radius 10 mm (measured in Fusion).
- Fusion's taper sign was found by trial (keep the cut that removes less volume);
  in build123d use `extrude(..., taper=...)` and check the result the same way.
- Printer for this project: Bambu Lab X1C, bed 256 x 256 mm, PLA.

## Where things stand

The four first tasks are done (skeleton, the MG400 port, fingerprint + load check, canvas).
The README's "What is missing" is the list of what comes next. Things that are easy to get
wrong:

- **Accounts as in Adam Designer** (`monet/auth.py`, `monet/store.py`): an admin lets people
  in; a card link sets the first password; there is no signing up. Each user has one
  workspace, in a folder named by their user id (never by name or key).
- **Two doors.** The person: `/w/<username>/…`, behind the login (cookie, or HTTP Basic for
  scripts). Their agent: `/w/<agent key>/agent/<tool>` (POST JSON), `/w/<agent key>/mcp`,
  `/w/<agent key>/upload/<project>/<note>` (a build, as a zip) and `/w/<agent key>/file/…` (GET),
  with the key as the only credential. There is no GET or parts workflow for fetch-only LLMs:
  agents need a shell (Kaspar, 2026-10-26). A route belongs to one
  door or the other (`api()` and `door()` in `monet/app.py`); do not make one answer to both.
- **No model in the server.** The agent is the user's own harness. One definition of the
  tools serves MCP and HTTPS: `monet/agent.py`; it is described for LLMs at `/api`.
- **The server never runs a Note** (Kaspar, 2026-10-26). The agent builds on the user's computer
  (`monet/build.py`, shipped in the skill zip with the server's own modules and its kernel pinned:
  `builder_script()` in `monet/app.py`) and uploads; `Project.accept_build` takes it only if every file
  it read matches (`note.dep_key`: the Note's own file by `geometry_key`, without its TAGS/JOINTS/GROUND/
  TIPS) and the libs equal `runner.versions()`. A canvas edit of those literals is worked out on the
  server from the stored build (`monet/derive.py`, with the mesh ray test of `monet/rays.py`, which the
  runner uses too). Never add a path that builds on the server; templates are prebuilt into the image
  (`monet/prebuild.py`). The load check compares an uploaded build of the saved version (`waiting`
  until there is one). Keep accounts and secrets out of `storage/`.
- **Snap points and instances** (Kaspar, 2026-10-27): a Note's `SNAPS` (computed; the runner records them in
  `result["snaps"]`, `derive.clean_snaps`) say where other Notes may go; `PLACED` (a plain literal the person
  rewrites through `PUT …/placed/<name>`) puts them there, and build() reads it, so placing makes the assembly stale
  until the agent builds (decided: not composed on the server). `derive.attached` holds each instance on the body
  its snap is `on`. The canvas draws the snaps in Assembly → Place and ghosts what is not built yet.
- **Git is the user's**, in a folder on their computer; the server keeps numbered versions.
  No git on the server.
- **The agent's door has no tool to change or remove a check, acknowledge a load check,
  delete a Note, or delete a project or bring one in from an archive** (an archive carries
  checks). Those are routes of the canvas API only. Keep it that way. That is also why the agent
  runs **no code in the person's canvas** (Adam Designer's `page` was left out on purpose, Kaspar
  2026-10-25): code in a logged-in page is the person, and no route could tell it apart. The agent
  edits at file level through its tools; the page answers only `screen`, `goto` and `view`.
- **The agent key alone opens the agent's door; there is no remote control switch** (Kaspar, 2026-11-13: the
  agent runs on the person's computer, started by their own hand, so a switch and its 15 minutes were one step too
  many). A new key closes it (the person's, or an admin's for them); logging out does not. Do not bring a switch or a
  timer back without him. What is left in `monet/remote.py` and `canvas/remote.js` (from Adam Designer's docs/15,
  without its `page`) is the agent's line to the open canvas: only the person's own pages dial
  `/w/<username>/api/remote/tab`, never an admin's looking in, and they answer `screen`, `goto` and `view`.
- **Monet local and the terminal** (Kaspar, 2026-11-13; the plan is docs/REWIRE.md): `skill/monet/scripts/local.py`,
  started by `monet.py local <project> [folder]`, runs on the person's computer: it sends, builds and uploads the
  folder's Notes as they change, writes what the canvas changed into the folder, and leaves a file changed on both
  sides alone (no merge yet). `canvas/terminal.js` opens a websocket from the page **straight to 127.0.0.1**; decided:
  direct only, never relayed through the server. Monet local takes only the Origin of the Monet it is linked to and
  a token it knows, and starts only names from its own list (`runs()`): the page never sends a command line.
  **One line starts it** (Kaspar, 2026-11-13: anything more was too complicated): the Terminal panel shows
  `uv run <origin>/start.py <agent link> <project> --pair=<token>`; `/start.py` (public, no key in it:
  `skill/monet/scripts/start.py`) fetches `/skill.zip` into `~/.cache/monet`, keeps the link, and runs local.py in
  `~/monet/<project>`. The page makes the token (kept in its localStorage) and looks for Monet local by itself on
  the ports of `PORTS` (the same list in local.py and terminal.js; the first free one is taken). What Monet local
  says (`say()`) is the same in its own terminal and in the panel's Activity tab. It looks at the folder every
  second and at the server every few (`EVERY`), at once on a poke from the page. The agent link lives in
  `~/.config/monet/link` (`monet.py link`), never in a project's folder.
- **An uploaded archive is not trusted**: `Workspace.import_project` takes files by name
  against `ARCHIVED` and writes each under that name; it never extracts a zip to a path the
  zip gives. Keep it that way.
- **A Note is only ever executed in `monet/runner.py`**, in its own process, on the agent's computer
  (or for the templates, when the image is made). The server reads Notes with `ast` (`monet/note.py`),
  so `TAGS`, `JOINTS`, `GROUND` and `TIPS` must stay plain literals.
- **Joints are as-built** (`monet/joints.py`; the canvas's copy is `canvas/motion.js`, and a test
  holds the two together): 0 is where `build()` puts the parts, a joint only says how they may
  still move. No solver: a loop is `follows`, a linear sum of other joints. A clash is *new*
  overlap as a joint moves; what overlaps as built is the interference, reported apart. The
  server answers what a pose hits from the build's preview mesh (`Project.pose`), never by
  running the Note.
- **Facts that are no shape** (Kaspar's lamp issues, 2026-11-10): `MATERIAL`, `MATERIALS`, `MASS`, `POSES`, `BOM`
  and `DRIVES` are plain literals (`note.FACTS`), left out of `geometry_key`, worked out by the server from the stored
  build when it reports (`Project.facts`: mass from `materials.py`, torque by virtual work in `joints.torque`, the BOM in
  `bom.py`; `POSES` in `derive`, as joints are). `KEEPOUT` and parts named `keepout_*` *are* geometry: the runner leaves
  them out of the fingerprint and exports, `joints.analyse` out of interference and sweeps. A Note's optional
  `pieces()` (usually `monet.split.split`) is what is printed: exports and `fits_bed`/`solids` follow it, the
  assembly still uses `build()`. The agent may write a timeline (`animate`): it changes no geometry.
- **The action line is data, never code** (Kaspar, 2026-11-11): the timeline's `actions` have two verbs, `pause` and
  `goto` (`workspace.ACTIONS`); add a verb when one is needed, never a script, since the agent runs no code in the canvas.
  Playing steps through `advance` in `canvas/timeline.js`, and a video through its Python copy in `workspace.py`
  (`played`); `tests/advance.json` holds the two together. The finish by picture models is planned in the README
  ("Showing it"); who calls the models is still open.
- **Slow work is a job** (issue #9): `render_animation` runs in `monet/jobs.py` (a process pool of one, a fresh process
  each, at most 4 waiting) and answers its progress (202 on the file route) until the file is there; never render in
  a request. The canvas renders its own video in the background (`canvas/video.js`, `startFilm`/`shoot` in canvas.js:
  frames between the view's pictures, from a frozen camera, poses by `placeParts`, levels by `lamps.lightly`, never
  `poseTo`/`setLevel`, which check clashes and restyle); it starts by itself when playing runs under 25 fps.
- **Pixels** (0.11.0, issue #10): a `pixels` light's pixels are solids of the parts it names, found by the build
  (`runner.pixels_of`, with the LEDs of the Note's `leds()`), in faces.json `pixels` and the report's `pixels`.
  `canvas/pixels.js` patches the parts' materials (onBeforeCompile, chained); colours are kept as shown (sRGB) and made
  light in the shader, as the offline renderer did. While pixels are lit the view tone-maps with Neutral, not AgX
  (AgX washes saturated blue out). Patterns are data (`lights.PATTERNS`), never code.
- **Lights** (0.10.0): `LIGHTS` is a fact (`note.FACTS`, out of `geometry_key`), checked in `monet/lights.py` against
  the build's part names when the report is made (nothing run); `canvas/lights.js` draws them in Motion: three.js
  spot lights with shadows (their shadow camera's `far` must reach as far as the light, or a projector's picture and
  the shadows stop at 500 mm), beams as instanced ribbons along rays cast with three-mesh-bvh against each part
  (moved with its part), bloom by EffectComposer only while lights are on. Their levels, `room` and `haze` are the
  animation's `lights`; on the timeline they are lines named `~name` (`kept`/`opened` in `timeline.js`).
- **One design, one project; its main is the Note named as the project** (Kaspar, 2026-11-11): no setting and no star.
  `status()` gives each row's `uses` (imports and `PLACED`) and the project's `main` (`workspace.main_of`: that Note, else a
  guess, `named: False`); `canvas/tree.js` makes the side panel's tree from them, the same in every room. Making a project
  of another design (`Workspace.project_of`) carries checks, so it is a route of the canvas API only.
- **`skill/monet/` is the single source of the agent's instructions**: the skill zip and the
  `guide` tool both serve it. When behaviour changes, change it there.

- **The canvas has no build step**: plain ES modules, three.js from a CDN by import map.
  `window.monet` exposes its state for `scripts/shot.mjs`: after a change to the canvas, drive
  it in headless Chrome and look at the picture. A build's faces, edges, points and parts are
  numbered in `faces.json`; those numbers only hold within one build.
- **Two different "workspaces"**: a workspace is a user's id and folder on the server; the
  three working areas of the canvas (Sketch, Part, Assembly) are called rooms in the code.

## Commands

```bash
uv sync
uv run monet                      # http://localhost:8000; prints the admin's first link
uv run python -m monet.prebuild   # the templates, built once (new projects open built; pytest does it too)
uv run pytest                     # builds every template Note (where not current) and tests the uploads; node tests too
MONET_URL=<agent link> python skill/monet/scripts/monet.py build <project>   # build here and upload, as an agent does
node --test tests/measure.test.mjs   # the measuring geometry alone
node --test tests/motion.test.mjs    # where the canvas puts parts at a pose of their joints
uv run python notes/mg400_rakis/_verify.py     # the port against the Fusion numbers, as a table
node scripts/shot.mjs http://localhost:8000/w/<id>#starter/rod_foot shot.png   # the canvas in headless Chrome
                                  # (SHOT_COOKIE='monet=<the login's cookie>' logs it in; --type types into what has the focus)
python skill/monet/scripts/monet.py local <project> [folder]   # Monet local: the folder watched, the canvas's terminal
```

`reference/mg400_rakis/measured_from_fusion.json` holds what was measured from the Fusion
model itself: the robot base outline (190 x 190 mm, corner radius 10) and exact volumes and
surface areas of the bodies. Surface area is a much sharper acceptance test than volume.
