"""What the server keeps on its own disk: the accounts and the audit log (from Adam
Designer, which took it from Nerva). No database. Everything of a project lives in the
storage folder, not here: the place where Notes are run never sees this one.

Writes are atomic (tmp + rename), files 0600. Sync IO on purpose: tiny files, one process.
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_atomic(file: Path, text: str) -> None:
    tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, file)


class Store:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory).resolve()
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._users_file = self.dir / "users.json"
        self._log_file = self.dir / "log.jsonl"
        self._lock = threading.Lock()
        self.users: dict[str, dict] = json.loads(self._users_file.read_text()) if self._users_file.exists() else {}

    def save_user(self, user: dict) -> dict:
        with self._lock:
            self.users[user["id"]] = user
            write_atomic(self._users_file, json.dumps(self.users, indent=2))
        return user

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            self.users.pop(user_id, None)
            write_atomic(self._users_file, json.dumps(self.users, indent=2))

    def log(self, **event) -> None:
        with self._lock:
            fd = os.open(self._log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as fh:
                fh.write(json.dumps({"at": now(), **event}) + "\n")

    def tail(self, n: int = 200) -> list[dict]:
        if not self._log_file.exists():
            return []
        with self._lock:
            lines = self._log_file.read_text().splitlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
