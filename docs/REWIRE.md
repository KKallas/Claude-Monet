# The rewire: your repo, your computer, Monet as the window

*A plan, written 2026-11-13 for the design work that starts 2026-11-14. Nothing here is built.
The decisions are Kaspar's, made 2026-11-13, and marked "Decided" where they apply. Google Drive was
in the plan for a few hours and is out: the home is git, nothing else.*

## What is built (2026-11-13, branch `rewire`)

The first slice of steps 1 and 2: Monet local (`skill/monet/scripts/local.py`) and the Terminal
panel (`canvas/terminal.js`), tested in `tests/test_local.py` and by hand in headless Chrome
against a server on localhost.

- **Started with one line.** The panel shows it (`uv run <origin>/start.py <agent link> <project>
  --pair=<token>`), the person pastes it into a terminal, and the panel finds Monet local by
  itself. The first version asked for a repository, `link`, a folder and a second link to open:
  too many steps (Kaspar, the same day). `monet link`, `open` and `init` of the plan below are
  this one line now; what is left of them is git.

- The folder's Notes are sent, built and uploaded as they change; a file changed in the canvas is
  written into the folder; one changed on both sides is left alone and said. **Whole files, no
  merge by key yet**, and no git: `open`, `init`, deposits and the board are not built.
- The terminal runs Claude Code, Codex or a shell in the folder, lives on when the page reloads,
  and is reached only from the linked Monet's pages with the computer's token.
- **Remote control is gone** (Kaspar, 2026-11-13): no switch, no 15 minutes. The agent key alone
  opens the agent's door; a new key closes it. So Monet local simply looks at the server every
  few seconds, and a hand edit in the canvas is in the folder within that.
- **The try from an https page is not finished.** From `https://example.com` in Chrome 155 a
  websocket to `ws://127.0.0.1` was neither refused nor opened in 20 s, which is what a waiting
  permission prompt ("access other apps and services on this device") looks like; nobody was
  there to click it. To be done by hand on the test instance, in Chrome, Firefox and Safari.
- The view is not made smaller by the open terminal: the panel lies over its lower part.

### Added 2026-11-14

- **The brief: `PROJECT.md`.** The first piece of "Let it rip" (`NEXT.md` in the plan below is this file's Next and
  Log): one Markdown file beside the Notes that says what the project is, where its repository and its issues are,
  what is done, the milestones, what to do next, and who did what. An agent reads it first and brings it up to date
  before it stops (the tools `brief` and `write_brief`, `monet.py brief` / `write-brief`); the person reads and
  writes it in the canvas (**Brief**, beside the project's name). Monet local keeps it in step with the folder like
  a Note; it is in the archive and in every saved version. So a project can be picked up on any computer by
  anybody's agent with nothing but its folder: a friend with tokens left over at the end of the week clones the
  repository, runs the one line against their own Monet, and their agent starts from Next.
- **A sitting with a limit.** `--for=2h` (or `90m`) on the one line: the agent in the terminal is told when the
  sitting ends (`MONET_UNTIL`), Monet local says so ten minutes before, and the skill tells the agent to have the
  brief written by then. Nothing is stopped. A limit in tokens is the harness's own to keep; the skill says the same
  for it: stop at a whole step with enough left to write the brief.
- **The folder is the whole project** (the same day, later): Monet local writes each Note's checks
  (`<note>.checks.json`) and the settings (`monet.json`) into the folder as the person changes them in the canvas,
  and brings a cloned folder's into a server that lacks them: the project is made there if there is none, and the
  folder's checks are added. Added only: "the server's checks rule" (decided above) holds, a check is never changed
  or removed from a folder. Git itself is the agent's to do with `git` and `gh` on the person's computer (the
  skill's `references/repository.md`; for the person, `docs/REPOSITORY.md`). Saved versions are not in the folder:
  git is the history, and a save is a tag.
- **MCP is out** (Kaspar, 2026-11-14), with the Connect dialog and the skill download that carried the link. One
  way in for an agent: HTTPS, through the skill's script. *New key* moved to the Terminal panel.
- **Going between rooms** while Monet local uploads no longer leaves the frame on the Note before: one `open()`
  rules at a time (`canvas.js`), the page's own look every two seconds waits for it, and while another Note is
  fetched the frame fades and says which one is coming.

## In one paragraph

Today a project lives in Monet's `storage/` and your git is a copy beside it. After the rewire it
is the other way round: **a project lives in a git repository of yours** (GitHub, or any git remote), your own agent
(Claude Code or Codex) works on it on your computer, and Monet holds only what it needs to show it
and to let you edit by hand: the latest builds, a mirror of the sources, the checks. A small
program on your computer, **Monet local**, ties the three together, and the canvas gets a
**terminal** that talks to it. What Monet is for moves from printed jigs to **small electronic
products**: bought LEDs, servos and controllers, 16 mm aluminium pipe, routed aluminium and wood,
printed parts between them. The lamps are the first examples.

The reason: a project that is a plain repo can be picked up by anyone and any agent. When there
are credits left at the end of the week, you open Monet, pick a project that would otherwise fade,
and let the agent run on it.

## Three places

| place | what it holds | who writes it |
|---|---|---|
| **Home**: a git repository (GitHub, or any remote) | everything that is the project: Notes, checks, animations, looks, the brief. The truth. | you and your agent |
| **Your computer**: the working folder, and Monet local | the working files, the builds, the agent and its credits | the agent; Monet local |
| **Monet** (500 MB a user) | accounts, and **the session**: the projects you are working on or last worked on, with their sources, current builds and checks | Monet local uploads; you edit by hand in the canvas |

Monet stays what it is: it never runs a Note, has no model in it, and has no git. Losing the
server loses previews, nothing else: everything on it except accounts can be made again from the
home.

## Monet local

`skill/monet/scripts/monet.py` grown into a program that stays running. It already pulls, pushes,
builds and uploads; what is new is that it watches, and that it serves a terminal.

```bash
monet link https://monet.roboarena.org/w/<agent key>   # once per computer: the key goes to ~/.config/monet/, never into a repo
monet open github.com/kaspar/orb-lamp                  # clone (your own git and login) into ~/monet/orb-lamp, tell Monet its home
monet local                                            # watch, build, upload, bring hand edits back, serve the terminal
```

While it runs, in each linked project:

1. **Files → Monet.** A Note changed on disk is sent, built with the pinned builder
   (`monet/build.py`, as now) and uploaded. `accept_build` and its rules stay as they are.
2. **Hand edits → files.** What you changed in the canvas comes down and is written into the
   working files (see "Hand edits go back"), where the agent sees it at once.
3. **The terminal.** A websocket on `127.0.0.1` that gives the canvas a PTY in the project's folder.

**The canvas shows the working copy** (Kaspar, 2026-11-13). While you and the agent work, what
is on screen is the files as they are on your computer at that moment, committed or not: every
change the agent writes is built and shown, without waiting for a commit. The repo gets the work
when it is done: **depositing** is the save that exists (every Note built, checks green), made
into one commit, tagged and pushed. So there are two states, and the canvas always says which:

- **working**: "the working copy on <computer>, 4 changes not deposited", with what changed
  since the last deposit drawn by the diff that exists;
- **deposited**: "as deposited, commit `9396d73`", when nothing has changed since, or when Monet
  local is not running and the session is what was last seen.

Work in progress is therefore in two places only, your disk and Monet's session, and in neither
for good: nothing is safe until it is deposited, and the canvas says so when you close it with
changes open. The agent may commit along the way in its own branch if it likes; what counts as
a version is a deposit.

It runs with uv, as the builder does, shipped by the server with its own modules pinned
(`builder_script()` in `monet/app.py` is the pattern). Starlette, uvicorn and websockets are
already dependencies. PTY: the standard library on macOS and Linux; Windows (pywinpty) later.

## The terminal

A panel in the canvas, [xterm.js](https://xtermjs.org) from the CDN by the import map (no build
step). It opens a websocket **from the page straight to Monet local on this computer**. The server
is not in between and never sees a byte of it.

- It starts one of a short list, in the project's folder: `claude`, `codex`, or a shell. The list
  is Monet local's own; the page picks by name and cannot send a command line.
- The PTY has `MONET_URL` in its environment, so the skill's script works
  with no setup. The key is never written into the repo.
- **Pairing.** `monet local` prints a link to your canvas with its port and a random token in the
  URL's fragment (which is not sent to the server); the page keeps it. Monet local binds to
  127.0.0.1 only, and answers only that token from the `Origin` of the Monet it was linked to.
  Without those, any web page you visit could open a shell on your computer.
- **What stays true.** The agent still runs no code in your canvas; this is the other direction,
  your page driving your terminal. What is typed there is you. The agent in it reaches Monet
  through the agent door like any other, under the same rules. There is no remote control switch
  any more (taken out 2026-11-13): the agent key opens the door, a new key closes it.
- **To be honest about.** The page's code comes from the server, so whoever controls the server
  could drive a terminal that is open. That is the trust given by linking; Monet local says which
  host it is linked to, and self-hosting stays one command.
- **To try on day one.** An https page opening `ws://127.0.0.1`: Chrome and Firefox treat loopback
  as secure; Chrome asks for local network access once; Safari has refused this before. If Safari
  still does, the answer is "use Chrome for the terminal", not a relay.

**Decided 1: direct only.** No relay: the server never carries a terminal. (A relay would let you
watch from a phone, and would make the server a way into every connected computer.)

## The home: a git repository

**The repo is the archive, unpacked.** Download already makes a zip of a project's Notes, their
checks and `monet.json` (`Project.archive`, `ARCHIVED`). The repo has the same files under the
same names, without the saved versions (git is the history), plus what an agent needs to start
cold:

```
orb-lamp/
  orb.py  orb_skin.py  …      the Notes; the main is the one named as the project, as now
  orb.checks.json  …          each Note's checks (a mirror: the server's copy counts)
  monet.json                  printer, material, looks, animations
  NEXT.md                     the brief: where it stands, what to do next (see "Let it rip")
  AGENTS.md  CLAUDE.md        three lines pointing at the skill
  .claude/skills/monet/       the skill, without link.txt
  .gitignore                  out/, .monet/
```

`monet init` writes the last four. Then "if I can work on it, an agent can" holds for a fresh
clone on any computer.

- **GitHub** goes through your own git on your computer: `git clone`, your login, your SSH key.
  The server needs no GitHub app, no OAuth and no token; it stores the repo's address and, for
  each build and saved version, the commit it was made from. "No git on the server" stays.
- **A deposit is a save and a commit.** `Project.save` already takes a `commit`. Version n is
  that commit, with a tag `v<n>`, pushed by Monet local. Nothing is deposited on red, as nothing
  is saved on red now.
- **Who loads from the repo: Monet local, never the server** (the server has no git and its
  container has no way out to the internet, by design). "Reopening loads from the home" therefore
  needs Monet local running; without it the canvas shows the cached session and says as of
  which commit.

**Decided 2: git only, no Google Drive** (2026-11-13). One kind of home is simpler, and git
brings what a shared project needs: history, branches, forks, pull requests, and finding where two
people changed the same thing. So there is no provider sign-in in the page, no project file
format beside the repo, and nothing of Google's for a server to be set up with. GitHub is where
the community is; any git remote works, since it is your own git that talks to it. Download and
Upload of an archive stay as they are, for moving a project by hand.

People who do not know git do not have to: Monet local commits, pulls and pushes, and says in
words what it did. What it cannot do by itself is in "When two changed the same thing".

**Or run the server yourself.** `uv run monet` on your own computer is the whole thing with no
limit and no provider: storage is your disk. Worth a short form for this (`monet here`: serve the
folder you are in, for one person, Monet local in the same process), since then a clone of any
project repo is opened with one command and nothing leaves the computer.

**Decided 3: the server holds what you are working on, within limits.** A project need not have a
home to be worked on; everything in a session counts against the 500 MB, home or not. Besides the
total there are limits per upload and per project (see "The 500 MB").

## Hand edits go back

The canvas changes only plain literals (`TAGS`, `JOINTS`, `GROUND`, `TIPS`, `PLACED`, the facts)
and the files beside the Notes (animations, looks, settings). Today the server rewrites its own
copy. After the rewire it does that and also **writes the edit down as an operation**: "in
`orb.py`, `TAGS["hinge_pin"]` is now …", who and when.

Monet local takes the operations in order, applies each to the file on disk with the same code
the server used (`monet/note.py`), and sends the file back; when the literals match, the
operation is done. It is not committed by itself: it is part of the working copy, and goes into
the repo with the next deposit, whose message lists the hand edits beside the agent's work. An operation is by key, so it still applies when
the agent has changed the Note's `build()` meanwhile. While Monet local is not running, the edits
wait, and the project says "3 edits not in your working copy yet".

No merging of whole files anywhere. If an operation cannot be applied (the Note is gone), it is
shown to the person, not dropped.

## Checks stay yours

This is the one thing the rewire could break. In a repo the agent can write every file, and
checks belong to the user. So:

- **The server's copy of the checks is the one that counts.** It is what runs and what "green"
  means. The `<note>.checks.json` files in the repo are a mirror, written by Monet local from the server.
- When the repo's copy differs (the agent edited it, or you pulled someone's change), nothing
  changes on the server. The canvas shows the difference and you take it or not, logged in.
  Adding a check through the agent door stays allowed, as now.
- The same for acknowledging a load check and for deleting: canvas routes only, as now.

**Decided 4: yes, the server's checks rule.** A project opened from a repo for the
first time brings its checks in as the person's (they opened it); after that, a difference is
shown and taken or not.

## When two changed the same thing

Two people, or you and your agent, or the canvas and the repo. Git finds this by lines of text,
which is the wrong unit for a part: a conflict marker inside a Note helps nobody. Monet local
does the merge itself, from the three sides (what both started from, A, B), read with
`monet/note.py`:

1. **By key.** `PARAMS`, `TAGS`, `JOINTS`, `PLACED`, the facts and `monet.json` are merged a key
   at a time. Two people who changed different tags, joints or numbers never meet. A hand edit
   from the canvas is merged the same way, so "the canvas and the repo changed the same literal"
   is this case and no other.
2. **By curve.** A sketch is a tag that holds curves; it is merged a curve at a time. The same
   curve drawn two ways is one conflict, of that curve.
3. **`build()` and other code.** Changed on one side only: taken. On both: git's own merge of
   the text, and if it goes through, built and checked like any change. If not, the Note is the
   conflict.

**Settled by looking.** Monet local builds A and B and uploads both. The canvas shows what is in
question, one thing at a time, with the tools it has for comparing versions (the colour map,
crossfade, the wipe plane, blink):

- a curve or a tag: both drawn on the part in two colours, click **A** or **B**;
- a number: both values, and the part built with each;
- a whole Note: A beside B, and what each changed from where they started.

**Or the agent decides, where the intent can be read.** Your own agent, in the terminal (there is
still no model in the server). It reads both sides, their commit messages and the Notes' rules,
and writes a third candidate, **C**, that keeps what each meant; where code met code this is
re-deriving the geometry from intent, which is what a Note is for. C is built and shown beside A
and B. It may be taken without asking only when it can be shown to be right: every check passes,
and C differs from A only where B differed from the start, and from B only where A did (the diff
that exists measures this). Then the merge commit says what was decided and why, and the canvas
lists it to be looked at afterwards; it is one commit, so one revert undoes it. Otherwise it is a
proposal and you click.

- Checks are never merged by the agent, and never by key without you: a difference in checks is
  shown and taken or not, as above.
- While a merge is open the project says so, shows your side, and nothing is saved.

## The 500 MB

Measured today: the three workspaces in `storage/` are 88 MB; the one with the lamp is 76 MB; the
orb's `model.glb` alone is 19.6 MB and a `faces.json` up to 5.6 MB. Sources are nothing. So the
room goes to builds, and builds can be made again.

**Decided 5: the server is a cache of your sessions, and reopening loads from the home.** Close
the page and the last session is still there. When a project is opened again it is loaded from
its repo, not trusted from the cache: Monet local pulls, and the sources come from the working
copy (which is the home's, plus whatever was not deposited last time), and a
cached build is used only where it is a build of exactly those sources, which `dep_key` already
tells. The rest Monet local builds. If the session has hand edits the home never got, they are
shown first and you choose: put them into the home, or drop them. What is on the server is never
the only copy of anything that has a home, so making room is safe:

- Projects are put out whole, the one touched longest ago first, and only those whose home has
  everything (no edits waiting, everything pushed). One that was put out stays on the
  board with its home, and opens again from there.
- A project with no home, or with changes its home does not have, is never put out; when such
  projects fill the 500 MB, the canvas says so and asks you to save one somewhere.
- Limits besides the total, so one mistake cannot fill it: a size for one upload, for one
  project, and a count of projects. Numbers to be set from the lamp (its workspace is 76 MB).

Within a project:

- Counted per workspace (`Workspace.usage()`), shown in the header and on `/users`.
- **Always kept:** sources, checks, operations waiting, and for every saved version its
  fingerprint and its commit (a few kB).
- **Kept while there is room, oldest out first:** preview meshes of saved versions, then of Notes
  not opened lately. What was put out shows as *waiting for your agent*, which the canvas already
  knows how to say, and Monet local builds it again from the commit when asked for.
- **Never stored:** exports (3MF, STL, STEP, DXF) are made on your computer and fetched from
  there, or uploaded for one download. Videos are kept one per animation.
- An upload that does not fit after eviction is refused in words, with what to do.
- Worth doing by itself: smaller builds. A 19.6 MB GLB wants mesh compression (meshopt or Draco,
  both read by three.js) before it wants a quota.

`MONET_MAX_USERS` × 500 MB is the disk the droplet must have: 20 users, 10 GB.

**The library pin: the server's** (as read from the decisions above; say if this is wrong). A
build is taken only if its libraries equal the server's (`runner.versions()`), as now. Monet
local always builds with the builder of the server it is linked to (your own, when you run it
yourself), and the repo records which Monet built it. A repo built with another pin loads all the
same: its sources are taken, its builds are made again here.

## Let it rip

The use this is all for: leftover credits, a project that is fading, one evening.

- **`NEXT.md` in every repo**, kept by the agent as part of saving (the skill says so): what the
  thing is, where it stands, what is broken, the next three steps, what is waiting for the person
  to decide. A cold start costs one file.
- **The projects list becomes a board**: each project with its picture, its home, when it was last
  touched, the first line of `NEXT.md`, and whether this computer has it. The fading ones are in
  sight.
- **One click**: Monet local clones or pulls it, the terminal opens in its folder with the chosen
  harness and a first prompt ("read NEXT.md and carry on; build, check, save, commit; write
  NEXT.md before you stop"). You watch the canvas change as builds arrive.
- How freely the agent may act (its permission mode) is set by you in the harness. Monet local
  never adds a flag that skips permissions by itself.
- Later, if wanted: a run without the terminal (`claude -p`, `codex exec`) with its log in the
  panel, several projects one after another.

## What it is for: small electronic products

The lamps showed the way: `LIGHTS`, pixels and LEDs, `MATERIALS`, `MASS`, `BOM`, `DRIVES` and
torque, `pieces()`, snap points. The rewire of the content is to make those the centre.

1. **A catalogue of bought parts**, as Notes like any other, in a repo of its own that a project
   takes as a dependency: servos (SG90, MG90S, MG996R), LED strips and rings (WS2812B, SK6812),
   controllers (ESP32 boards, Pico), drivers, power supplies, switches, connectors, fasteners. Each
   has its shape (simple, or from the maker's STEP), `MASS`, `SNAPS` where it mounts, a `BOM` line
   with what to order and from whom (LCSC, AliExpress, a price and the date it was seen), and its
   electrical facts (see 4). The agent picks from it before it invents.
2. **16 mm pipe as stock**: a helper that cuts a length, drills it, and joins it with printed or
   routed nodes; the cut list in the BOM already exists (`bom.py`).
3. **Routed parts.** A Note says it is routed from a sheet (`MATERIAL`: aluminium 3 mm, plywood
   12 mm measured 11.6). New: a router profile in `profiles/` (bed, bits, smallest inside radius);
   checks that a flat part can be routed (one thickness, the sheet's; inside corners no tighter
   than the bit; fits the sheet); a DXF or SVG of the outline as an export (build123d writes
   both). For ordering routed aluminium from a shop, the same DXF and a STEP.
4. **Electronics, later, in two steps.** First as facts, the way `LIGHTS` are: what each bought
   part draws and offers (`volts`, `amps`, pins), and a `WIRES` literal that says what connects to
   what. From those the server can already report a power budget, wire lengths through the
   assembly and a wiring table, and checks can hold them (`power.5v.amps <= 3`). Then real tools,
   run by the agent on your computer and shown by Monet: SKiDL or atopile for the netlist in
   Python, KiCad's `kicad-cli` for schematic and board pictures, ngspice (PySpice) for simulation,
   Wokwi for firmware.
5. **Monet shows what Python tools made.** To make room for 4, a build may carry **views** beside
   the model: named SVGs, PNGs and tables, listed in `result.json`, taken by name as every upload
   is. The canvas gets a place to show them. A schematic, a cut sheet, a plot of a simulated rail:
   all views. Design this field with the rewire, even though only cut sheets use it at first.

Steps 1 to 3 need nothing from the rewire and can be worked on beside it, as Notes.

## What stays, what changes

**Stays:** the Note, the runner, `accept_build`, checks and the load check, tags and joints worked
out on the server, the canvas and its rooms, the two doors, the agent's tools,
jobs, accounts.

**Changes:**

| today | after |
|---|---|
| a project is a folder in `storage/` | a project has a **home**; `storage/` holds a mirror and what can be made again |
| git is yours, beside the server | the repo is the project |
| the canvas shows what the agent pushed | the canvas shows the working copy, live; the repo gets it at a deposit |
| `monet.py` is run by the agent, a command at a time | **Monet local** stays running: watches, builds, brings edits back, serves the terminal |
| the skill is a zip with your key in it | the skill is in the repo without a key; the key is in `~/.config/monet/` |
| no chat, no terminal in Monet | a terminal in the canvas, to your own computer |
| Download / Upload an archive | the same files as a repo; the archive stays, for moving a project by hand |
| two people cannot work on one project | git, and a conflict settled by looking: A or B |
| no limit | 500 MB, with eviction |
| printed jigs and brackets | small electronic products |

**Lines of CLAUDE.md that will need rewriting when this lands:** "Git is the user's … the server
keeps numbered versions"; the skill zip; "Checks are owned by the user" gains the mirror rule; a
new entry for Monet local and the terminal (direct to loopback, never relayed, the list of
harnesses, the pairing). README: the first three paragraphs, "Try it", "Chat: the agent",
"Running it for other people".

## In what order

Each step can ship and be used by itself.

0. **Tomorrow.** Two tries, half a day each: (a) xterm.js in the canvas talking to a PTY on
   loopback from the https page, in Chrome, Firefox and Safari; (b) the lamp project moved to a
   GitHub repo by hand and worked on from a fresh clone with today's `monet.py pull / push /
   build`, writing down everything that hurt.
1. **Home and Monet local, no terminal.** `link`, `open`, `init`, `local` (watch, build, upload).
   A project stores its home and each build its commit. The key moves out of the skill zip.
2. **The terminal.** The panel, the pairing, `claude` / `codex` / shell.
3. **Hand edits as operations**, and the checks mirror with its "take it or not". `monet here`.
4. **Conflicts settled by looking**: the merge by key, A and B built and shown, the agent's C.
   Then **the 500 MB**: usage, the limits, putting a project out and opening it again; mesh
   compression.
5. **Let it rip**: `NEXT.md` in the skill, the board, the one click.
6. **Views** in a build; routed parts with their cut sheets as the first use.
7. **Electrical facts and `WIRES`**; then the netlist and simulation tools as views.

Beside all of it, from day one: the catalogue, the pipe helper, and a second and third product
after the lamp, since they are what will show whether the format holds.

## Test and release, on one droplet

Two instances beside each other, so that what is merged can be tried before people work on it.

- **One Caddy, two apps.** `compose.yml` gets a second app service; the Caddyfile a second name.
  `monet.roboarena.org` is release, `test.monet.roboarena.org` is test (one more A record). Each
  has its own `storage` and `data` folders, so its own accounts, keys and session secret. Images
  are tagged `monet:test` and `monet:release`, not `latest`.
- **The path of a change.** A pull request runs the checks in GitHub (`deploy.yml` does this
  already, for forks too, without secrets). Merged to `main`: sent to **test** by itself, as now.
  **Release** only when you say so: a tag `v0.12.0` (or a button on the workflow) sends that
  same image, already tried on test, to release. `rollback.sh` takes which of the two.
- **Never a pull request's code on the droplet.** Only what is merged is sent. The deploy key and
  the people's files are on that machine.
- **Room.** The droplet is laid out for one app (2 GB, the app's ceiling 1500 MB) and every image
  is near 3 GB. Two apps want a 4 GB droplet, or a lower ceiling for test; and the disk must hold
  the images, release's 500 MB a user, and a small test storage (test: few users, wiped freely).
- **Tests of the whole thing**, run against test after each deploy: log in, open the starter,
  build and upload it with the skill's script, look at the canvas with `scripts/shot.mjs`. This is
  the piece that is missing today: the checks in GitHub test the code, nothing tests the instance.

## Many hands

What the rewire is for in the end (Kaspar, 2026-11-13): a community. Someone describes a thing
they want, a lamp, a robot game, a change to Monet itself; people with tokens left at the end of
the week take it up and their agents do the work. Anyone may run a server. A project that is
public can be finished by others when its owner has no time or money.

**Two boards, both GitHub's.**

- **Monet itself**: issues in this repository. An issue an agent can take says what is wanted,
  how to tell it is done (which test, which picture), and what not to touch. Labels: `ready`
  (described well enough to take), `taken`, `needs Kaspar`. `CONTRIBUTING.md` and this repo's
  `CLAUDE.md` are what a stranger's agent reads. A pull request brings the test output and, for
  the canvas, a picture from `scripts/shot.mjs`. `main` is protected: the checks green and your
  review. Changes to `tests/`, `deploy/`, `.github/` and `monet/auth.py` always need you
  (CODEOWNERS): an agent must not make a test pass by changing the test, as with checks.
- **Projects**: a public project is a public GitHub repo with the topic `monet-project`. Its
  `NEXT.md` says where it stands; its issues are what is asked for. The board in Monet is a page
  that lists them, read from GitHub by the visitor's browser (the server has no way out). So the
  board is the same on every server, and belongs to none.

**Helping on someone's project.** Fork it, open the fork in your own Monet (any server, or `monet
here`), let your agent work, and send a pull request when the checks are green, with a link to
the preview. Where the owner changed the same thing meanwhile, it is settled as in "When two
changed the same thing", by whoever merges. The owner's checks rule: an action in the project's repo builds the Notes and runs
the checks **of the branch being merged into**, so a pull request cannot loosen a check to get
in. (This needs the checks to run without a server: `monet check`, the same code as the
server's.) The owner sees the diff of the geometry in their own canvas before merging.

**What this brings that is new and dangerous.** Until now everyone built only their own Notes.

- **A Note is Python.** Building a stranger's project runs their code on your computer, beside
  your agent's logins. Monet local must build what is not yours shut in: no network, no files
  but the project's (a container, or the system's sandbox). This has to exist before the board.
- **`NEXT.md` and issues are a stranger's words to your agent**, which has a shell. The first
  prompt for a project that is not yours says so, the agent does not run with permissions
  skipped, and the work happens in that same shut-in place.
- **A preview is a claim.** A build someone else uploaded is not proof (README, "Running it for
  other people"); the action in the repo, building again, is.

**Not decided:** whether a bounty is ever money. Assumed no: it is thanks and a name in the
history. Money brings payment, disputes and tax, and should be a decision of its own.

## What is not described yet

Enough is written to do the two tries and steps 1 and 2. Before the later steps can be handed
to someone as a ticket, these need a page each:

1. **The operations**: their format, the two agent tools that fetch and confirm them, and what
   happens when the canvas and the repo changed the same literal.
2. **The merge**: the units a Note is merged by, how a sketch's curves are told to be the same
   curve, and where the builds of A, B and C are kept while a merge is open.
3. **Limits**: the numbers.
4. **The catalogue as a dependency**: a build is taken only if every file it read is on the
   server (`dep_key`). How a project names the catalogue's version and how its files get there.
5. **The shut-in build** for a project that is not yours.
6. **`monet check` and `monet here`**: the server's checks run on a folder, with no accounts.
7. **Windows**: the terminal there.
8. **How each step is tested**: what must be true, written as tests before the step is built.
