"""How much of the Claude plan is used: the bars over the canvas's terminal (Session, Week, and a model's own weekly
limit, such as Fable's). Nothing here asks anybody: it reads what Claude Code itself already knows, on this computer.

Two sources, the fresher wins:

- **Claude Code's status line.** Monet local starts Claude Code with this file as its status line (when the person has
  none of their own). After every reply Claude Code gives it the session's JSON on stdin; its `rate_limits` (the 5-hour
  session and the 7-day week, each with `used_percentage` and `resets_at`) are kept in ~/.cache/monet/usage.json, and
  one short line is printed for Claude Code to show.
- **What Claude Code fetched for /usage**, kept in ~/.claude.json (`cachedUsageUtilization`): the same two, and the
  weekly limit of one model (`weekly_scoped`, e.g. Fable). Only as fresh as the last time Claude Code fetched it.

    python3 usage.py          as a status line: the JSON on stdin
    python3 usage.py --show   what is known now, as JSON
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

KEPT = Path(os.environ.get("MONET_CACHE") or Path.home() / ".cache" / "monet") / "usage.json"
NAMES = {"five_hour": "session", "seven_day": "week", "session": "session", "weekly_all": "week"}
LABELS = {"session": "Session", "week": "Week"}


def claude_json() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()) / ".claude.json"


def _epoch(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def keep(session: dict, now: float | None = None) -> str:
    """The status line: the session's rate limits kept for Monet local, and the line Claude Code shows."""
    limits = session.get("rate_limits") or {}
    if isinstance(limits, dict) and limits:
        KEPT.parent.mkdir(parents=True, exist_ok=True)
        tmp = KEPT.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": now or time.time(), "rate_limits": limits}))
        os.replace(tmp, KEPT)
    bars = read(now)
    return " · ".join(f"{b['label']} {round(b['pct'])}%" for b in bars.values()) or (session.get("model") or {}).get("display_name", "")


def read(now: float | None = None) -> dict:
    """What is known now, by name: {session|week|<model>: {label, pct, resets (epoch s), at (epoch s, when it was so)}}.
    A window whose reset has passed is left out: what it said is no longer so."""
    now = now or time.time()
    bars: dict = {}

    def put(name, label, pct, resets, at):
        if pct is None or resets <= now or (name in bars and bars[name]["at"] >= at):
            return
        bars[name] = {"label": label, "pct": max(0.0, float(pct)), "resets": resets, "at": at}

    try:
        kept = json.loads(KEPT.read_text())
    except (OSError, ValueError):
        kept = {}
    for key, w in (kept.get("rate_limits") or {}).items():
        if isinstance(w, dict) and key != "spend_limit":
            name = NAMES.get(key, key)
            put(name, LABELS.get(name, key.replace("_", " ")), w.get("used_percentage"), _epoch(w.get("resets_at")), float(kept.get("at") or 0))
    try:
        cached = json.loads(claude_json().read_text()).get("cachedUsageUtilization") or {}
    except (OSError, ValueError):
        cached = {}
    at = float(cached.get("fetchedAtMs") or 0) / 1000
    for L in (cached.get("utilization") or {}).get("limits") or []:
        if not isinstance(L, dict):
            continue
        model = (((L.get("scope") or {}).get("model") or {}).get("display_name") or "") if isinstance(L.get("scope"), dict) else ""
        name = model.lower() if L.get("kind") == "weekly_scoped" and model else NAMES.get(L.get("kind"))
        if name:
            put(name, model or LABELS[name], L.get("percent"), _epoch(L.get("resets_at")), at)
    order = ["session", "week"]
    return dict(sorted(bars.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 2, kv[0])))


if __name__ == "__main__":
    if "--show" in sys.argv:
        print(json.dumps(read(), indent=1))
    else:
        try:
            print(keep(json.loads(sys.stdin.read() or "{}")))
        except ValueError:
            print("")
