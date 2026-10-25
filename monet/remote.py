"""Remote control (from Adam Designer, its docs/15): the person lets their own agent in, for as long as something
is happening, and the agent can see the canvas they have open and take it somewhere.

The agent key opens nothing until the person switches remote control on, in their canvas. It ends by itself:
after 15 minutes in which neither the person did anything in the canvas nor the agent asked anything, when they
log out, and when their password is changed or reset. The same key works again when it is switched on again, so a
connector set up once keeps working. MCP stays connected while it is off: `initialize` and `tools/list` answer,
every call says in words that it is off.

While it is on, every open canvas of the person dials `/w/<username>/api/remote/tab` and says what it shows. The
agent's tools `screen`, `goto` and `view` are questions to the page on screen (else the one heard from last):
`{t: ask, id, what, args}`, answered `{t: result, id, ok, json}`. The page answers these three by name and runs no code
of the agent's: what the agent changes goes through the server's tools and their rules, never as the person in their
page. Everything it changed is written down.
"""
import asyncio
import concurrent.futures
import itertools
import json
import time
from collections import deque
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketDisconnect

from .store import Store, now
from .workspace import Problem

IDLE = 15 * 60      # seconds it stays on with nothing happening
GONE = ("this agent link opens nothing now: remote control is off (the person switched it off or logged out, or nothing "
        "happened for 15 minutes and it ended by itself). Ask them to switch it on again in their canvas, under Connect "
        "your agent: the same link then works again")


@dataclass(eq=False)
class Tab:
    """An open canvas of the person, which their agent may look at and drive."""
    ws: WebSocket
    user: str
    loop: asyncio.AbstractEventLoop
    project: str = ""
    note: str = ""
    room: str = ""
    hidden: bool = True
    at: float = field(default_factory=time.time)


class Remote:
    def __init__(self, store: Store, idle: float = IDLE):
        self.store, self.idle = store, idle
        self.tabs: list[Tab] = []
        self.waiting: dict[str, concurrent.futures.Future] = {}
        self.recent: dict[str, deque] = {}      # what each person's agent changed lately: for their eye, not kept over a restart
        self.pictures: dict[str, bytes] = {}    # the last picture `view` took of each person's canvas
        self._seq = itertools.count(1)
        self._kept: dict[str, float] = {}       # when an account was last written for this: once a minute is enough
        self._told: dict[str, float] = {}       # when its pages were last told how long is left

    # ---- the switch, and how long it holds ----------------------------------------
    def live(self, user: dict) -> bool:
        """Is this person's remote control on, still? Asked before the key opens anything."""
        a = user.get("agent") or {}
        if not a.get("on"):
            return False
        if a.get("session", 1) != (user.get("session") or 1):      # the login it was switched on in is over
            self.stop(user, "login")
            return False
        if time.time() >= a.get("until", 0):
            self.stop(user, "idle")
            return False
        return True

    def start(self, user: dict, who: str = "") -> None:
        had = user.get("agent") or {}
        user["agent"] = {"on": True, "until": time.time() + self.idle, "session": user.get("session") or 1, "seen": had.get("seen")}
        self.store.save_user(user)
        self._kept[user["id"]] = time.time()
        self.store.log(type="remote-on", user=user["username"], who=who or user["username"])

    def stop(self, user: dict, why: str, who: str = "") -> None:
        """why: you · idle (15 minutes of nothing) · logout · login (the password changed or was reset)."""
        a = user.get("agent") or {}
        if not a.get("on"):
            return
        user["agent"] = {**a, "on": False, "off": {"at": now(), "why": why}}
        self.store.save_user(user)
        self.store.log(type="remote-off", user=user["username"], who=who or user["username"], why=why)
        for t in [t for t in self.tabs if t.user == user["id"]]:
            self._send(t, None)
            self.tabs.remove(t)

    def touch(self, user: dict, agent: bool = False) -> None:
        """Something happened: the person did something in the canvas, or their agent asked something. The time
        starts again; their pages are told (they count it down)."""
        a = user.get("agent") or {}
        if not a.get("on"):
            return
        t = time.time()
        a["until"] = t + self.idle
        if agent:
            a["seen"] = now()
        if t - self._kept.get(user["id"], 0) > 60:
            self._kept[user["id"]] = t
            self.store.save_user(user)
        if t - self._told.get(user["id"], 0) > min(2, self.idle / 10):      # a burst of calls is one telling, not fifty
            self._told[user["id"]] = t
            for tab in self.tabs_of(user["id"]):
                self._send(tab, {"t": "left", "ms": round(self.idle * 1000)})

    def note(self, user: dict, what: str = "") -> None:
        """The agent was here, and what it changed (when it changed something)."""
        self.touch(user, agent=True)
        if what:
            self.recent.setdefault(user["id"], deque(maxlen=30)).appendleft({"at": now(), "what": what[:200]})

    def view(self, user: dict) -> dict:
        on = self.live(user)
        a = user.get("agent") or {}
        return {"on": on, "left": round(max(0.0, a.get("until", 0) - time.time()) * 1000) if on else 0, "idle": round(self.idle * 1000),
                "off": None if on else a.get("off"), "seen": a.get("seen"), "tabs": len(self.tabs_of(user["id"])),
                "recent": list(self.recent.get(user["id"], [])) if on else []}

    async def sweep(self) -> None:
        """Nobody has to ask for it to end: a switch that ran out is off, its pages hung up on, within 15 s."""
        while True:
            await asyncio.sleep(15)
            for u in list(self.store.users.values()):
                if (u.get("agent") or {}).get("on"):
                    self.live(u)

    # ---- the pages ----------------------------------------------------------------
    async def serve(self, ws: WebSocket, user: dict) -> None:
        """One open canvas, for as long as it is open. Its user is checked (logged in, theirs, switched on) by the route."""
        await ws.accept()
        tab = Tab(ws, user["id"], asyncio.get_running_loop())
        self.tabs.append(tab)
        try:
            while True:
                try:
                    m = json.loads(await ws.receive_text())
                except (ValueError, TypeError):
                    continue
                if not isinstance(m, dict):
                    continue
                if m.get("t") == "state":
                    tab.project, tab.note, tab.room = str(m.get("project") or ""), str(m.get("note") or ""), str(m.get("room") or "")
                    tab.hidden, tab.at = bool(m.get("hidden")), time.time()
                elif m.get("t") == "alive":      # the person did something (a click, a key): the page's heartbeat is not that
                    u = self.store.users.get(tab.user)
                    if u and self.live(u):
                        self.touch(u)
                elif m.get("t") == "result":
                    fut = self.waiting.get(str(m.get("id")))
                    if fut and not fut.done():
                        fut.set_result((bool(m.get("ok")), m.get("json")))
        except WebSocketDisconnect:
            pass
        finally:
            if tab in self.tabs:
                self.tabs.remove(tab)

    def tabs_of(self, user_id: str) -> list[Tab]:
        """The one on screen first (a covered tab draws no frames), then the one heard from last."""
        return sorted((t for t in self.tabs if t.user == user_id), key=lambda t: (t.hidden, -t.at))

    def pages(self, user_id: str) -> list[dict]:
        return [{"project": t.project or None, "note": t.note or None, "room": t.room or None, "on_screen": not t.hidden} for t in self.tabs_of(user_id)]

    def _send(self, tab: Tab, message: dict | None) -> None:
        """From any thread. None hangs up: remote control was switched off."""
        coro = tab.ws.close(code=4001, reason="remote control was switched off") if message is None else tab.ws.send_text(json.dumps(message))
        try:
            asyncio.run_coroutine_threadsafe(coro, tab.loop)
        except RuntimeError:        # that page's loop is gone
            coro.close()

    def ask(self, user: dict, what: str, args: dict, timeout: float = 30):
        """Ask the person's open canvas (from a worker thread, never the event loop): what it answers, as JSON."""
        tabs = self.tabs_of(user["id"])
        if not tabs:
            raise Problem(f"no canvas of {user.get('name') or user['username']} is open with remote control on: ask them to "
                          "open Monet in a browser and leave the tab open (the other tools work without it)", 503)
        ask_id = f"{int(time.time() * 1000):x}-{next(self._seq)}"
        fut = self.waiting[ask_id] = concurrent.futures.Future()
        self._send(tabs[0], {"t": "ask", "id": ask_id, "what": what, "args": args})
        try:
            ok, text = fut.result(timeout)
        except concurrent.futures.TimeoutError:
            raise Problem(f"the canvas did not answer in {round(timeout)} s: is it busy, or its tab asleep in the background?", 504) from None
        finally:
            self.waiting.pop(ask_id, None)
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            value = text
        if not ok:
            raise Problem(f"the canvas could not: {value if isinstance(value, str) else json.dumps(value)}", 422)
        return value
