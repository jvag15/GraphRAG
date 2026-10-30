#!/usr/bin/env python3
"""PruningWorker — QThread that launches prune_document.py as a subprocess.

Streams stdout line-by-line, parses step progress markers, and updates
gui_state.json via StateManager. Never raises an unhandled exception
inside run().

# Phase 2 — Pruning Infrastructure
# GraphRAG Engine — Legal Discovery & Knowledge Engine
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from gui.state.state_manager import StateManager

PROJECT_ROOT = Path(__file__).parent.parent.parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"


class PruningWorker(QThread):
    """Launches prune_document.py as an isolated subprocess. Streams stdout."""

    log_line = pyqtSignal(str)
    """Emitted for every line of stdout / stderr from the subprocess."""

    progress_updated = pyqtSignal(int)
    """Emitted with progress percentage (0–100) as steps complete."""

    prune_complete = pyqtSignal(str, bool)
    """Emitted on finish: (document_id, success)."""

    def __init__(self, document_id: str) -> None:
        """Initialise the worker for a specific document.

        Args:
            document_id: PDF filename to prune.
        """
        super().__init__()
        self.document_id = document_id
        self._process: subprocess.Popen | None = None

    def run(self) -> None:  # noqa: D102
        """Execute prune_document.py in a subprocess. Never raises."""
        try:
            state = StateManager.read()
            state["pruning"]["status"] = "running"
            state["pruning"]["document_id"] = self.document_id
            state["pruning"]["progress_pct"] = 0
            state["pruning"]["last_message"] = ""
            StateManager.write(state)
        except Exception:
            pass  # StateManager failure should not block pruning

        success = False
        try:
            self._process = subprocess.Popen(
                [str(VENV_PYTHON), "prune_document.py", self.document_id],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Never use shell=True — document_id comes from filesystem
                # listing, but defence in depth requires list-form Popen.
            )
            # Record PID for liveness tracking and zombie-lock detection
            state = StateManager.read()
            state["pruning"]["pid"] = self._process.pid
            StateManager.write(state)

            # Map step markers to progress percentages
            step_map = {
                "Step 1/4": 10,
                "Step 2/4": 35,
                "Step 3/4": 60,
                "Step 4/4": 85,
                "Complete": 100,
            }

            for line in self._process.stdout:
                line = line.rstrip()
                self.log_line.emit(line)

                for marker, pct in step_map.items():
                    if marker in line:
                        self.progress_updated.emit(pct)
                        try:
                            state = StateManager.read()
                            state["pruning"]["progress_pct"] = pct
                            state["pruning"]["last_message"] = line
                            StateManager.write(state)
                        except Exception:
                            pass
                        break

            self._process.wait()
            success = self._process.returncode == 0

        except Exception as exc:
            self.log_line.emit(f"[PRUNE][FATAL] Worker exception: {exc}")

        finally:
            try:
                StateManager._clear_pruning_state()
                # Override with completion status for UI feedback
                state = StateManager.read()
                state["pruning"]["status"] = "complete" if success else "error"
                state["pruning"]["progress_pct"] = 100 if success else 0
                StateManager.write(state)
            except Exception:
                pass  # Best-effort state update on cleanup

            self.prune_complete.emit(self.document_id, success)
