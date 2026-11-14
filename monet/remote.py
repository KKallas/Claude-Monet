"""The agent's line to the canvas the person has open (from Adam Designer's docs/15, without its `page`, and
since 2026-11-13 without its switch).

There was a switch here, remote control: the agent key opened nothing until the person switched it on, and it ended
after 15 idle minutes. Kaspar took it out (2026-11-13): the agent now runs on the person's own computer, started by
their own hand (Monet local, the terminal of the canvas), and a switch to let it in was one step too many. **The agent
key alone opens the agent's door.** What closes it is a new key (the canvas's Terminal → New key).

Every open canvas of the person dials `/w/<username>/api/remote/tab` and says what it shows. The agent's tools
`screen`, `goto` and `view` are questions to the page on screen (else the one heard from last): `{t: ask, id, what,
args}`, answered `{t: result, id, ok, json}`. The page answers these three by name and runs no code of the agent's:
what the agent changes goes through the server's tools and their rules, never as the person in their page. Everything
it changed is written down in the server's log (app.py, changed()).
"""
import asyncio
import concurrent.futures
import itertools
import json
import time
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketDisconnect

from .store import Store
from .workspace import Problem


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
    def __init__(self, store: Store):
        self.store = store
        self.tabs: list[Tab] = []
        self.waiting: dict[str, concurrent.futures.Future] = {}
        self.pictures: dict[str, bytes] = {}    # the last picture `view` took of each person's canvas
        self._seq = itertools.count(1)

    # ---- the pages ----------------------------------------------------------------
    async def serve(self, ws: WebSocket, user: dict) -> None:
        """One open canvas, for as long as it is open. Its user is checked (logged in, their own) by the route."""
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

    def _send(self, tab: Tab, message: dict) -> None:
        """From any thread."""
        coro = tab.ws.send_text(json.dumps(message))
        try:
            asyncio.run_coroutine_threadsafe(coro, tab.loop)
        except RuntimeError:        # that page's loop is gone
            coro.close()

    def ask(self, user: dict, what: str, args: dict, timeout: float = 30):
        """Ask the person's open canvas (from a worker thread, never the event loop): what it answers, as JSON."""
        tabs = self.tabs_of(user["id"])
        if not tabs:
            raise Problem(f"no canvas of {user.get('name') or user['username']} is open: ask them to open Monet in a browser "
                          "and leave the tab open (the other tools work without it)", 503)
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
