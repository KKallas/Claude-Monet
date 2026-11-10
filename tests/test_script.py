"""The skill's script from a shell: a server that cannot be reached is said in one line, never a traceback, never the
agent link."""
import os
import socket
import subprocess
import sys

from monet.app import ROOT

SCRIPT = ROOT / "skill/monet/scripts/monet.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_server_that_cannot_be_reached_is_one_line_and_no_key():
    url = f"http://127.0.0.1:{free_port()}/w/SECRET-AGENT-KEY-123"
    env = {**os.environ, "MONET_URL": url, "MONET_RETRIES": "0,0"}
    proc = subprocess.run([sys.executable, str(SCRIPT), "status"], env=env, capture_output=True, text=True, timeout=60)
    said = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "Traceback" not in said and "SECRET-AGENT-KEY" not in said
    assert "cannot reach 127.0.0.1" in said and "run the same command again" in said
    assert said.count("trying again") == 2
