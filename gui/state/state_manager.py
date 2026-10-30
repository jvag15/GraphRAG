"""
StateManager — Single source of truth shared between GUI and backend processes.

Reads and writes data/gui_state.json relative to the project root.
Uses atomic write (tempfile + os.replace) to prevent corruption from
concurrent reads/writes by the GUI and batch_coordinator.py.

CRITICAL: StateManager.read() must never be called in the main/GUI thread
except at initialization. All runtime reads happen in QThread workers.
"""

import json
import os
import tempfile
from pathlib import Path

import psutil


class StateManager:
    """Read/write the shared gui_state.json file with atomic writes."""

    STATE_PATH = Path(__file__).parent.parent.parent / "data" / "gui_state.json"

    _DEFAULT_STATE: dict = {
        "ingestion": {
            "status": "idle",
            "pid": None,
            "pause_requested": False,
            "stop_requested": False,
            "session_number": 0,
            "batch_number": 0,
            "total_files_at_start": 0,
            "files_remaining": 0,
            "current_file": "",
            "current_stage": "",
            "active_since": None,
            "last_updated": None,
        },
        "query": {
            "last_session_id": None,
            "active": False,
            "pid": None,
        },
        "pruning": {
            "status": "idle",
            "pid": None,
            "document_id": "",
            "progress_pct": 0,
            "last_message": "",
            "prune_requests": [],
        },
    }

    @classmethod
    def read(cls) -> dict:
        """Read current state. Returns default state if file does not exist."""
        try:
            with open(cls.STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls._deep_copy_default()

    @classmethod
    def write(cls, state: dict) -> None:
        """Atomically write state using temp file + rename to prevent corruption.

        os.replace() is atomic on Linux — no partial writes possible.
        """
        cls.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        state["ingestion"]["last_updated"] = cls._utc_now()

        # Write to temp file first, then atomic rename
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            dir=str(cls.STATE_PATH.parent),
            prefix="gui_state_",
            delete=False
        ) as f:
            tmp_path = f.name
            try:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        os.replace(tmp_path, str(cls.STATE_PATH))

    @classmethod
    def set_pause_requested(cls, value: bool) -> None:
        """Set pause_requested flag. Backend polls this between documents."""
        state = cls.read()
        state["ingestion"]["pause_requested"] = value
        if value and state["ingestion"]["status"] == "running":
            state["ingestion"]["status"] = "paused"
        elif not value and state["ingestion"]["status"] == "paused":
            state["ingestion"]["status"] = "running"
        cls.write(state)

    @classmethod
    def set_stop_requested(cls, value: bool) -> None:
        """Set stop_requested flag. Backend flushes and exits cleanly."""
        state = cls.read()
        state["ingestion"]["stop_requested"] = value
        if value:
            state["ingestion"]["status"] = "stopping"
        cls.write(state)

    @classmethod
    def is_ingesting(cls) -> bool:
        """Return True if ingestion process is alive.

        Uses psutil.pid_exists(pid) to detect zombie locks. If the PID
        is dead, auto-clears the state and returns False.
        """
        try:
            state = cls.read()
            pid = state["ingestion"].get("pid")
            if pid is not None:
                if psutil.pid_exists(pid):
                    return True
                # Zombie detected — auto-clear
                cls._clear_ingestion_state()
                return False
            # Fallback to status check for pre-PID states
            return state["ingestion"]["status"] in ("running", "paused")
        except Exception:
            return False

    @classmethod
    def reset(cls) -> None:
        """Reset state to idle. Called after ingestion completes or stops."""
        state = cls.read()
        state["ingestion"]["status"] = "idle"
        state["ingestion"]["pid"] = None
        state["ingestion"]["pause_requested"] = False
        state["ingestion"]["stop_requested"] = False
        state["ingestion"]["current_file"] = ""
        state["ingestion"]["current_stage"] = ""
        state["ingestion"]["files_remaining"] = 0
        cls.write(state)

    # --- Pruning helpers ---

    @classmethod
    def is_pruning(cls) -> bool:
        """Return True if a pruning operation is currently running.

        Uses psutil.pid_exists(pid) to detect zombie locks. If the PID
        is dead, auto-clears the state and returns False.
        """
        try:
            state = cls.read()
            pid = state["pruning"].get("pid")
            if pid is not None:
                if psutil.pid_exists(pid):
                    return True
                # Zombie detected — auto-clear
                cls._clear_pruning_state()
                return False
            # Fallback to status check
            return state["pruning"]["status"] == "running"
        except Exception:
            return False

    @classmethod
    def is_system_busy(cls) -> bool:
        """Return True if ingesting, querying, or pruning.

        Used by mutual exclusion checks across all tabs to prevent
        conflicting operations from running simultaneously.
        """
        try:
            return cls.is_ingesting() or cls.is_pruning() or cls.read()["query"]["active"]
        except Exception:
            return False

    @classmethod
    def queue_prune(cls, document_id: str) -> None:
        """Append document_id to prune_requests array atomically."""
        state = cls.read()
        if document_id not in state["pruning"]["prune_requests"]:
            state["pruning"]["prune_requests"].append(document_id)
        cls.write(state)

    @classmethod
    def pop_prune_request(cls) -> str | None:
        """Atomically remove and return the first queued prune request.

        Backend calls this to consume the next document to prune.
        Returns None if the queue is empty.
        """
        state = cls.read()
        requests = state["pruning"]["prune_requests"]
        if not requests:
            return None
        document_id = requests.pop(0)
        state["pruning"]["prune_requests"] = requests
        cls.write(state)
        return document_id

    # --- Auto-cleanup helpers ---

    @classmethod
    def _clear_ingestion_state(cls) -> None:
        """Reset ingestion state to idle. Called after ingestion completes or on zombie detection."""
        state = cls.read()
        state["ingestion"]["status"] = "idle"
        state["ingestion"]["pid"] = None
        state["ingestion"]["pause_requested"] = False
        state["ingestion"]["stop_requested"] = False
        state["ingestion"]["current_file"] = ""
        state["ingestion"]["current_stage"] = ""
        state["ingestion"]["files_remaining"] = 0
        cls.write(state)

    @classmethod
    def _clear_pruning_state(cls) -> None:
        """Reset pruning state to idle. Called after pruning completes or on zombie detection."""
        state = cls.read()
        state["pruning"]["status"] = "idle"
        state["pruning"]["pid"] = None
        state["pruning"]["document_id"] = ""
        state["pruning"]["progress_pct"] = 0
        state["pruning"]["last_message"] = ""
        cls.write(state)

    # --- Private helpers ---

    @classmethod
    def _deep_copy_default(cls) -> dict:
        """Return a deep copy of the default state to prevent mutation."""
        return json.loads(json.dumps(cls._DEFAULT_STATE))

    @staticmethod
    def _utc_now() -> str:
        """Return ISO 8601 UTC timestamp string."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
