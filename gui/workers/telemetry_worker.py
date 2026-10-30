"""
TelemetryWorker — Background QThread that polls hardware every 1000ms.

Uses pynvml for direct NVML GPU metrics (no nvidia-smi subprocess).
Uses psutil for CPU utilisation and temperature.
Reads ingestion state from StateManager (safe in QThread, never in GUI thread).

Emits telemetry_updated(dict) signal every second.
Never touches the GUI directly — only emits signals.
"""

import pynvml
import psutil
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from gui.state.state_manager import StateManager


class TelemetryWorker(QThread):
    """Polls hardware and ingestion state every 1000ms in a background thread."""

    telemetry_updated = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._running = True
        self._nvml_initialized = False

    def run(self) -> None:
        """Poll hardware every 1000ms until stopped."""
        handle = None
        try:
            pynvml.nvmlInit()
            self._nvml_initialized = True
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            handle = None

        while self._running:
            data = self._collect(handle)
            self.telemetry_updated.emit(data)
            self.msleep(1000)

        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def _collect(self, handle) -> dict:
        """Collect all hardware and state metrics. Never raises — catches all."""
        # CSV guard: if the ingestion metrics file is missing, emit neutral
        # telemetry dict so the UI stays alive while the pipeline initializes.
        log_path = Path("logs/ingestion_metrics.csv")
        if not log_path.exists():
            return {
                "gpu_util": 0,
                "vram_used_gib": 0.0,
                "vram_total_gib": 12.0,
                "cpu_util": 0.0,
                "cpu_temp_c": 0.0,
                "ingestion_status": "idle",
                "current_file": "",
                "current_stage": "",
                "session_number": 0,
                "batch_number": 0,
                "total_files": 0,
                "files_remaining": 0,
                "pruning_status": "idle",
                "pruning_progress_pct": 0,
                "query_active": False,
            }
        result: dict = {
            "gpu_util": 0,
            "vram_used_gib": 0.0,
            "vram_total_gib": 12.0,
            "cpu_util": 0.0,
            "cpu_temp_c": 0.0,
            "ingestion_status": "idle",
            "current_file": "",
            "current_stage": "",
            "session_number": 0,
            "batch_number": 0,
            "total_files": 0,
            "files_remaining": 0,
            "pruning_status": "idle",
            "pruning_progress_pct": 0,
            "query_active": False,
        }

        # GPU via pynvml (direct NVML — no subprocess, no nvidia-smi parse)
        if handle:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                result["gpu_util"] = util.gpu
                result["vram_used_gib"] = mem.used / (1024 ** 3)
                result["vram_total_gib"] = mem.total / (1024 ** 3)
            except Exception:
                pass

        # CPU via psutil
        try:
            result["cpu_util"] = psutil.cpu_percent(interval=None)
            temps = psutil.sensors_temperatures()
            # Xeon W-2125 reports under 'coretemp' or 'k10temp'
            for key in ("coretemp", "k10temp", "acpitz"):
                if key in temps and temps[key]:
                    result["cpu_temp_c"] = temps[key][0].current
                    break
        except Exception:
            pass

        # State from gui_state.json (safe in QThread — NOT GUI thread)
        try:
            full_state = StateManager.read()
            # Zombie lock self-heal — check PID liveness
            ing_pid = full_state.get("ingestion", {}).get("pid")
            if ing_pid is not None and not psutil.pid_exists(ing_pid):
                StateManager._clear_ingestion_state()
                full_state = StateManager.read()  # Re-read after clear

            prune_pid = full_state.get("pruning", {}).get("pid")
            if prune_pid is not None and not psutil.pid_exists(prune_pid):
                StateManager._clear_pruning_state()
                full_state = StateManager.read()  # Re-read after clear

            # Ingestion metrics
            ing = full_state.get("ingestion", {})
            result.update({
                "ingestion_status": ing.get("status", "idle"),
                "current_file": ing.get("current_file", ""),
                "current_stage": ing.get("current_stage", ""),
                "session_number": ing.get("session_number", 0),
                "batch_number": ing.get("batch_number", 0),
                "total_files": ing.get("total_files_at_start", 0),
                "files_remaining": ing.get("files_remaining", 0),
            })
            # Pruning metrics
            pruning = full_state.get("pruning", {})
            result.update({
                "pruning_status": pruning.get("status", "idle"),
                "pruning_progress_pct": pruning.get("progress_pct", 0),
            })
            # Query active flag
            query = full_state.get("query", {})
            result.update({
                "query_active": query.get("active", False),
            })
        except Exception:
            pass

        return result

    def stop(self) -> None:
        """Signal the polling loop to exit."""
        self._running = False
