# SKILL.md — Engineering Laws & Hard Constraints
# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine
#
# This file supersedes all previous SKILL.md versions.
# PyQt6 build skills → SKILL_GUI.md
# Phase 2 additions → SKILL_PHASE2.md
# This document codifies the immutable engineering doctrine that governs both.
#
# Read: CLAUDE.md → AGENTS.md → this file → SKILL_GUI.md → SKILL_PHASE2.md

---

## 1. LOCAL LLM HARDWARE & VRAM MAPPING (RTX 3060 12GB)

### Model Loading Rules for llama_cpp

- Load `.gguf` binaries using relative paths from the project root only.
  Correct:   `./models/Qwen3.6-12B-IQ-Q4_K_M.gguf`
  Forbidden: `/models/Qwen3.6-12B-IQ-Q4_K_M.gguf`
  Forbidden: `/home/graphrag-automation/graphrag_engine/models/...` hardcoded in code
  Required:  Read path from environment variable, fall back to relative `./models/`

- The llama_cpp.Llama constructor must always specify `n_threads` and `n_threads_batch`
  explicitly. Never rely on defaults. Xeon W-2125 has 8 hardware threads.
  Required: `n_threads=8, n_threads_batch=8`

### VRAM Budget and Layer Allocation Rules

The RTX 3060 has 12GB VRAM. The following rules are absolute.

**Rule 1 — Never load n_gpu_layers=-1 for models exceeding 8GB when other CUDA
consumers are simultaneously active.**

| Model | VRAM footprint | n_gpu_layers rule |
|---|---|---|
| Llama 3.1 8B Q8_0 (port 8080) | ~8.5GB | `-1` permitted ONLY when running solo |
| Qwen3.6-12B IQ-Q4_K_M (port 8000) | ~7.0GB | `-1` permitted — fits with BGE + Reranker |
| BGE-large-en-v1.5 | ~1.34GB | Always on GPU |
| BGE-reranker-v2-m3 | ~1.1GB | Always on GPU at query time |

**Rule 2 — At query time, the simultaneous VRAM budget is:**
```
BGE embed:    1.34 GB
Reranker:     1.10 GB
Qwen:         7.00 GB
Buffers/KV:   1.00 GB
──────────────────────
Total:       10.44 GB / 12.0 GB  ✓
```
This leaves 1.56GB headroom. Do not add any CUDA consumer to the query-time process.

**Rule 3 — If a 12B+ model must share VRAM with embedding models, explicitly cap
GPU layers and restrict context window to avoid CUDA OOM panics:**
```python
# Example: hypothetical 12B model alongside BGE (1.34GB) on a 12GB card
# Available VRAM for model: 12GB - 1.34GB - buffers = ~9.5GB
# 12B Q4_K_M ≈ 7.5GB, so full offload is possible here.
# If the model were 12B Q8_0 (~13GB), cap would be required:
Llama(
    model_path="./models/hypothetical-12b-q8.gguf",
    n_gpu_layers=28,    # cap below full offload to stay within VRAM
    n_ctx=4096,         # restrict context to reduce KV cache pressure
    n_threads=8,
    n_threads_batch=8,
)
```

**Rule 4 — The two-port architecture is the VRAM isolation mechanism.**
Port 8000 (query server) and port 8080 (LLM inference server) must NEVER run
simultaneously. This is not a preference — it is a hard VRAM limit. Combined:
8.5GB (Llama on port 8080) + 10.4GB (full query stack on port 8000) = 18.9GB.
The RTX 3060 has 12GB. The result is a CUDA OOM → SIGSEGV.

**Rule 5 — Context window sizes:**
- Port 8000 Qwen: `n_ctx=8192` (sufficient for legal document retrieval context)
- Port 8080 Llama: `n_ctx=4096` (entity extraction prompts are short; wider context
  wastes KV cache VRAM unnecessarily)

### jemalloc Mandate for Long Runs

All ingestion processes exceeding 30 minutes must run with jemalloc to prevent
glibc malloc from fragmenting heap memory across sequential ML tensor allocations.

```bash
# Mandatory — set before any ingestion subprocess launch:
export LD_PRELOAD=/usr/lib/libjemalloc.so
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

Install: `sudo pacman -S jemalloc`
Verify: `ls /usr/lib/libjemalloc.so` (must exist before launching ingestion)

---

## 2. NETWORK PORT SANITATION & DAEMON CONTROL

### The Ghost Process Problem

When a Python server process (uvicorn, llama_cpp.server) is SIGKILLed or crashes
without proper cleanup, the OS kernel may retain the TCP socket in TIME_WAIT state.
Subsequent launch attempts fail with `[Errno 98] address already in use` or
`[Errno 111] connection refused`. These must be destroyed before reinitialising any server.

### Required Kill Sequence Before Any Server Start

```bash
# Kill query server and everything on port 8000:
sudo fuser -k 8000/tcp
pkill -f "uvicorn src.api.fastapi_service" 2>/dev/null

# Kill LLM inference server and everything on port 8080:
sudo fuser -k 8080/tcp
pkill -9 -f "llama_cpp.server" 2>/dev/null
pkill -9 -f "llama_cpp server" 2>/dev/null

# If using Ollama (not currently in use, but if present):
sudo killall -9 ollama 2>/dev/null
sudo fuser -k 11434/tcp 2>/dev/null

# Verify ports are clear before proceeding:
fuser 8000/tcp && echo "PORT 8000 STILL IN USE — ABORT" || echo "Port 8000 clear"
fuser 8080/tcp && echo "PORT 8080 STILL IN USE — ABORT" || echo "Port 8080 clear"
```

### Port Kill is Mandatory in These Routines

| Routine | Ports to kill before starting |
|---|---|
| Starting query server (port 8000) | Kill 8000 AND 8080 |
| Starting LLM inference server (port 8080) | Kill 8000 AND 8080 |
| Starting ingestion | Kill 8000 |
| Starting pruning operation | Kill 8080 (prevent graph_builder.py write conflict) |

### The `[Errno 98]` Response Protocol

If a server fails with `[Errno 98] address already in use`:
1. Run the kill sequence above
2. Wait 5 seconds
3. Retry the server start
4. If it fails again: `ss -tlnp | grep -E "8000|8080"` to identify the squatting PID
5. `kill -9 <PID>`

---

## 3. DIRECT NATIVE EXECUTION vs. API ROUTING

### Doctrine for Evaluation Scripts

Do not route bulk evaluation matrices (100-question test suites, regression testing)
through the FastAPI endpoint (uvicorn on port 8000).

HTTP routing adds: network stack latency, JSON serialisation overhead, uvicorn worker
concurrency limits, potential 404s from route mismatches, and timeout failures on
slow Qwen inference calls (>120s).

For headless automated testing and evaluation, directly import the GraphRAG engine
core into local Python memory:

```python
# Correct — headless direct import for eval:
import sys
sys.path.insert(0, "/home/graphrag-automation/graphrag_engine")
from src.retrieval.hybrid_search import HybridSearchEngine
from src.retrieval.query_router import QueryRouter
from src.api.conversation_manager import ConversationManager

# Incorrect — routing eval through HTTP:
response = httpx.post("http://localhost:8000/query", json={"query": q})
# This approach fails if uvicorn is not running, adds 30-120s timeout risk,
# and cannot inspect internal state (retrieved chunks, graph nodes, scores)
```

### When HTTP Routing IS Correct

HTTP routing to port 8000 is required for:
- The PyQt6 GUI (query_worker.py) — cross-process, non-Python consumer
- Integration tests that specifically test the API contract
- Performance benchmarking of the full HTTP stack

HTTP routing is never correct for:
- Automated evaluation suites (run_eval.py)
- Unit tests of individual retrieval components
- Batch regression testing

---

## 4. PYQT6 THREADING & 144Hz COMPLIANCE

### The Blocking Call Ban

The main Qt event loop thread — the thread running `QApplication.exec()` — must
never execute any operation that takes longer than 6.9ms (one frame at 144Hz).

These operations are absolutely forbidden in the main thread:
- Any file I/O: `open()`, `json.load()`, `json.dump()`, `pathlib.Path.read_text()`
- Any database operation: `chromadb.query()`, `chromadb.delete()`
- Any subprocess spawn: `subprocess.Popen()`, `subprocess.run()`
- Any network call: `httpx.get()`, `httpx.post()`, `requests.get()`
- Any `time.sleep()` call
- Any `StateManager.read()` or `StateManager.write()` call

All of these must be delegated to QThread workers.

### State Caching Mandate

GUI state (ingestion active, pruning active, query active) must NEVER be read
from disk in button click handlers or any GUI event handler. The main thread
must operate on a cached in-memory copy of state, updated only via asynchronous
telemetry signals.

```python
# WRONG — reads disk in GUI thread:
def on_submit_clicked(self):
    if StateManager.read()["ingestion"]["status"] == "running":  # BLOCKED
        return

# CORRECT — uses cached state from TelemetryWorker signal:
def on_submit_clicked(self):
    if self._cached_ingestion_status == "running":  # fast, no I/O
        return

# Cached state is updated by TelemetryWorker signal every 1000ms:
@pyqtSlot(dict)
def on_telemetry_updated(self, data: dict) -> None:
    self._cached_ingestion_status = data["ingestion_status"]
    self._cached_pruning_status = data["pruning_status"]
    self._cached_query_active = data["query_active"]
```

### Required QThread Workers

Every blocking operation must have a dedicated QThread worker:

| Worker | Blocked operation | Signal emitted |
|---|---|---|
| `TelemetryWorker` | pynvml, psutil, state file read | `telemetry_updated(dict)` |
| `IngestionWorker` | subprocess.Popen(batch_coordinator.py) | `log_line(str)`, `process_finished(int)` |
| `PruningWorker` | subprocess.Popen(prune_document.py) | `log_line(str)`, `prune_complete(str, bool)` |
| `QueryWorker` | httpx.post() to port 8000 | `response_ready(dict)`, `error_occurred(str)` |
| `ArchiveLoaderWorker` | directory glob, stat() | `data_ready(list)` |
| `GraphLoader` | json.load(knowledge_graph.json) + pyvis build | `html_ready(str)` |
| `HealthCheckWorker` | httpx.get() port 8000 health | `status_changed(bool)` |

### PyVis / QWebEngineView Physics

The PyVis network graph runs physics in Chromium's `requestAnimationFrame` loop.
This is entirely decoupled from Python. Do not attempt to pump or synchronise the
graph physics from Python code. The JavaScript engine handles frame pacing natively.

---

## 5. ATOMIC STATE MANAGEMENT & SUBPROCESS SECURITY

### Atomic Write Protocol

Every write to `gui_state.json` or `knowledge_graph.json` must use the
POSIX-atomic rename pattern. This prevents partial writes corrupting state if the
process crashes mid-write.

```python
import os
import json
import tempfile
from pathlib import Path

def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically using tempfile + os.replace (POSIX rename)."""
    # CRITICAL: dir= must be the same filesystem as the target file.
    # If tempfile uses /tmp (a different mount), os.replace falls back to
    # a non-atomic copy+delete, defeating the purpose.
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,       # same filesystem as target — mandatory
        suffix=".json.tmp",
        delete=False,
        encoding="utf-8"
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, str(path))  # POSIX atomic rename — guaranteed
```

**The `dir=path.parent` parameter is mandatory.** On systems where `/tmp` is
a tmpfs mount and the project data is on ext4/btrfs, `os.replace()` across
different filesystems triggers a non-atomic copy+delete. This creates a window
where both the old and new file exist simultaneously — a race condition.

### Subprocess Argument Passing

Every `subprocess.Popen()` and `subprocess.run()` call must pass arguments as
a Python list, never as a shell string.

```python
# CORRECT — list-form, no shell injection vector:
subprocess.Popen(
    [str(VENV_PYTHON), "prune_document.py", document_id],
    cwd=str(PROJECT_ROOT),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
    # shell=True is FORBIDDEN
)

# WRONG — shell=True allows injection if document_id contains shell metacharacters:
subprocess.Popen(
    f"python prune_document.py {document_id}",
    shell=True  # ABSOLUTE BAN
)
```

Even when `document_id` is sourced from a trusted filesystem glob (not user
input), `shell=True` is still forbidden. Defence in depth requires list-form
always.

---

## 6. MUTUAL EXCLUSION (MUTEX) ARCHITECTURE

### Tri-State Lock Matrix

| User action | Blocked if ingesting | Blocked if querying | Blocked if pruning |
|---|---|---|---|
| Start ingestion | — | YES | YES |
| Submit query | YES | — | YES |
| Prune document | YES | YES | — |

All blocked states present a `MutualExclusionDialog` with context-aware text
appropriate to the blocking condition.

### psutil.pid_exists() over Boolean Flags

Static boolean flags (`is_ingesting = True`) are permanently poisoned if the
backend process crashes without writing a cleanup state. The GUI will refuse
to start ingestion indefinitely until manually reset.

The correct pattern polls the OS directly using the backend process PID:

```python
import psutil

class StateManager:
    
    @classmethod
    def is_ingesting(cls) -> bool:
        """Check ingestion state using PID liveness, not static flag."""
        state = cls.read()
        pid = state["ingestion"].get("pid")
        if pid is None:
            return False
        if not psutil.pid_exists(pid):
            # Process is dead — clean up stale state
            cls._clear_ingestion_state()
            return False
        return state["ingestion"]["status"] in ("running", "paused")
    
    @classmethod
    def is_pruning(cls) -> bool:
        """Check pruning state using PID liveness."""
        state = cls.read()
        pid = state["pruning"].get("pid")
        if pid is None:
            return False
        if not psutil.pid_exists(pid):
            cls._clear_pruning_state()
            return False
        return state["pruning"]["status"] == "running"
    
    @classmethod
    def _clear_ingestion_state(cls) -> None:
        """Reset stale ingestion state after detected process death."""
        state = cls.read()
        state["ingestion"]["status"] = "idle"
        state["ingestion"]["pid"] = None
        cls.write(state)
    
    @classmethod
    def _clear_pruning_state(cls) -> None:
        state = cls.read()
        state["pruning"]["status"] = "idle"
        state["pruning"]["pid"] = None
        cls.write(state)
```

**Updated gui_state.json schema — add PID fields:**
```json
{
  "ingestion": {
    "status": "idle",
    "pid": null,
    "pause_requested": false,
    "stop_requested": false
  },
  "pruning": {
    "status": "idle",
    "pid": null,
    "document_id": "",
    "progress_pct": 0
  },
  "query": {
    "active": false,
    "pid": null
  }
}
```

**IngestionWorker and PruningWorker must write their PID to state on start:**
```python
def run(self) -> None:
    self._process = subprocess.Popen([...])
    state = StateManager.read()
    state["ingestion"]["pid"] = self._process.pid
    StateManager.write(state)
    # ... rest of run()
```

### Port 8080 Check Before Pruning

Before any pruning operation starts, check whether the LLM inference server
is running on port 8080. An active port 8080 means `graph_builder.py` may be
writing to `knowledge_graph.json` concurrently. Pruning must not begin.

```python
import socket

def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

# In KnowledgeTab._on_prune_clicked:
if _is_port_in_use(8080):
    QMessageBox.warning(
        self, "Ingestion Active",
        "The LLM inference server is running on port 8080.\n"
        "A graph build may be in progress. Stop port 8080 before pruning.\n\n"
        "Run: pkill -9 -f llama_cpp.server"
    )
    return
```

---

## 7. QSS STYLING & UI HARDCODING BANS

### The Token System

All visual values — colours, sizes, radii, spacing, font families — must be
defined in `ThemeLoader.TOKENS` and applied exclusively via `theme.qss`.

**Absolutely forbidden in any `.py` file:**
```python
# BANNED — hardcoded hex:
label.setStyleSheet("color: #cdd6f4;")
button.setStyleSheet("background: #89b4fa;")

# BANNED — hardcoded pixel margin:
layout.setContentsMargins(5, 5, 5, 5)  # use @spacing_sm token via QSS

# BANNED — hardcoded font string:
font = QFont("Courier New", 12)  # define in theme.qss @font_family_mono
```

**Required pattern — objectName + QSS:**
```python
# CORRECT — objectName for QSS targeting:
self.answer_label.setObjectName("answerText")
self.progress_bar.setObjectName("ingestionProgress")

# QSS file handles all styling:
# QTextEdit#answerText { ... using @tokens only ... }
# QProgressBar#ingestionProgress { ... }
```

**Token substitution happens at startup in ThemeLoader.load():**
```python
# ThemeLoader.load() replaces all @token_name with resolved values
# before applying the stylesheet to QApplication.
# Adding a new @token requires:
# 1. Add to ThemeLoader.TOKENS dict
# 2. Use @token_name in theme.qss
# 3. Never reference the hex value anywhere else
```

### Margin and Spacing Rules

All margin, padding, and spacing values must use theme tokens:
```qss
/* CORRECT: */
QPushButton { padding: @spacing_sm @spacing_md; }
QWidget { margin: @spacing_sm; }

/* WRONG: */
QPushButton { padding: 8px 16px; }
QWidget { margin: 5px; }
```

---

## 8. HARDWARE THERMAL OVERRIDES

### Background

Aggressive Linux software fan controllers (`fancontrol`, `thermald`) can lock the
RTX 3060's cooling fan at high RPMs during idle periods, creating unnecessary noise
without thermal benefit. During sustained GPU inference (90%+ utilisation for hours),
the NVIDIA VBIOS fan curve provides better thermal management than user-space
software controllers that may react too slowly or use incorrect thermal targets.

### Protocol: Return Cooling Authority to BIOS/VBIOS

```bash
# Step 1 — Disable user-space fan controllers:
sudo systemctl stop fancontrol 2>/dev/null
sudo systemctl disable fancontrol 2>/dev/null
sudo systemctl stop thermald 2>/dev/null
sudo systemctl disable thermald 2>/dev/null

# Step 2 — Verify NVIDIA fan control is set to auto (VBIOS curve):
nvidia-settings -a "[gpu:0]/GPUFanControlState=0" 2>/dev/null
# GPUFanControlState=0 = automatic VBIOS control
# GPUFanControlState=1 = manual (forced by some fan control software)

# Step 3 — Confirm fan speed is managed by VBIOS:
nvidia-smi --query-gpu=fan.speed --format=csv,noheader
# Should return a reasonable value (20-40% at idle)
# If it returns 100% at idle, thermald or fancontrol may still be running

# Step 4 — Monitor during inference:
watch -n 2 'nvidia-smi --query-gpu=temperature.gpu,fan.speed,power.draw --format=csv,noheader'
# Expected during 90%+ GPU load: temp 65-80°C, fan 50-80%, power 110-170W
```

### Normal Operating Ranges (RTX 3060 on Xeon W-2125 system)

| State | GPU Temp | Fan Speed | Power Draw |
|---|---|---|---|
| Idle (no inference) | 35-50°C | 0-30% | 10-20W |
| BGE embedding | 55-65°C | 30-50% | 60-90W |
| Llama/Qwen inference | 65-80°C | 50-75% | 110-170W |
| Emergency throttle threshold | >90°C | 100% | automatic throttle |

If GPU temperature exceeds 85°C during normal inference, stop the workload and
verify airflow. The RTX 3060 thermal limit is 93°C before hardware throttling.

### Xeon CPU Cooling

The Xeon W-2125 is a workstation CPU with good thermal headroom. Keep CPU governor
on `performance` mode. If CPU temperatures exceed 80°C under full parsing load,
check that case airflow is adequate. The Xeon does not require user-space thermal
management beyond the `cpupower` governor setting.

```bash
# Verify CPU governor:
cpupower frequency-info | grep "current policy"
# Must show: performance

# If wrong:
sudo cpupower frequency-set -g performance
```

---

## 9. PHASE 3 ENGINEERING PATTERNS

### 9.1 Headless Uvicorn Bridge (Automated Query Server Management)

The user must never be required to manually launch the query server. The GUI
manages the server lifecycle natively through a `ServerManager` class.

```python
# gui/services/server_manager.py
import os
import socket
import subprocess
import psutil
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

PROJECT_ROOT = Path("/home/graphrag-automation/graphrag_engine")
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"


def is_port_bound(port: int) -> bool:
    """Return True if a process is listening on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


class ServerManager:
    """Manages the uvicorn query server lifecycle from the GUI."""

    _process: subprocess.Popen | None = None

    @classmethod
    def ensure_running(cls) -> bool:
        """
        Check port 8000. Kill ghost process if bound but dead.
        Launch uvicorn if not running. Return True when server is ready.
        """
        if is_port_bound(8000):
            # Port is bound — verify it's actually responsive
            return True  # HealthCheckWorker will confirm via /health

        # Kill ghost process squatting on port (if any)
        try:
            subprocess.run(
                ["sudo", "fuser", "-k", "8000/tcp"],
                timeout=5, capture_output=True
            )
        except Exception:
            pass

        # Launch uvicorn as detached subprocess
        env = os.environ.copy()
        cls._process = subprocess.Popen(
            [
                str(VENV_PYTHON), "-m", "uvicorn",
                "src.api.fastapi_service:app",
                "--host", "127.0.0.1",
                "--port", "8000",
                "--log-level", "warning",
            ],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,  # detach from GUI process group
        )
        return False  # HealthCheckWorker polls until port is bound

    @classmethod
    def get_pid(cls) -> int | None:
        return cls._process.pid if cls._process else None

    @classmethod
    def shutdown(cls) -> None:
        if cls._process and psutil.pid_exists(cls._process.pid):
            cls._process.terminate()
            cls._process = None
        subprocess.run(
            ["sudo", "fuser", "-k", "8000/tcp"],
            capture_output=True
        )
```

**QueryTab initialisation sequence with ServerManager:**
```python
def __init__(self, parent=None):
    super().__init__(parent)
    self.submit_btn.setEnabled(False)  # disabled until server confirmed
    self._start_server_check()

def _start_server_check(self) -> None:
    ServerManager.ensure_running()
    # HealthCheckWorker polls every 5s — re-enables submit_btn on True
```

### 9.2 Quarantine Auto-Routing in run_ingestion.py

Non-PDF files and corrupt PDFs must be automatically quarantined rather than
left in staging/ to be re-scanned on every boot.

```python
# In run_ingestion.py, Stage 1 (parser.py) exception handling:

QUARANTINE_DIR = Path(os.environ.get("HDD_BASE_PATH",
    "/opt/graphrag/data/ingestion_pool")) / "quarantine"

def _process_file_safe(file_path: Path) -> bool:
    """Returns True on success, False on failure. Auto-quarantines bad files."""
    try:
        chunks = parser.parse(file_path)
        return True
    except Exception as e:
        error_str = str(e)
        # Catch known bad-file signatures from unstructured/pdfminer:
        if any(sig in error_str for sig in [
            "No /Root object",
            "Unsupported extension",
            "PdfReadError",
            "EOF marker not found",
            "Invalid elementary object",
        ]):
            QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
            error_log = QUARANTINE_DIR / f"{file_path.name}.error.log"
            error_log.write_text(
                f"Auto-quarantined by run_ingestion.py\n"
                f"Reason: {error_str}\n"
                f"Timestamp: {datetime.now().isoformat()}\n"
            )
            shutil.move(str(file_path), str(QUARANTINE_DIR / file_path.name))
            print(f"[QUARANTINE] {file_path.name} — {error_str[:80]}", flush=True)
            return False
        raise  # re-raise unexpected errors
```

**The file extensions that trigger immediate quarantine without parsing attempt:**
```python
SKIP_EXTENSIONS = {".error", ".log", ".tmp", ".lock", ".partial", ".csv"}

for file_path in staging_dir.iterdir():
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        shutil.move(str(file_path), str(QUARANTINE_DIR / file_path.name))
        continue
```

### 9.3 PID-Based Zombie Lock Prevention

All state-checking methods must use psutil.pid_exists() as the primary
liveness signal. Static boolean flags are forbidden.

The full implementation is in Section 6. Key addition for Phase 3:
The TelemetryWorker must include PID liveness in its 1000ms poll:

```python
def _collect(self, handle) -> dict:
    result = {...}  # existing telemetry fields

    # PID liveness check — overrides stale state flags
    state = StateManager.read()
    ing_pid = state["ingestion"].get("pid")
    prune_pid = state["pruning"].get("pid")

    if ing_pid and not psutil.pid_exists(ing_pid):
        StateManager._clear_ingestion_state()
        state["ingestion"]["status"] = "idle"

    if prune_pid and not psutil.pid_exists(prune_pid):
        StateManager._clear_pruning_state()
        state["pruning"]["status"] = "idle"

    result["ingestion_status"] = state["ingestion"]["status"]
    result["pruning_status"] = state["pruning"]["status"]
    return result
```

This means zombie locks self-heal within 1 second of process death.
No manual intervention or state file deletion required.

---

## 10. UI PATCH MANDATES — PHASE 3 CORRECTIONS

These are exact, non-negotiable UI fixes derived from confirmed hardware and layout bugs.
Each patch is atomic. Implement them in the order listed.

### 10.1 VRAM Binary Conversion (CRITICAL — wrong hardware reading)

The GPU VRAM display shows 13GB instead of 12GB because pynvml returns bytes and
the code divides by 1,000,000,000 (decimal) instead of 1,073,741,824 (binary GiB).

**Forbidden:**
```python
vram_used_gb = mem.used / 1_000_000_000   # decimal — reports 13.4GB for 12GB card
vram_total_gb = mem.total / 1_000_000_000
```

**Required:**
```python
GiB = 1024 ** 3
vram_used_gib = mem.used / GiB    # binary — correctly reports 11.6 GiB
vram_total_gib = mem.total / GiB  # correctly reports 11.6 GiB total capacity
# Display as: f"{vram_used_gib:.1f} / {vram_total_gib:.1f} GiB"
```

Fix location: `gui/workers/telemetry_worker.py`, `_collect()` method.

### 10.2 Button Label Remapping

Current labels are wrong. Apply these exact replacements:

| Widget location | Current (wrong) label | Required (correct) label |
|---|---|---|
| IngestionTab directory panel | "Open quarantine" | "Open Archive" |
| IngestionTab directory panel | "View error logs" | "Open Quarantine" |

The "Open Archive" button must open `archive/` in the system file manager.
The "Open Quarantine" button must open `quarantine/` in the system file manager.

```python
# Fix in gui/tabs/ingestion_tab.py:
open_archive_btn = QPushButton("Open Archive")
open_archive_btn.clicked.connect(
    lambda: subprocess.Popen(["xdg-open", str(ARCHIVE_DIR)])
)

open_quarantine_btn = QPushButton("Open Quarantine")
open_quarantine_btn.clicked.connect(
    lambda: subprocess.Popen(["xdg-open", str(QUARANTINE_DIR)])
)
```

### 10.3 Pause Button State Text

When the Stop button initiates a graceful stop, the ingestion status label must
display "Pausing..." not "Stopping..." — stopping is a different terminal state.
The process is pausing its loop between documents, not terminating.

```python
# Fix in gui/tabs/ingestion_tab.py, _update_button_states():
if status == "stopping":
    self.status_label.setText("Pausing...")  # was "Stopping..."
    self.pause_btn.setEnabled(False)
    self.stop_btn.setEnabled(False)
```

### 10.4 QComboBox Drop-Down Arrow (Missing from QSS)

The Models dropdown in QueryTab has no visible directional arrow because
`QComboBox::drop-down` is not defined in `theme.qss`. This is a QSS omission.

**Required addition to `gui/styles/theme.qss`:**
```qss
QComboBox::drop-down {
    width: @combo_dropdown_width;
    background-color: @combo_dropdown_bg;
    border-left: 1px solid @color_border;
    border-top-right-radius: @radius_md;
    border-bottom-right-radius: @radius_md;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}

QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid @color_text_secondary;
}

QComboBox::down-arrow:on {
    border-top: 6px solid @color_accent_primary;
}
```

No Python changes required — QSS only.

### 10.5 Models Label Above Dropdown

The QueryTab dropdown has no label above it. Auditors have no visual cue that
the dropdown controls model selection.

```python
# Fix in gui/tabs/query_tab.py, _build_chat_panel():
# Add ABOVE the model_selector QComboBox:
models_label = QLabel("Models")
models_label.setObjectName("labelSecondary")
chat_layout.addWidget(models_label)
chat_layout.addWidget(self.model_selector)
```

No QSS change required. `QLabel#labelSecondary` should already be defined
in `theme.qss` using `@color_text_secondary` and `@font_size_sm`.

### 10.6 Ingestion Telemetry Label Wiring

The "Queue", "Session", "Batch", and "Current file" labels in IngestionTab are
static dead labels. They must update dynamically from the `IngestionWorker`
stdout stream.

**The IngestionWorker must emit structured telemetry lines** that the IngestionTab
can parse. `batch_coordinator.py` should already print these — if not, add them.

**Required stdout format from batch_coordinator.py:**
```
[TELEMETRY] session=3 batch=47 total=142 remaining=95 file=014. AS 16 Borrowing Costs.pdf stage=Stage 2 — Embedding
```

**IngestionWorker parsing — add to `on_log_line` slot:**
```python
@pyqtSlot(str)
def on_log_line(self, line: str) -> None:
    # Append to log view (existing behaviour)
    self._append_log(line)

    # Parse structured telemetry lines
    if line.startswith("[TELEMETRY]"):
        parts = {}
        for token in line.replace("[TELEMETRY]", "").strip().split():
            if "=" in token:
                k, v = token.split("=", 1)
                parts[k] = v
        if "session" in parts:
            self.session_label.setText(parts["session"])
        if "batch" in parts and "total" in parts:
            self.batch_label.setText(f"{parts['batch']}/{parts['total']}")
        if "remaining" in parts:
            remaining = int(parts["remaining"])
            total = int(parts.get("total", "0") or "0")
            if total > 0:
                self.queue_label.setText(f"{remaining} remaining / {total} total")
        if "file" in parts:
            self.current_file_label.setText(parts["file"])
        if "stage" in parts:
            self.current_stage_label.setText(parts["stage"].replace("-", "—"))
```

**batch_coordinator.py must emit telemetry lines.** Add before processing each file:
```python
# In batch_coordinator.py, inside the processing loop:
print(
    f"[TELEMETRY] session={session_num} batch={batch_num} "
    f"total={total_files} remaining={remaining} "
    f"file={filename} stage=Stage 1 — Parsing",
    flush=True
)
```

Emit a new `[TELEMETRY]` line at the start of each stage (Parsing, Embedding,
Graph, Indexing) so the GUI updates as stages progress within each document.
