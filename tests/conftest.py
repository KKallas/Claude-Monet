import uuid

import pytest

from monet.workspace import Workspaces
from monet.app import ROOT


@pytest.fixture(scope="session")
def workspaces(tmp_path_factory):
    return Workspaces(tmp_path_factory.mktemp("storage"), ROOT / "notes", ROOT / "profiles")


@pytest.fixture(scope="session")
def ws(workspaces):
    """One workspace for the whole run: it holds a copy of every template, and builds are cached in it."""
    return workspaces.of(str(uuid.uuid4()), "tests")
