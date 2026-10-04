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

- **No accounts, on purpose.** A workspace id in the address is the whole access;
  `MONET_MAX_USERS` is the only limit. Do not add logins.
- **No model in the server.** The agent is the user's own harness, connected over MCP
  (`/w/<id>/mcp`) or plain HTTPS (`/w/<id>/agent/<tool>`, GET or POST; described for LLMs at
  `/api`). One definition of the tools serves both: `monet/agent.py`.
- **Git is the user's**, in a folder on their computer; the server keeps numbered versions.
  No git on the server.
- **The agent's door has no tool to change or remove a check, acknowledge a load check or
  delete a Note.** Those are routes of the canvas API only. Keep it that way.
- **A Note is only ever executed in `monet/runner.py`**, in its own process. The server
  reads Notes with `ast` (`monet/note.py`), so `TAGS` must stay a plain literal.
- **`skill/monet/` is the single source of the agent's instructions**: the skill zip and the
  `guide` tool both serve it. When behaviour changes, change it there.

## Commands

```bash
uv sync
uv run monet                      # http://localhost:8000
uv run pytest                     # about a minute: builds every Note
uv run python notes/mg400_rakis/_verify.py     # the port against the Fusion numbers, as a table
node scripts/shot.mjs http://localhost:8000/w/<id>#starter/rod_foot shot.png   # the canvas in headless Chrome
```

`reference/mg400_rakis/measured_from_fusion.json` holds what was measured from the Fusion
model itself: the robot base outline (190 x 190 mm, corner radius 10) and exact volumes and
surface areas of the bodies. Surface area is a much sharper acceptance test than volume.
