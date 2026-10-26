import tempfile
import uuid
from pathlib import Path

import pytest

from monet import prebuild
from monet.app import ROOT
from monet.build import FILES, build, zipped
from monet.workspace import Workspaces


@pytest.fixture(scope="session", autouse=True)
def templates_built():
    """As the image does before anyone comes: a new workspace's templates open built."""
    prebuild.main([str(ROOT / "notes")])


@pytest.fixture(scope="session")
def workspaces(tmp_path_factory):
    return Workspaces(tmp_path_factory.mktemp("storage"), ROOT / "notes", ROOT / "profiles")


@pytest.fixture(scope="session")
def ws(workspaces):
    """One workspace for the whole run: it holds a copy of every template, built."""
    return workspaces.of(str(uuid.uuid4()), "tests")


def built_files(where: Path, name: str, exports=()) -> dict:
    """What the agent's build of a Note leaves, built from the files in `where` (as monet.py build does)."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / name
        build(where, name, out, exports)
        return {f: (out / f).read_bytes() for f in FILES if (out / f).exists()}


def agent_builds(p, name: str, exports=(), version: int | None = None) -> dict:
    """The agent builds a Note on its own computer and uploads it: the server's answer."""
    where = p.dir if version is None else p._vpath(version)
    return p.accept_build(name, built_files(where, name, exports), version)


def build_zip(p, name: str, exports=()) -> bytes:
    """The same build, as the zip an upload carries."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / name
        build(p.dir, name, out, exports)
        return zipped(out)
