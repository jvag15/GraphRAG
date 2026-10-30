"""
ServerManager — Manages the FastAPI query server (port 8000) lifecycle.

Provides:
  - is_port_bound(port):  TCP connect check — no subprocess, no nvidia-smi parse.
  - ensure_running():     Starts uvicorn if port 8000 is not bound.
  - get_pid():            Returns the PID of the running server process, or None.
  - shutdown():           Terminates the server process and kills port occupants.

All subprocess calls use list-form Popen (never shell=True).
The server is launched detached (start_new_session=True) so it survives
GUI restarts without requiring re-launch.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"


def is_port_bound(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently bound by any process.

    Uses socket.connect_ex with a short timeout. Returns True if the
    port is accepting connections, False otherwise.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except OSError:
        return False
    finally:
        sock.close()


class ServerManager:
    """Manages the FastAPI query server lifecycle from the GUI.

    The server is started as a detached subprocess so it continues running
    even if the GUI is restarted. The GUI only checks whether port 8000 is
    bound; it does not track the process directly.
    """

    _server_process: subprocess.Popen | None = None

    @classmethod
    def ensure_running(cls) -> bool:
        """Ensure the FastAPI query server is running on port 8000.

        Returns:
            True if the server was already running (port was bound).
            False if the server was just launched (HealthCheckWorker will poll).

        Steps:
            1. Check if port 8000 is bound — if yes, return True.
            2. Kill any ghost processes on port 8000 (fuser -k).
            3. Launch uvicorn as a detached subprocess.
            4. Return False — caller should wait for HealthCheckWorker to confirm.
        """
        if is_port_bound(8000):
            return True

        # Kill any ghost processes holding port 8000
        try:
            subprocess.run(
                ["sudo", "fuser", "-k", "8000/tcp"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass  # fuser may fail if no process holds the port — that's fine

        # Also kill any lingering llama_cpp server on port 8080
        # (VRAM mutual exclusion — these two servers must not run simultaneously)
        try:
            subprocess.run(
                ["sudo", "fuser", "-k", "8080/tcp"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

        # Launch uvicorn detached from the GUI process group
        try:
            cls._server_process = subprocess.Popen(
                [
                    str(VENV_PYTHON), "-m", "uvicorn",
                    "src.api.fastapi_service:app",
                    "--host", "0.0.0.0",
                    "--port", "8000",
                ],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # Detach from GUI process group
            )
        except Exception:
            return False

        return False

    @classmethod
    def get_pid(cls) -> int | None:
        """Return the PID of the server process launched by this manager.

        Returns None if the server was already running (not launched by us)
        or if no server process is tracked.
        """
        if cls._server_process is not None:
            return cls._server_process.pid
        return None

    @classmethod
    def shutdown(cls) -> None:
        """Terminate the server process and kill any remaining port occupants."""
        if cls._server_process is not None:
            try:
                cls._server_process.terminate()
                cls._server_process.wait(timeout=5)
            except Exception:
                try:
                    cls._server_process.kill()
                except Exception:
                    pass
            cls._server_process = None

        # Ensure port 8000 is freed
        try:
            subprocess.run(
                ["sudo", "fuser", "-k", "8000/tcp"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
