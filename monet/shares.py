"""Share links: one motion study of a project, to watch, for anyone who has the link (GitHub only to write a note).

A link is /s/<token>; it holds the study by its id (Project.study_id), so renaming the study keeps it. Links are found
by the sha256 of their token; the token is kept too, so the person sees their link again in the Share dialog
(Kaspar, 2026-11-24: "if I have forgotten I get it from there"). This file is data/shares.json, beside the accounts
and the session secret, never in storage/; links made before then were kept as the sha alone. A new link for a study
closes the one before; the person can close it too. What a link opens is the study's assembly as built, played: never
a source, a check or another Note (the share door in app.py). Notes about it go to GitHub, as issues the viewer writes
there themselves: nothing a viewer says is kept here.
"""
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path

from .store import now, write_atomic

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,40}$")


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Shares:
    def __init__(self, directory: str | Path):
        self.file = Path(directory) / "shares.json"
        self._lock = threading.Lock()
        self.links: dict[str, dict] = json.loads(self.file.read_text()) if self.file.exists() else {}

    def _write(self) -> None:
        write_atomic(self.file, json.dumps(self.links, indent=1))

    def make(self, user_id: str, project: str, study: str) -> str:      # study: its id
        """A new link to a study: the token, to be shown once. The study's link before it stops working."""
        token = secrets.token_urlsafe(18)
        with self._lock:
            self._drop(user_id, project, study)
            self.links[_key(token)] = {"user": user_id, "project": project, "study": study, "made": now(), "token": token}
            self._write()
        return token

    def _drop(self, user_id: str, project: str, study: str) -> bool:
        gone = [k for k, s in self.links.items() if (s["user"], s["project"], s["study"]) == (user_id, project, study)]
        for k in gone:
            del self.links[k]
        return bool(gone)

    def close(self, user_id: str, project: str, study: str) -> bool:
        with self._lock:
            gone = self._drop(user_id, project, study)
            if gone:
                self._write()
        return gone

    def close_all(self, user_id: str, project: str | None = None) -> None:
        """A user, or a project of theirs, gone: their links with them."""
        with self._lock:
            gone = [k for k, s in self.links.items() if s["user"] == user_id and (project is None or s["project"] == project)]
            for k in gone:
                del self.links[k]
            if gone:
                self._write()

    def of(self, user_id: str, project: str, study: str) -> dict | None:
        """Whether a study is shared, since when, and its token (none for a link made when only the sha was kept)."""
        return next(({"made": s["made"], "token": s.get("token")} for s in self.links.values()
                     if (s["user"], s["project"], s["study"]) == (user_id, project, study)), None)

    def find(self, token) -> dict | None:
        token = str(token or "")
        if not TOKEN_RE.match(token):
            return None
        return self.links.get(_key(token))
