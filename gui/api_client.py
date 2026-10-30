from __future__ import annotations
import os
import httpx
from PyQt6.QtCore import QThread, pyqtSignal

API_BASE_URL: str = os.environ.get("GRAPHRAG_API_URL", "http://127.0.0.1:8000")


class HealthCheckWorker(QThread):
    status_changed = pyqtSignal(bool)

    def run(self) -> None:
        try:
            response = httpx.get(f"{API_BASE_URL}/health", timeout=5.0)
            self.status_changed.emit(response.status_code == 200)
        except Exception:
            self.status_changed.emit(False)


class QueryWorker(QThread):
    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, query: str, session_id: str | None = None) -> None:
        super().__init__()
        self.query = query
        self.session_id = session_id

    def run(self) -> None:
        payload = {"query": self.query}
        if self.session_id is not None:
            payload["session_id"] = self.session_id

        try:
            response = httpx.post(
                f"{API_BASE_URL}/query",
                json=payload,
                timeout=120.0
            )
            response.raise_for_status()
            self.response_ready.emit(response.json())
        except httpx.TimeoutException:
            self.error_occurred.emit(
                "Request timed out after 120s. The model may still be processing."
            )
        except httpx.ConnectError:
            self.error_occurred.emit(
                "Cannot connect to GraphRAG API. Is the server running on port 8000?"
            )
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {str(e)}")