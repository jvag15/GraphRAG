"""
IngestionWorker — QThread that manages batch_coordinator.py as a subprocess.

Does NOT directly run Python ingestion code. Launches batch_coordinator.py
as a child process with the required memory environment (jemalloc, CUDA alloc),
monitors stdout/stderr in real-time, and emits log lines.

Pause/stop are cooperative: writes flags to StateManager. The backend
(batch_coordinator.py) polls these flags between documents.

CRITICAL: StateManager.reset() is called in finally block to clean state
after the process ends — even on crash.
"""

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from gui.state.state_manager import StateManager


class IngestionWorker(QThread):
    """Launch and monitor batch_coordinator.py subprocess in a background thread."""

    log_line = pyqtSignal(str)
    process_started = pyqtSignal()
    process_finished = pyqtSignal(int)  # exit code
    error = pyqtSignal(str)

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"

    def __init__(self) -> None:
        super().__init__()
        self._process: subprocess.Popen | None = None
        self._pause_requested = False
        self._stop_requested = False

    def run(self) -> None:
        """Launch batch_coordinator.py with required memory env vars."""
        env = os.environ.copy()
        env["LD_PRELOAD"] = "/usr/lib/libjemalloc.so"
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        # Snapshot the file count at start time for progress ratio
        staging = Path(
            env.get("HDD_BASE_PATH", "data/ingestion_pool")
        ) / "staging"
        total = len(list(staging.glob("*.pdf")) + list(staging.glob("*.PDF")))

        # Write initial state
        state = StateManager.read()
        state["ingestion"]["status"] = "running"
        state["ingestion"]["total_files_at_start"] = total
        state["ingestion"]["files_remaining"] = total
        state["ingestion"]["session_number"] = state["ingestion"].get("session_number", 0) + 1
        state["ingestion"]["pause_requested"] = False
        state["ingestion"]["stop_requested"] = False
        StateManager.write(state)

        try:
            self._process = subprocess.Popen(
                [str(self.VENV_PYTHON), "ingestion_mouth/batch_coordinator.py"],
                cwd=str(self.PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            # Record PID for liveness tracking and zombie-lock detection
            state = StateManager.read()
            state["ingestion"]["pid"] = self._process.pid
            StateManager.write(state)
            self.process_started.emit()

            # Stream output in real-time
            if self._process.stdout:
                for line in self._process.stdout:
                    self.log_line.emit(line.rstrip())

            self._process.wait()
            self.process_finished.emit(self._process.returncode)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            # Always reset state — even on crash
            StateManager._clear_ingestion_state()

    @pyqtSlot()
    def request_pause(self) -> None:
        """Write pause flag. Backend catches it between documents."""
        StateManager.set_pause_requested(True)

    @pyqtSlot()
    def request_resume(self) -> None:
        """Clear pause flag to resume ingestion."""
        StateManager.set_pause_requested(False)

    @pyqtSlot()
    def request_stop(self) -> None:
        """Write stop flag. Backend flushes and exits cleanly."""
        StateManager.set_stop_requested(True)