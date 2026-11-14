# The project's repository: git, done by you, for the user

The user says what they want ("put this in a repository", "pick up the lamp", "what is open?", "share it with
Mari"); you do it with `git` and `gh` in their shell. They should never have to type a git command. This file is
the recipe. Read the brief first (`PROJECT.md`): it names the repository and where the issues are.

## What is in the folder

With Monet local running, the project's folder holds the whole project, and all of it is committed:

| file | what | who changes it |
|---|---|---|
| `<note>.py` | the Notes and helper modules | you, and the person through the canvas (tags, joints, placed parts) |
| `PROJECT.md` | the brief: what, where, state, next, log | you, at the end of every sitting; the person |
| `<note>.checks.json` | each Note's checks | **the person, in the canvas.** Monet local writes it here. Never edit it |
| `monet.json` | printer, material, looks, animations | the person in the canvas, you through the tools (`animate`, `set_profile`) |
| anything else you made | `print/`, `tools/`, drawings, a bill of materials | you |

Not committed: `.monet/` (Monet local's memory of what both sides agreed on), `__pycache__/`. No key, agent link
or password is ever in the folder: the link lives in `~/.config/monet/link`.

## 0. Is the computer ready? (once)

```bash
git --version && gh --version && gh auth status
```

- No `git`: macOS `xcode-select --install`; Windows `winget install Git.Git`; Linux the package manager.
- No `gh`: macOS `brew install gh`; Windows `winget install GitHub.cli`; Linux https://cli.github.com.
- `gh auth status` says not logged in: **the user does this one themselves**, it opens their browser:
  `gh auth login` (GitHub.com, HTTPS, "login with a web browser"). Then `gh auth setup-git` so `git push` works.
  Do not ask for, type or store a token or a password.
- `git config user.name` / `user.email` empty: ask the user what to put (GitHub offers a no-reply address under
  Settings → Emails), then `git config --global user.name "…"` and `user.email "…"`.

Tell the user what is missing in one message, with the one command for their system, and go on when it is there.

## 1. A project that has no repository yet

In the project's folder (`~/monet/<project>`, where Monet local keeps it):

```bash
cd ~/monet/<project>
git init -b main
printf '.monet/\n__pycache__/\n*.pyc\n.DS_Store\n' > .gitignore
git add -A && git commit -m "<project>: as it stands"
```

Then the remote. **Ask the user two things first, and only these: private or public, and under which account or
organisation.** Private unless they say public: a public repository shows the design to everybody and cannot be
taken back once it was seen. Name it as the project, so a clone lands in a folder of the right name:

```bash
gh repo create <owner>/<project> --private --source . --push --description "<the brief's first sentence>"
```

Write both addresses into the brief under *Where it lives* (Repository, Issues: `…/issues`), turn the brief's
*Next* into issues if the user wants the list there (one issue a line, `gh issue create --title … --body …`, and
put `#<number>` beside each line in the brief), commit and push.

## 2. Every sitting

Start:

```bash
git pull --rebase            # what the others did; Monet local sends what came in to the server and builds it
gh issue list --limit 20     # what is open, beside the brief's Next
```

If the pull does not go through because of your own uncommitted work, `git stash`, pull, `git stash pop`. If two
people changed the same lines of a Note, git marks the conflict in the file: **do not send a file with conflict
marks to Monet** (it will not build). Read both sides, write the Note that keeps the intent of both, build, look.
If the intents contradict, stop and ask the user.

Work as the skill says (edit, build, look, green). Commit when a step is whole:

```bash
git add -A && git commit -m "<what changed and why>  (#<issue>)"
```

After `save` answered `saved: true`: `git commit -m "v<version>: <the save's message>"`, and
`git tag v<version>` so the repository's history and Monet's versions name the same things.

End (after the brief is up to date):

```bash
git add -A && git commit -m "<date>: <what this sitting did>" && git push && git push --tags
```

`gh issue close <n> --comment "<what was done, in which commit>"` for what is finished; comment on what is half
done so the next one knows. **Push only what is green, or say plainly in the commit and the brief what is red and
why.** Never `git push --force`, never rewrite pushed history, never commit with `--no-verify`.

## 3. Picking up somebody else's project (theirs, or yours on another computer)

```bash
gh repo clone <owner>/<project> ~/monet/<project>     # the folder is named as the project
```

Then the user presses **Terminal** in *their own* Monet canvas and pastes the one line it shows, with the
project's name as its last word (they need an account on a Monet; any Monet will do, it need not be the one the
project was started on). Monet local finds no such project there, makes it, sends the Notes, builds them (the
first time takes minutes: every Note), and adds the folder's checks. From there it is step 2.

- **The checks came with the repository, and on this Monet they are this person's now.** Monet local adds the
  ones that are missing; it cannot change or remove one. If it says a check differs between the folder and the
  server, tell the user: they decide, in the canvas.
- **Without write access** to the repository: `gh repo fork <owner>/<project> --clone` instead, work on a branch
  (`git switch -c <what>`), and offer the work as a pull request: `gh pr create --fill`. Say in the pull request
  which issue it is for and that every Note is built and green (or what is not).
- **Do not push to somebody else's `main`** unless the brief or the owner says that is how they work.

## 4. Sharing it

- A friend who should work on it: `gh api -X PUT repos/<owner>/<project>/collaborators/<their login>` invites
  them (they accept by e-mail). Ask the user for the login; never guess one.
- Making it public (`gh repo edit --visibility public --accept-visibility-change-consequences`): only when the
  user says so in so many words. Look through the folder first for anything that should not be seen (addresses,
  names, prices, a key that got in by mistake) and tell them what you found.

## 5. When it goes wrong

- `git push` refused (non-fast-forward): somebody pushed. `git pull --rebase`, build, look, push again.
- `gh` says the token lacks a scope: the user runs `gh auth refresh -s repo` (their browser again).
- Monet local says a file "was changed here and on the server": the pull brought a Note the person also changed
  in the canvas. Look at both (`monet.py tool read_note …` and the file), write the one that keeps both, and
  start Monet local again with `--mine`.
- You are not sure what a command will do to their history: do not run it. Say what you see and ask.
