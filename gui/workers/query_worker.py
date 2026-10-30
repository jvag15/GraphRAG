"""
QueryWorker — QThread for HTTP POST to FastAPI query server on port 8000.

The ONLY HTTP call in the entire GUI application. All ingestion control,
state tracking, hardware telemetry, and filesystem monitoring operate
through direct OS-level interfaces — not HTTP.

Includes mutual exclusion check: DO NOT submit query if
StateManager.is_ingesting() returns True. The caller (QueryTab) is
responsible for showing the MutualExclusionDialog before starting this worker.

All HTTP calls run in this QThread — never in the GUI thread.
"""

import httpx
from PyQt6.QtCore import QThread, pyqtSignal

API_BASE_URL = "http://127.0.0.1:8000"


class QueryWorker(QThread):
    """Send query to FastAPI server in a background thread."""

    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        query: str,
        session_id: str | None = None,
        model_mode: str = "local",
    ) -> None:
        super().__init__()
        self.query = query
        self.session_id = session_id
        self.model_mode = model_mode  # "local" | "sonnet" | "gpt-mini"

    def run(self) -> None:
        """Execute HTTP POST to /query endpoint. Emits result via signal."""
        try:
            payload: dict = {"query": self.query, "model_mode": self.model_mode}
            if self.session_id:
                payload["session_id"] = self.session_id
            response = httpx.post(
                f"{API_BASE_URL}/query",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            self.response_ready.emit(response.json())
        except httpx.ConnectError:
            self.error_occurred.emit(
                "Cannot connect to query server on port 8000. "
                "Start the server with: uvicorn src.api.fastapi_service:app --port 8000"
            )
        except httpx.TimeoutException:
            self.error_occurred.emit(
                "Query timed out after 120 seconds. The server may be overloaded."
            )
        except httpx.HTTPStatusError as e:
            self.error_occurred.emit(
                f"Server returned {e.response.status_code}: {e.response.text[:200]}"
            )
        except Exception as e:
            self.error_occurred.emit(str(e))
