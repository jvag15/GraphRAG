#!/usr/bin/env python3
"""KnowledgeTab — Knowledge management interface with document pruning.

Lists archived documents in a table. Provides per-row Prune action that
delegates to PruningWorker subprocess. All operations are non-blocking.

# Phase 2 — Granular Graph Pruning
# GraphRAG Engine — Legal Discovery & Knowledge Engine
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.workers.pruning_worker import PruningWorker
from gui.state.state_manager import StateManager

HDD_BASE = Path(
    os.environ.get(
        "HDD_BASE_PATH",
        "/mnt/parameter-archives/GraphRAG-Ingestion-DB",
    )
)
ARCHIVE_DIR = HDD_BASE / "archive"
PRUNED_DIR = HDD_BASE / "pruned"


class ArchiveLoaderWorker(QThread):
    """Reads archive/ directory asynchronously. Never blocks the GUI thread."""

    data_ready = pyqtSignal(list)
    """Emits list of (filename, size_bytes, modified_timestamp)."""

    def run(self) -> None:  # noqa: D102
        rows = []
        try:
            for p in sorted(ARCHIVE_DIR.glob("*.pdf")) + sorted(
                ARCHIVE_DIR.glob("*.PDF")
            ):
                stat = p.stat()
                rows.append((p.name, stat.st_size, stat.st_mtime))
        except Exception:
            pass  # Return empty list if directory inaccessible
        self.data_ready.emit(rows)


class KnowledgeTab(QWidget):
    """Tab 3: Knowledge Management.

    Lists archived documents. Provides per-row Prune action.
    All pruning delegated to PruningWorker subprocess.
    """

    prune_conflict = pyqtSignal(str)
    """Emitted when prune is blocked — reason string (ingesting/querying/pruning)."""

    def __init__(self, parent=None) -> None:
        """Initialise the knowledge tab.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._active_worker: PruningWorker | None = None
        self._build_ui()
        self._setup_watcher()
        self._reload_table()

    def _build_ui(self) -> None:
        """Build the user interface."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("panelHeader")
        h_layout = QHBoxLayout(header)
        title = QLabel("Knowledge Management")
        title.setObjectName("panelTitle")
        self.doc_count_label = QLabel("Loading...")
        self.doc_count_label.setObjectName("labelSecondary")
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._reload_table)
        h_layout.addWidget(title)
        h_layout.addStretch()
        h_layout.addWidget(self.doc_count_label)
        h_layout.addWidget(refresh_btn)
        root.addWidget(header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Document ID", "Size", "Ingested", "Action"]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(3, 100)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)

        # Pruning progress panel (hidden by default)
        self.progress_panel = QFrame()
        self.progress_panel.setObjectName("progressPanel")
        self.progress_panel.setVisible(False)
        p_layout = QVBoxLayout(self.progress_panel)
        self.prune_label = QLabel("Pruning: —")
        self.prune_label.setObjectName("labelPrimary")
        self.prune_bar = QProgressBar()
        self.prune_bar.setRange(0, 100)
        self.prune_log = QTextEdit()
        self.prune_log.setReadOnly(True)
        self.prune_log.setObjectName("logView")
        self.prune_log.setMaximumHeight(120)
        p_layout.addWidget(self.prune_label)
        p_layout.addWidget(self.prune_bar)
        p_layout.addWidget(self.prune_log)
        root.addWidget(self.progress_panel)

    def _setup_watcher(self) -> None:
        """Watch archive/ and pruned/ for changes. Reload table on any change."""
        self._watcher = QFileSystemWatcher()
        for d in (ARCHIVE_DIR, PRUNED_DIR):
            d.mkdir(parents=True, exist_ok=True)
            self._watcher.addPath(str(d))
        self._watcher.directoryChanged.connect(self._reload_table)

    def _reload_table(self) -> None:
        """Load archive directory in background thread."""
        loader = ArchiveLoaderWorker()
        loader.data_ready.connect(self._populate_table)
        loader.start()
        self._loader = loader  # keep reference

    def _populate_table(self, rows: list) -> None:
        """Populate the table with directory listing results."""
        self.table.setRowCount(0)
        self.doc_count_label.setText(f"{len(rows)} documents")

        for filename, size_bytes, mtime in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(filename))
            size_str = (
                f"{size_bytes / 1024:.1f} KB"
                if size_bytes < 1_000_000
                else f"{size_bytes / 1_000_000:.1f} MB"
            )
            self.table.setItem(row, 1, QTableWidgetItem(size_str))
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(row, 2, QTableWidgetItem(ts))

            prune_btn = QPushButton("Prune")
            prune_btn.setObjectName("btnDanger")
            prune_btn.clicked.connect(
                lambda checked, fn=filename: self._on_prune_clicked(fn)
            )
            self.table.setCellWidget(row, 3, prune_btn)

    def _on_prune_clicked(self, document_id: str) -> None:
        """Handle prune button click with mutual exclusion check."""
        # Mutual exclusion check — ingestion
        if StateManager.is_ingesting():
            self.prune_conflict.emit("ingesting")
            return

        # Mutual exclusion check — query
        try:
            state = StateManager.read()
            if state["query"]["active"]:
                self.prune_conflict.emit("querying")
                return
        except Exception:
            pass

        # Mutual exclusion check — LLM inference server running (port 8080)
        if self._is_llm_inference_running():
            self.prune_conflict.emit("llm_inference")
            return

        # Mutual exclusion check — already pruning
        if StateManager.is_pruning():
            return  # Already pruning — button should be disabled anyway

        # Confirmation dialog
        confirm = QMessageBox.question(
            self,
            "Confirm Pruning",
            f"Permanently remove all vectors, graph nodes, and edges for:\n\n"
            f"{document_id}\n\n"
            f"The PDF will be moved to pruned/. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._start_prune(document_id)

    def _start_prune(self, document_id: str) -> None:
        """Start the pruning process for a document."""
        self.progress_panel.setVisible(True)
        self.prune_label.setText(f"Pruning: {document_id}")
        self.prune_bar.setValue(0)
        self.prune_log.clear()
        self._disable_all_prune_buttons()

        self._active_worker = PruningWorker(document_id)
        self._active_worker.log_line.connect(self._on_prune_log)
        self._active_worker.progress_updated.connect(self.prune_bar.setValue)
        self._active_worker.prune_complete.connect(self._on_prune_complete)
        self._active_worker.start()

    def _on_prune_log(self, line: str) -> None:
        """Handle log line from pruning worker."""
        self.prune_log.append(line)
        self.prune_log.verticalScrollBar().setValue(
            self.prune_log.verticalScrollBar().maximum()
        )

    def _on_prune_complete(self, document_id: str, success: bool) -> None:
        """Handle pruning completion."""
        if success:
            self.prune_bar.setValue(100)
            self.prune_log.append(f"[OK] Pruning complete: {document_id}")
        else:
            self.prune_log.append(
                f"[FAIL] Pruning failed. See log above."
            )
        self._reload_table()
        self._enable_all_prune_buttons()

    def _disable_all_prune_buttons(self) -> None:
        """Disable all prune buttons in the table."""
        for row in range(self.table.rowCount()):
            btn = self.table.cellWidget(row, 3)
            if btn:
                btn.setEnabled(False)

    def _enable_all_prune_buttons(self) -> None:
        """Enable all prune buttons in the table."""
        for row in range(self.table.rowCount()):
            btn = self.table.cellWidget(row, 3)
            if btn:
                btn.setEnabled(True)

    def _is_llm_inference_running(self) -> bool:
        """Return True if the LLM inference server (port 8080) appears to be running."""
        try:
            import socket
            s = socket.create_connection(("127.0.0.1", 8080), timeout=0.5)
            s.close()
            return True
        except OSError:
            return False