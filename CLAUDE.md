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
  scripts). Their agent: `/w/<agent key>/agent/<tool>` (GET or POST), `/w/<agent key>/mcp`
  and `/w/<agent key>/file/…`, with the key as the only credential. A route belongs to one
  door or the other (`api()` and `door()` in `monet/app.py`); do not make one answer to both.
- **No model in the server.** The agent is the user's own harness. One definition of the
  tools serves MCP and HTTPS: `monet/agent.py`; it is described for LLMs at `/api`.
- **Online, the web app never runs a Note**: it asks the runner container (`monet/buildd.py`),
  which has the working files and nothing else. Keep accounts and secrets out of `storage/`.
- **Git is the user's**, in a folder on their computer; the server keeps numbered versions.
  No git on the server.
- **The agent's door has no tool to change or remove a check, acknowledge a load check or
  delete a Note.** Those are routes of the canvas API only. Keep it that way.
- **A Note is only ever executed in `monet/runner.py`**, in its own process. The server
  reads Notes with `ast` (`monet/note.py`), so `TAGS` must stay a plain literal.
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
uv run pytest                     # about a minute and a half: builds every Note; runs the node tests too
node --test tests/measure.test.mjs   # the measuring geometry alone
uv run python notes/mg400_rakis/_verify.py     # the port against the Fusion numbers, as a table
node scripts/shot.mjs http://localhost:8000/w/<id>#starter/rod_foot shot.png   # the canvas in headless Chrome
```

`reference/mg400_rakis/measured_from_fusion.json` holds what was measured from the Fusion
model itself: the robot base outline (190 x 190 mm, corner radius 10) and exact volumes and
surface areas of the bodies. Surface area is a much sharper acceptance test than volume.
