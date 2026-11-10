"""`meals serve`, `status` and `stop`, the commands behind start.bat / stop.bat."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _meals(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "meals.cli", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_serve_status_stop(tmp_path: Path) -> None:
    port = _free_port()
    env = {**os.environ, "MEALS_DATA_DIR": str(tmp_path), "MEALS_PORT": str(port)}
    assert _meals(env, "status").returncode == 1
    assert "Not running" in _meals(env, "stop").stdout

    server = subprocess.Popen(
        [sys.executable, "-m", "meals.cli", "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if _meals(env, "status").returncode == 0:
                break
            time.sleep(0.2)
        status = _meals(env, "status")
        assert status.returncode == 0, status.stdout
        assert f"PID {server.pid}" in status.stdout

        # A second start leaves the running server and its PID file alone.
        again = _meals(env, "serve")
        assert again.returncode == 0
        assert "Already running" in again.stdout
        assert (tmp_path / "meals.pid").read_text(encoding="utf-8") == str(server.pid)

        assert "Stopped" in _meals(env, "stop").stdout
        server.wait(timeout=10)
        assert not (tmp_path / "meals.pid").exists()
        assert _meals(env, "status").returncode == 1
    finally:
        if server.poll() is None:
            server.kill()
