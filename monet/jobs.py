"""Slow work done apart from the requests (issue #9): a render of a big assembly's animation takes minutes, longer
than the proxy waits for an answer, and done inside a request it held the server's other answers up.

A job runs in a process of its own (a pool of one: one render at a time on the whole server, each in a fresh
process, so its memory goes when it ends). A call answers at once: the job's progress while it runs, and the caller
asks again with the same arguments until the file is there. The same job asked for twice runs once; when too many
are waiting, a new one is refused with what is running."""
from __future__ import annotations

import atexit
import concurrent.futures as cf
import json
import multiprocessing
import threading
from pathlib import Path

WAITING = 4          # jobs in the queue (the running one counted) before a new one is refused
_guard = threading.Lock()
_pool: cf.ProcessPoolExecutor | None = None
_jobs: dict = {}     # key -> {"future", "progress": Path, "label"}


class Busy(Exception):
    """Too many jobs are waiting: the message says which one runs."""


def _executor() -> cf.ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = cf.ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1)
        atexit.register(_pool.shutdown, wait=False, cancel_futures=True)
    return _pool


def progress(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def state(key: str) -> dict | None:
    """{"state": "rendering" | "waiting", "done", "frames"} of a job in hand, {"state": "failed", "error"} of one that
    failed (said once, then forgotten, so it can be tried again), or None."""
    with _guard:
        job = _jobs.get(key)
        if not job:
            return None
        f = job["future"]
        if f.done():
            del _jobs[key]
            e = f.exception()
            return {"state": "failed", "error": str(e) or type(e).__name__} if e else None
        got = progress(job["progress"])
        return {"state": "rendering" if f.running() or got else "waiting", "done": got.get("done", 0),
                "frames": got.get("frames", job.get("frames", 0))}


def submit(key: str, fn, *args, progress_path: Path, label: str, frames: int = 0) -> dict:
    """Start `fn(*args)` in the job process unless the same job is in hand: its state either way."""
    with _guard:
        job = _jobs.get(key)
        if not (job and not job["future"].done()):
            live = [j for j in _jobs.values() if not j["future"].done()]
            if len(live) >= WAITING:
                now = next((j for j in live if j["future"].running()), live[0])
                p = progress(now["progress"])
                raise Busy(f"the server is rendering {now['label']} ({p.get('done', 0)}/{p.get('frames', '?')} frames) with "
                           f"{len(live) - 1} more waiting: try again in a minute")
            progress_path.unlink(missing_ok=True)
            _jobs[key] = {"future": _executor().submit(fn, *args), "progress": progress_path, "label": label, "frames": frames}
    return state(key) or {"state": "waiting", "done": 0, "frames": frames}


def wait(key: str, timeout: float | None = None) -> bool:
    """Until the job is done, or `timeout` seconds: whether it is done (it raises what the job raised)."""
    with _guard:
        job = _jobs.get(key)
    if not job:
        return True
    try:
        job["future"].result(timeout)
    except cf.TimeoutError:
        return False
    return True
