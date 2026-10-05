"""The runner, as a service: the one place Notes are run when Monet is online.

    python -m monet.buildd          listens on :8081, inside the instance's own network only

A Note is code, and whoever may send one may run anything in the process that builds it. So
that process lives in a container of its own, which is given the working files (it has to
read the Notes and write the builds) and nothing else: not the accounts, not the session
secret, no way out to the internet. The web app asks it to build and reads back the result.
"""
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from .note import NAME_RE
from .workspace import EXPORTS, run_build_here

STORAGE = Path(os.environ.get("MONET_STORAGE", "storage")).resolve()


async def build(request):
    body = await request.json()
    project, out, note = Path(str(body.get("dir", ""))).resolve(), Path(str(body.get("out", ""))).resolve(), str(body.get("note", ""))
    exports = tuple(e for e in body.get("exports") or [] if e in EXPORTS)
    # only the working files, and only a Note by a Note's name
    if not NAME_RE.match(note) or STORAGE not in project.parents or STORAGE not in out.parents or not (project / f"{note}.py").is_file():
        return JSONResponse({"error": "not a Note of this storage"}, 400)
    return JSONResponse(await run_in_threadpool(run_build_here, project, note, out, exports))


app = Starlette(routes=[Route("/build", build, methods=["POST"]), Route("/healthz", lambda _r: JSONResponse({"ok": True}))])


def main():
    uvicorn.run(app, host=os.environ.get("MONET_HOST", "0.0.0.0"), port=int(os.environ.get("RUNNER_PORT", "8081")), log_level="warning")


if __name__ == "__main__":
    main()
