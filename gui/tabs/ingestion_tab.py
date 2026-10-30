"""
IngestionTab — Tab 1: Ingestion controls + telemetry + live log + directory watcher.

Control button state machine:
  idle     → Start enabled, Pause/Stop disabled
  running  → Start disabled, Pause/Stop enabled
  paused   → Start enabled (resumes), Pause disabled, Stop enabled
  stopping → all disabled (greyed, "Stopping...")

QFileSystemWatcher monitors staging/archive/quarantine directories for
real-time file count updates (event-driven, no polling).

Telemetry updates every 1000ms via TelemetryWorker signal.
Live log streams from IngestionWorker subprocess output.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QGroupBox,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QFileSystemWatcher, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QTextCursor

from gui.state.state_manager import StateManager
from gui.workers.telemetry_worker import TelemetryWorker
from gui.workers.ingestion_worker import IngestionWorker

# Directory constants (Linux server paths)
HDD_BASE = Path(
    os.environ.get("HDD_BASE_PATH", "/mnt/parameter-archives/GraphRAG-Ingestion-DB")
)
STAGING_DIR = HDD_BASE / "staging"
ARCHIVE_DIR = HDD_BASE / "archive"
QUARANTINE_DIR = HDD_BASE / "quarantine"


class IngestionTab(QWidget):
    """Ingestion pipeline control panel with hardware telemetry and live logging."""

    # Signals for mutual exclusion wiring (emitted from dialog interactions)
    ingestion_started = pyqtSignal()
    ingestion_stopped = pyqtSignal()

    # Signals for worker thread communication (to avoid StateManager.read() in GUI thread)
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ingestion_worker: IngestionWorker | None = None
        self._current_status = "idle"

        self._setup_ui()
        self._setup_file_watcher()
        self._update_button_states("idle")
        self._update_directory_counts()

    def _setup_ui(self) -> None:
        """Build all UI sections."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # — Section 1: Controls —
        controls_group = QGroupBox("Ingestion Controls")
        controls_layout = QVBoxLayout(controls_group)

        # Button row
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start")
        self.pause_btn = QPushButton("⏸ Pause")
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("btn_stop")
        self.pause_btn.setObjectName("btn_pause")

        self.start_btn.clicked.connect(self._on_start_clicked)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.pause_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(1)
        controls_layout.addLayout(btn_row)

        # Status row
        status_grid = QGridLayout()
        self.queue_label = QLabel("Queue: —")
        self.session_label = QLabel("Session: 0")
        self.batch_label = QLabel("Batch: 0/0")
        self.current_file_label = QLabel("Current file: —")
        self.current_stage_label = QLabel("Current stage: —")

        status_grid.addWidget(self.queue_label, 0, 0)
        status_grid.addWidget(self.session_label, 0, 1)
        status_grid.addWidget(self.batch_label, 0, 2)
        status_grid.addWidget(self.current_file_label, 1, 0, 1, 2)
        status_grid.addWidget(self.current_stage_label, 1, 2)
        controls_layout.addLayout(status_grid)

        main_layout.addWidget(controls_group)

        # — Section 2: Hardware Telemetry —
        telemetry_group = QGroupBox("Hardware Telemetry")
        telemetry_layout = QGridLayout(telemetry_group)

        # GPU util
        telemetry_layout.addWidget(QLabel("GPU Compute"), 0, 0)
        self.gpu_bar = QProgressBar()
        self.gpu_bar.setObjectName("gpu_bar")
        self.gpu_bar.setRange(0, 100)
        self.gpu_bar.setFormat("%v%")
        telemetry_layout.addWidget(self.gpu_bar, 0, 1)
        self.gpu_label = QLabel("0%")
        self.gpu_label.setMinimumWidth(50)
        telemetry_layout.addWidget(self.gpu_label, 0, 2)

        # VRAM
        telemetry_layout.addWidget(QLabel("VRAM"), 1, 0)
        self.vram_bar = QProgressBar()
        self.vram_bar.setObjectName("vram_bar")
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setFormat("%v%")
        telemetry_layout.addWidget(self.vram_bar, 1, 1)
        self.vram_label = QLabel("0.0 / 12.0 GB")
        self.vram_label.setMinimumWidth(100)
        telemetry_layout.addWidget(self.vram_label, 1, 2)

        # CPU util
        telemetry_layout.addWidget(QLabel("CPU"), 2, 0)
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setObjectName("cpu_bar")
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setFormat("%v%")
        telemetry_layout.addWidget(self.cpu_bar, 2, 1)
        self.cpu_label = QLabel("0%")
        self.cpu_label.setMinimumWidth(50)
        telemetry_layout.addWidget(self.cpu_label, 2, 2)

        # CPU temp
        telemetry_layout.addWidget(QLabel("CPU Temp"), 3, 0)
        self.cpu_temp_label = QLabel("—°C")
        telemetry_layout.addWidget(self.cpu_temp_label, 3, 1, 1, 2)

        main_layout.addWidget(telemetry_group)

        # — Section 3: Live Log —
        log_group = QGroupBox("Live Log")
        log_layout = QVBoxLayout(log_group)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)

        log_layout.addWidget(self.log_view)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.log_view.clear)
        log_layout.addWidget(clear_log_btn)

        main_layout.addWidget(log_group, stretch=1)

        # — Section 4: Directory Watcher —
        dir_group = QGroupBox("Directory Watcher")
        dir_layout = QVBoxLayout(dir_group)

        dir_info = QHBoxLayout()
        self.staging_count_label = QLabel(f"Staging: — files")
        self.archive_count_label = QLabel(f"Archive: — files")
        self.quarantine_count_label = QLabel(f"Quarantine: — files")
        dir_info.addWidget(self.staging_count_label)
        dir_info.addWidget(self.archive_count_label)
        dir_info.addWidget(self.quarantine_count_label)
        dir_layout.addLayout(dir_info)

        dir_btn_row = QHBoxLayout()
        open_staging_btn = QPushButton("Open Staging")
        open_staging_btn.clicked.connect(lambda: self._open_directory(STAGING_DIR))
        open_quarantine_btn = QPushButton("Open Archive")
        open_quarantine_btn.clicked.connect(lambda: self._open_directory(ARCHIVE_DIR))
        view_errors_btn = QPushButton("Open Quarantine")
        view_errors_btn.clicked.connect(self._open_quarantine_errors)

        dir_btn_row.addWidget(open_staging_btn)
        dir_btn_row.addWidget(open_quarantine_btn)
        dir_btn_row.addWidget(view_errors_btn)
        dir_layout.addLayout(dir_btn_row)

        main_layout.addWidget(dir_group)

    def _setup_file_watcher(self) -> None:
        """Watch staging/archive/quarantine directories for file count changes."""
        self._watcher = QFileSystemWatcher()
        for d in (STAGING_DIR, ARCHIVE_DIR, QUARANTINE_DIR):
            d.mkdir(parents=True, exist_ok=True)
            self._watcher.addPath(str(d))
        self._watcher.directoryChanged.connect(self._on_directory_changed)

    # --- Button state machine ---

    def _update_button_states(self, status: str) -> None:
        """Update button enabled/disabled state based on ingestion status."""
        self._current_status = status

        if status == "idle":
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Start")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
        elif status == "running":
            self.start_btn.setEnabled(False)
            self.start_btn.setText("▶ Start")
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
        elif status == "paused":
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Resume")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        elif status == "stopping":
            self.start_btn.setEnabled(False)
            self.start_btn.setText("▶ Start")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("⏸ Pausing...")
            self.stop_btn.setEnabled(False)
        else:
            # error or unknown — treat as idle
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶ Start")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)

    # --- Button click handlers ---

    def _on_start_clicked(self) -> None:
        """Start or resume ingestion."""
        if self._current_status == "paused":
            # Resume: request resume via signal to worker thread
            self.resume_requested.emit()
            self._update_button_states("running")
            return

        # Start new ingestion
        self._ingestion_worker = IngestionWorker()
        self._ingestion_worker.log_line.connect(self.on_log_line)
        self._ingestion_worker.process_started.connect(self._on_process_started)
        self._ingestion_worker.process_finished.connect(self._on_process_finished)
        self._ingestion_worker.error.connect(self._on_process_error)
        # Connect worker signals for pause/stop/resume requests
        self.pause_requested.connect(self._ingestion_worker.request_pause)
        self.stop_requested.connect(self._ingestion_worker.request_stop)
        self.resume_requested.connect(self._ingestion_worker.request_resume)
        self._ingestion_worker.start()
        self.ingestion_started.emit()

    def _on_pause_clicked(self) -> None:
        """Pause ingestion by requesting pause via signal to worker thread."""
        self.pause_requested.emit()
        self._update_button_states("paused")

    def _on_stop_clicked(self) -> None:
        """Stop ingestion by requesting stop via signal to worker thread."""
        self.stop_requested.emit()
        self._update_button_states("stopping")

    # --- IngestionWorker lifecycle handlers ---

    def _on_process_started(self) -> None:
        """Called when the ingestion subprocess starts."""
        self._update_button_states("running")
        self.on_log_line("Ingestion subprocess started")

    def _on_process_finished(self, exit_code: int) -> None:
        """Called when the ingestion subprocess finishes."""
        status_msg = f"exit code {exit_code}"
        if exit_code == 0:
            self.on_log_line(f"Ingestion completed successfully ({status_msg})")
        else:
            self.on_log_line(f"Ingestion failed ({status_msg})")
        self._update_button_states("idle")
        self._ingestion_worker = None
        # Disconnect signals to avoid issues with deleted worker
        try:
            self.pause_requested.disconnect(self._ingestion_worker.request_pause)
            self.stop_requested.disconnect(self._ingestion_worker.request_stop)
            self.resume_requested.disconnect(self._ingestion_worker.request_resume)
        except (RuntimeError, TypeError):
            # Worker may already be deleted
            pass
        self.ingestion_stopped.emit()

    def _on_process_error(self, error_msg: str) -> None:
        """Called when ingestion subprocess fails to start."""
        self.on_log_line(f"ERROR: {error_msg}")
        self._update_button_states("idle")
        self._ingestion_worker = None
        # Disconnect signals
        try:
            self.pause_requested.disconnect(self._ingestion_worker.request_pause)
            self.stop_requested.disconnect(self._ingestion_worker.request_stop)
            self.resume_requested.disconnect(self._ingestion_worker.request_resume)
        except (RuntimeError, TypeError):
            pass
        self.ingestion_stopped.emit()

    # --- Slots for signals from other components ---

    @pyqtSlot(str)
    def on_log_line(self, line: str) -> None:
        """Append a timestamped log line and trim to 1000 lines.

        Also parses [TELEMETRY] key=value lines from batch_coordinator.py
        to update status labels in real-time between StateManager reads.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {line}")

        # Parse [TELEMETRY] structured log lines
        if "[TELEMETRY]" in line:
            self._parse_telemetry_line(line)

        # Trim to 1000 lines
        doc = self.log_view.document()
        while doc.blockCount() > 1000:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

        # Auto-scroll to bottom
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _parse_telemetry_line(self, line: str) -> None:
        """Extract key=value pairs from a [TELEMETRY] log line and update labels.

        Format: [TELEMETRY] session=N batch=N total=N remaining=N file=NAME stage=STAGENAME
        """
        try:
            telemetry_part = line.split("[TELEMETRY]", 1)[1].strip()
            kv_map: dict[str, str] = {}
            for token in telemetry_part.split():
                if "=" in token:
                    key, _, value = token.partition("=")
                    kv_map[key.strip()] = value.strip()

            if "session" in kv_map:
                self.session_label.setText(f"Session: {kv_map['session']}")
            if "batch" in kv_map:
                total = kv_map.get("total", "0")
                self.batch_label.setText(f"Batch: {kv_map['batch']}/{total}")
            if "total" in kv_map and "remaining" in kv_map:
                self.queue_label.setText(
                    f"Queue: {kv_map['remaining']}/{kv_map['total']}"
                )
            if "file" in kv_map:
                fname = kv_map["file"]
                self.current_file_label.setText(
                    f"Current file: {fname if fname else '—'}"
                )
            if "stage" in kv_map:
                self.current_stage_label.setText(
                    f"Current stage: {kv_map['stage']}"
                )
        except Exception:
            pass  # Never crash the GUI on a malformed telemetry line

    @pyqtSlot(dict)
    def on_telemetry_updated(self, data: dict) -> None:
        """Receives TelemetryWorker signal every 1000ms. Updates all widgets."""
        # Defensive access — never crash the GUI on a missing key
        gpu_util = data.get("gpu_util", 0)
        vram_used = data.get("vram_used_gib", 0.0)
        vram_total = data.get("vram_total_gib", 12.0)
        cpu_util = data.get("cpu_util", 0.0)
        cpu_temp = data.get("cpu_temp_c", 0.0)
        session_num = data.get("session_number", 0)
        batch_num = data.get("batch_number", 0)
        total_files = data.get("total_files", 0)
        current_file = data.get("current_file", "")
        current_stage = data.get("current_stage", "")
        ingestion_status = data.get("ingestion_status", "idle")

        self.gpu_bar.setValue(gpu_util)
        self.gpu_label.setText(f"{gpu_util}%")

        vram_pct = int(vram_used / vram_total * 100) if vram_total > 0 else 0
        self.vram_bar.setValue(vram_pct)
        self.vram_label.setText(
            f"{vram_used:.1f} / {vram_total:.0f} GiB"
        )

        self.cpu_bar.setValue(int(cpu_util))
        self.cpu_label.setText(f"{cpu_util:.0f}%")
        self.cpu_temp_label.setText(f"{cpu_temp:.0f}°C")

        self.session_label.setText(f"Session: {session_num}")
        self.batch_label.setText(
            f"Batch: {batch_num}/{total_files}"
        )
        self.current_file_label.setText(
            f"Current file: {current_file or '—'}"
        )
        self.current_stage_label.setText(
            f"Current stage: {current_stage or '—'}"
        )

        # Update queue count
        remaining = data.get("files_remaining", 0)
        self.queue_label.setText(f"Queue: {remaining}/{total_files}")

        # Update button states based on ingestion status from state file
        self._update_button_states(ingestion_status)

    # --- Directory watcher helpers ---

    def _on_directory_changed(self, path: str) -> None:
        """Fired when QFileSystemWatcher detects a change. Recount files."""
        self._update_directory_counts()

    def _update_directory_counts(self) -> None:
        """Count PDF files in each watched directory."""
        for dir_path, label in [
            (STAGING_DIR, self.staging_count_label),
            (ARCHIVE_DIR, self.archive_count_label),
            (QUARANTINE_DIR, self.quarantine_count_label),
        ]:
            try:
                count = len(
                    list(dir_path.glob("*.pdf")) + list(dir_path.glob("*.PDF"))
                )
                label.setText(f"{dir_path.name}: {count} files")
            except Exception:
                label.setText(f"{dir_path.name}: —")

    def _open_directory(self, path: Path) -> None:
        """Open directory in the system file manager."""
        try:
            subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    def _open_quarantine_errors(self) -> None:
        """Open quarantine directory for viewing .error.log files."""
        self._open_directory(QUARANTINE_DIR)

    # --- Public methods for mutual exclusion wiring ---

    def on_stop_requested(self) -> None:
        """Called externally (from QueryTab via MutualExclusionDialog)."""
        self._on_stop_clicked()

    def on_pause_requested(self) -> None:
        """Called externally (from QueryTab via MutualExclusionDialog)."""
        self._on_pause_clicked()