# Your project in a git repository

*For the person. Your agent has the same in its own words (the skill's `references/repository.md`), so most of
this it does for you.*

A Monet project is a folder on your computer, `~/monet/<project>`, and that folder is the whole project: the
Notes (the parts, as Python), the brief (`PROJECT.md`: what it is, what is done, what comes next), the checks and
the settings. Put it in a git repository and it has a history, a place for issues, and it can be picked up on
another computer: by you, or by a friend whose agent has tokens to spare.

You do not type git commands. You tell your agent what you want.

## Once on a computer

Three programs. Your agent checks them and tells you which is missing; if you would rather do it yourself:

| | macOS | Windows | Linux |
|---|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) (runs Monet's tools) | `brew install uv` | `winget install astral-sh.uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| git | `xcode-select --install` | `winget install Git.Git` | your package manager |
| [gh](https://cli.github.com) (GitHub from the command line) | `brew install gh` | `winget install GitHub.cli` | see cli.github.com |

Then log in to GitHub, once. This is the one step that is yours: it opens your browser, and your agent never sees
your password.

```
gh auth login        # GitHub.com, HTTPS, "Login with a web browser"
gh auth setup-git
```

And an agent with a shell: [Claude Code](https://claude.com/claude-code) or Codex. (Monet local is macOS and
Linux for now.)

## Start working

1. Open your project in Monet and press **Terminal**. Copy the one line it shows, paste it into a terminal, leave
   it running. Your folder is `~/monet/<project>`.
2. In the Terminal panel, open the **Claude Code** (or Codex) tab. That is your agent, in the folder.

## What to say

| you want | say |
|---|---|
| a repository for this project | "Put this project in a git repository on GitHub, private." (or "public") |
| to go on where it was left | "Read the brief and go on with what is next." |
| to see what is open | "What is open on this project?" |
| a job written down for later | "Make an issue: the visor hinge needs knuckles." |
| to hand it on for today | "Bring the brief up to date, commit and push." |
| a friend to work on it | "Invite the GitHub user mari-k to this repository." |
| somebody's project on your computer | "Clone github.com/kaspar/cube and set it up here." Then paste your own Terminal line, with `cube` as its last word |
| a sitting with an end | add `--for=2h` to the Terminal's line: the agent is told, and writes the brief before time is up |

## What goes where

- **Notes, the brief, the settings**: in the folder, changed by your agent and by you in the canvas, committed.
- **Checks** (`<note>.checks.json`): in the folder so that they travel, but **changed only by you, in the
  canvas**. An agent can add a check; it cannot loosen or remove one, neither through Monet nor through a file. If
  a repository you pulled changed a check, Monet says so and leaves yours as it is: you decide.
- **Your agent link**: never in the folder, never in the repository. It is kept in `~/.config/monet/link` on your
  computer. If it got out, press **New key** in the Terminal panel.
- **Builds** (the 3D models): on the Monet server, made again from the Notes on any computer. Not in the repository.

## A friend picks it up

They need: the three programs above, an agent, access to the repository (you invite them, or it is public), and
an account on a Monet (yours, if you let them in, or any other: the project does not care which).

They tell their agent: "Clone github.com/you/project and set it up." They paste their own Terminal line with the
project's name. Their Monet local makes the project on their Monet, builds every part (a few minutes the first
time) and brings the checks along. Their agent reads the brief, takes the first thing under *Next*, and before it
stops writes down what it did, for you and for whoever comes after.
