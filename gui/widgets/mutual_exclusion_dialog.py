"""
MutualExclusionDialog — Modal dialog shown when a user action conflicts with
an ongoing system operation (ingestion, query, or pruning).

The exact "ingesting" message is a hard requirement from the specification:
  "Ingestion is currently taking place.
   To Send a query kindly pause or stop the ingestion process."

Do NOT paraphrase this text for the "ingesting" key.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal


class MutualExclusionDialog(QDialog):
    """Context-aware conflict dialog.

    Shown when the user attempts an action that conflicts with a currently
    running system operation. The message and available buttons depend on
    the conflict_reason:

    - "ingesting": Stop/Pause buttons available, exact spec string shown.
    - "querying":  Only Cancel available — wait for query to finish.
    - "pruning":   Only Cancel available — wait for prune to finish.
    """

    action_stop = pyqtSignal()
    action_pause = pyqtSignal()

    MESSAGES: dict[str, str] = {
        "ingesting": (
            "Ingestion is currently taking place.\n"
            "To Send a query kindly pause or stop the ingestion process."
        ),
        "querying": (
            "A query is currently being processed.\n"
            "Please wait for the response before pruning documents."
        ),
        "pruning": (
            "A document pruning operation is in progress.\n"
            "Please wait for it to complete before submitting a query."
        ),
    }

    def __init__(self, conflict_reason: str, parent=None) -> None:
        """Initialise dialog with context-aware message and buttons.

        Args:
            conflict_reason: One of "ingesting", "querying", or "pruning".
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Operation Conflict")
        self.setFixedWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Context-aware message
        message = self.MESSAGES.get(
            conflict_reason,
            "Another operation is currently in progress.\nPlease wait before retrying.",
        )
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()

        # Show Stop/Pause only for ingestion conflicts
        if conflict_reason == "ingesting":
            stop_btn = QPushButton("Stop Ingestion")
            stop_btn.setObjectName("btn_stop")
            stop_btn.clicked.connect(self._on_stop)

            pause_btn = QPushButton("Pause Ingestion")
            pause_btn.setObjectName("btn_pause")
            pause_btn.clicked.connect(self._on_pause)

            btn_row.addWidget(stop_btn)
            btn_row.addWidget(pause_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_stop(self) -> None:
        """Emit stop signal and close dialog."""
        self.action_stop.emit()
        self.accept()

    def _on_pause(self) -> None:
        """Emit pause signal and close dialog."""
        self.action_pause.emit()
        self.accept()