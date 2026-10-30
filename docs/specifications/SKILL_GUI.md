# SKILL_GUI.md — PyQt6 Master Control Application
# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine
# SUPERSEDES: SKILL.md and SKILL_INGESTION_MONITOR.md
# Read CLAUDE.md, AGENTS.md, FRONTEND.md before this file.

---

## WHAT THIS FILE IS

Production-grade build specification for the native PyQt6 desktop application.
This is the master command-and-control interface for the entire GraphRAG pipeline.
It runs natively on the Arch Linux host — same physical machine as the pipeline.

This document supersedes the previous SKILL.md and SKILL_INGESTION_MONITOR.md.
Those files described a simpler HTTP-client GUI. This specification describes the
full native control application with direct kernel-level hooks, filesystem watchers,
IPC state management, and hardware telemetry.

---

## CORE DESIGN PRINCIPLES

**No polling the FastAPI.** Ingestion control, state tracking, hardware telemetry,
and filesystem monitoring all operate through direct OS-level interfaces — not HTTP.
The only HTTP call in the entire application is the query POST to port 8000.

**The Qt event loop must never block.** Every I/O operation, every hardware poll,
every file read, every subprocess call lives in a QThread or QRunnable. The GUI
thread does nothing except render and respond to signals. This is mandatory for
144Hz display smoothness.

**State via local JSON.** The shared state between the GUI and the backend processes
is a single JSON file on disk. The GUI writes flags to it. The backend reads it.
No sockets, no pipes, no shared memory — just a watched file.

---

## FILE STRUCTURE

```
/home/graphrag-automation/graphrag_engine/gui/
├── __init__.py
├── main.py                      ← QMainWindow, QTabWidget, mutual exclusion
├── state/
│   ├── __init__.py
│   └── state_manager.py         ← JSON state file reader/writer
├── tabs/
│   ├── __init__.py
│   ├── ingestion_tab.py         ← Tab 1: controls + telemetry
│   └── query_tab.py             ← Tab 2: chat + graph visualiser
├── workers/
│   ├── __init__.py
│   ├── ingestion_worker.py      ← QThread: launches batch_coordinator subprocess
│   ├── telemetry_worker.py      ← QThread: pynvml + psutil hardware polling
│   └── query_worker.py          ← QThread: HTTP POST to port 8000
├── widgets/
│   ├── __init__.py
│   ├── spell_edit.py            ← QTextEdit subclass with live spellcheck
│   ├── graph_view.py            ← QWebEngineView wrapper + QWebChannel bridge
│   └── mutual_exclusion_dialog.py ← Modal VRAM conflict dialog
└── styles/
    └── theme.qss                ← QSS with placeholder design tokens
```

Windows dev path: `graphrag_engine\gui\`

---

## DEPENDENCIES

### System packages (Arch Linux):
```bash
sudo pacman -S --needed python-pyqt6 python-pyqt6-webengine hunspell hunspell-en_us
```

### Python packages (venv):
```bash
pip install PyQt6 PyQt6-WebEngine pyvis httpx pynvml psutil pyspellchecker
```

### Add to requirements.txt:
```
PyQt6>=6.6.0
PyQt6-WebEngine>=6.6.0
pyvis>=0.3.2
httpx>=0.27.0
pynvml>=11.5.0
psutil>=5.9.0
pyspellchecker>=0.7.0
```

---

## BUILD ORDER

Build in this exact order. Each file depends on the previous.

```
1. gui/state/state_manager.py            ← No dependencies
2. gui/styles/theme.qss                  ← No dependencies
3. gui/workers/telemetry_worker.py       ← Depends on: state_manager
4. gui/workers/ingestion_worker.py       ← Depends on: state_manager
5. gui/workers/query_worker.py           ← No project dependencies
6. gui/widgets/spell_edit.py             ← No project dependencies
7. gui/widgets/graph_view.py             ← No project dependencies
8. gui/widgets/mutual_exclusion_dialog.py ← No project dependencies
9. gui/tabs/ingestion_tab.py             ← Depends on: workers, state_manager
10. gui/tabs/query_tab.py                ← Depends on: workers, widgets
11. gui/main.py                          ← Depends on: everything above
```

---

## STEP 1: gui/state/state_manager.py

The single source of truth shared between the GUI and all backend processes.
Reads and writes `data/gui_state.json` relative to the project root.

### State file schema:
```json
{
  "ingestion": {
    "status": "idle",
    "pause_requested": false,
    "stop_requested": false,
    "session_number": 0,
    "batch_number": 0,
    "total_files_at_start": 0,
    "files_remaining": 0,
    "current_file": "",
    "current_stage": "",
    "active_since": null,
    "last_updated": null
  },
  "query": {
    "last_session_id": null,
    "active": false
  }
}
```

Status values for ingestion: `idle` | `running` | `paused` | `stopping` | `error`

### Class: `StateManager`

```python
class StateManager:
    """Read/write the shared gui_state.json file with file locking."""
    
    STATE_PATH = Path(__file__).parent.parent.parent / "data" / "gui_state.json"
    
    @classmethod
    def read(cls) -> dict:
        """Read current state. Returns default state if file does not exist."""
    
    @classmethod
    def write(cls, state: dict) -> None:
        """Atomically write state using temp file + rename to prevent corruption."""
        # Write to gui_state.json.tmp, then os.replace() to gui_state.json
        # os.replace() is atomic on Linux — no partial writes
    
    @classmethod
    def set_pause_requested(cls, value: bool) -> None:
        """Set pause_requested flag. Backend polls this between documents."""
    
    @classmethod  
    def set_stop_requested(cls, value: bool) -> None:
        """Set stop_requested flag. Backend flushes and exits cleanly."""
    
    @classmethod
    def is_ingesting(cls) -> bool:
        """Return True if ingestion status is running or paused."""
        return cls.read()["ingestion"]["status"] in ("running", "paused")
    
    @classmethod
    def reset(cls) -> None:
        """Reset state to idle. Called after ingestion completes or stops."""
```

**Atomic write is mandatory.** The GUI and the batch_coordinator.py may read the
state file simultaneously. A partial write during a crash would corrupt the state.
Use `tempfile.NamedTemporaryFile` + `os.replace()` — Linux guarantees this is atomic.

**batch_coordinator.py must be updated** to read `pause_requested` and `stop_requested`
from this state file between every document. The GUI does not directly kill the process.

---

## STEP 2: gui/styles/theme.qss

The stylesheet uses design token placeholders instead of hardcoded values.
All colour and font decisions are deferred — only token names are defined now.
When the corporate design system is provided, the token values are injected
into the QSS file without touching any Python code.

### Token naming convention:
```qss
/* === DESIGN TOKENS — inject values here when brand is defined === */
/* Token format: @token_name — replaced at runtime by ThemeLoader */

/*
  @color_bg_base          base window background
  @color_bg_surface       card/panel background (slightly lighter)
  @color_bg_surface_alt   alternate row, input background
  @color_border           widget borders
  @color_text_primary     main text
  @color_text_secondary   labels, captions
  @color_accent_primary   primary action buttons, active tabs
  @color_accent_success   success states, online indicator
  @color_accent_warning   paused state, warning
  @color_accent_danger    stop, error, offline indicator
  @font_family_primary    body font
  @font_family_mono       log output, code, telemetry numbers
  @font_size_base         base body size in px
  @font_size_sm           small labels
  @font_size_lg           headers
  @radius_sm              small border radius
  @radius_md              medium border radius
  @spacing_sm             small padding
  @spacing_md             medium padding
*/
```

### ThemeLoader class (in main.py):

```python
class ThemeLoader:
    """Load theme.qss and substitute design tokens with resolved values."""
    
    # Default token values — override when brand is defined
    TOKENS: dict[str, str] = {
        "@color_bg_base":         "#1e1e2e",
        "@color_bg_surface":      "#313244",
        "@color_bg_surface_alt":  "#45475a",
        "@color_border":          "#585b70",
        "@color_text_primary":    "#cdd6f4",
        "@color_text_secondary":  "#a6adc8",
        "@color_accent_primary":  "#89b4fa",
        "@color_accent_success":  "#a6e3a1",
        "@color_accent_warning":  "#f9e2af",
        "@color_accent_danger":   "#f38ba8",
        "@font_family_primary":   "system-ui",
        "@font_family_mono":      "monospace",
        "@font_size_base":        "14px",
        "@font_size_sm":          "12px",
        "@font_size_lg":          "16px",
        "@radius_sm":             "4px",
        "@radius_md":             "6px",
        "@spacing_sm":            "6px",
        "@spacing_md":            "12px",
    }
    
    @classmethod
    def load(cls, qss_path: Path, overrides: dict[str, str] | None = None) -> str:
        """Read QSS file and substitute all @token_name placeholders."""
        tokens = {**cls.TOKENS, **(overrides or {})}
        with open(qss_path) as f:
            qss = f.read()
        for token, value in tokens.items():
            qss = qss.replace(token, value)
        return qss
```

The QSS file itself uses tokens literally:
```qss
QMainWindow, QWidget {
    background-color: @color_bg_base;
    color: @color_text_primary;
    font-family: @font_family_primary;
    font-size: @font_size_base;
}

QPushButton {
    background-color: @color_accent_primary;
    color: @color_bg_base;
    border: none;
    border-radius: @radius_md;
    padding: @spacing_sm @spacing_md;
}
```

---

## STEP 3: gui/workers/telemetry_worker.py

Polls hardware every 1000ms. Runs in a background QThread forever.
Never touches the GUI directly — only emits signals.

### Class: `TelemetryWorker(QThread)`

```python
class TelemetryWorker(QThread):
    telemetry_updated = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self._running = True
        self._nvml_initialized = False
    
    def run(self) -> None:
        """Poll hardware every 1000ms until stopped."""
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
            pynvml.nvmlShutdown()
    
    def _collect(self, handle) -> dict:
        """Collect all hardware and state metrics. Never raises — catches all."""
        result = {
            "gpu_util": 0, "vram_used_gb": 0.0, "vram_total_gb": 12.0,
            "cpu_util": 0.0, "cpu_temp_c": 0.0,
            "ingestion_status": "idle", "current_file": "",
            "current_stage": "", "session_number": 0,
            "batch_number": 0, "total_files": 0, "files_remaining": 0,
        }
        
        # GPU via pynvml (direct NVML — no subprocess, no nvidia-smi parse)
        if handle:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                result["gpu_util"] = util.gpu
                result["vram_used_gb"] = mem.used / 1e9
                result["vram_total_gb"] = mem.total / 1e9
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
        
        # State from gui_state.json
        try:
            state = StateManager.read()["ingestion"]
            result.update({
                "ingestion_status": state.get("status", "idle"),
                "current_file": state.get("current_file", ""),
                "current_stage": state.get("current_stage", ""),
                "session_number": state.get("session_number", 0),
                "batch_number": state.get("batch_number", 0),
                "total_files": state.get("total_files_at_start", 0),
                "files_remaining": state.get("files_remaining", 0),
            })
        except Exception:
            pass
        
        return result
    
    def stop(self) -> None:
        """Signal the polling loop to exit."""
        self._running = False
```

---

## STEP 4: gui/workers/ingestion_worker.py

Manages the ingestion subprocess lifecycle. Does NOT directly run Python ingestion
code — it launches `batch_coordinator.py` as a child process and monitors it.

### Class: `IngestionWorker(QThread)`

```python
class IngestionWorker(QThread):
    log_line = pyqtSignal(str)           # stdout/stderr line from subprocess
    process_started = pyqtSignal()
    process_finished = pyqtSignal(int)   # exit code
    error = pyqtSignal(str)
    
    PROJECT_ROOT = Path("/home/graphrag-automation/graphrag_engine")
    VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"
    
    def run(self) -> None:
        """Launch batch_coordinator.py with required memory env vars."""
        env = os.environ.copy()
        env["LD_PRELOAD"] = "/usr/lib/libjemalloc.so"
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        
        # Snapshot the file count at start time for progress ratio
        staging = Path(env.get("HDD_BASE_PATH",
            "/opt/graphrag/data/ingestion_pool")) / "staging"
        total = len(list(staging.glob("*.pdf")) + list(staging.glob("*.PDF")))
        
        # Write initial state
        state = StateManager.read()
        state["ingestion"]["status"] = "running"
        state["ingestion"]["total_files_at_start"] = total
        state["ingestion"]["files_remaining"] = total
        state["ingestion"]["session_number"] += 1
        state["ingestion"]["pause_requested"] = False
        state["ingestion"]["stop_requested"] = False
        StateManager.write(state)
        
        try:
            self._process = subprocess.Popen(
                [str(self.VENV_PYTHON), "batch_coordinator.py"],
                cwd=str(self.PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            self.process_started.emit()
            
            for line in self._process.stdout:
                self.log_line.emit(line.rstrip())
            
            self._process.wait()
            self.process_finished.emit(self._process.returncode)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            StateManager.reset()
    
    def request_pause(self) -> None:
        """Write pause flag. Backend catches it between documents."""
        StateManager.set_pause_requested(True)
    
    def request_stop(self) -> None:
        """Write stop flag. Backend flushes and exits cleanly."""
        StateManager.set_stop_requested(True)
```

**Force stop / SIGKILL is not exposed to the UI.** The stop button only sets the
flag. The backend is responsible for graceful shutdown. If the backend does not
respond to the stop flag within 120 seconds, the GUI shows a warning — it still
does not SIGKILL. This is a deliberate design choice to prevent database corruption.

---

## STEP 5: gui/workers/query_worker.py

HTTP POST to port 8000. Standard QThread pattern — see FRONTEND.md for the
full implementation. The one addition here is the check against ingestion state.

```python
class QueryWorker(QThread):
    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, query: str, session_id: str | None = None,
                 model_mode: str = "local"):
        super().__init__()
        self.query = query
        self.session_id = session_id
        self.model_mode = model_mode  # "local" | "sonnet" | "gpt-mini"
    
    def run(self) -> None:
        try:
            payload = {"query": self.query, "model_mode": self.model_mode}
            if self.session_id:
                payload["session_id"] = self.session_id
            response = httpx.post(
                f"{API_BASE_URL}/query",
                json=payload,
                timeout=120.0
            )
            response.raise_for_status()
            self.response_ready.emit(response.json())
        except httpx.ConnectError:
            self.error_occurred.emit(
                "Cannot connect to query server on port 8000. "
                "Start the server with: uvicorn src.api.fastapi_service:app --port 8000"
            )
        except Exception as e:
            self.error_occurred.emit(str(e))
```

---

## STEP 6: gui/widgets/spell_edit.py

QTextEdit subclass with live spellchecking. Underlines misspelled words in red.
Right-click context menu shows correction suggestions.

### Class: `SpellCheckHighlighter(QSyntaxHighlighter)`

```python
from spellchecker import SpellChecker

class SpellCheckHighlighter(QSyntaxHighlighter):
    """Highlights misspelled words with a red underline."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self._spell = SpellChecker()
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self._format.setUnderlineColor(QColor("#f38ba8"))  # accent_danger token
    
    def highlightBlock(self, text: str) -> None:
        """Called by Qt whenever a block changes. Mark misspelled words."""
        # Tokenise on word boundaries, skip numbers and single chars
        for match in re.finditer(r"\b[a-zA-Z]{2,}\b", text):
            word = match.group()
            if word.lower() in self._spell.unknown([word.lower()]):
                self.setFormat(match.start(), len(word), self._format)
```

### Class: `SpellEdit(QTextEdit)`

```python
class SpellEdit(QTextEdit):
    """QTextEdit with live spellcheck and right-click suggestion menu."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._spell = SpellChecker()
        self._highlighter = SpellCheckHighlighter(self.document())
    
    def contextMenuEvent(self, event) -> None:
        """Extend the default context menu with spellcheck suggestions."""
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        
        if word and word.lower() in self._spell.unknown([word.lower()]):
            suggestions = list(self._spell.candidates(word) or [])[:6]
            if suggestions:
                menu.insertSeparator(menu.actions()[0])
                for suggestion in reversed(suggestions):
                    action = menu.insertAction(
                        menu.actions()[0],
                        QAction(suggestion, self)
                    )
                    action.triggered.connect(
                        lambda checked, s=suggestion, c=cursor:
                        self._replace_word(c, s)
                    )
                menu.insertSeparator(menu.actions()[0])
        
        menu.exec(event.globalPos())
    
    def _replace_word(self, cursor: QTextCursor, replacement: str) -> None:
        cursor.insertText(replacement)
```

---

## STEP 7: gui/widgets/graph_view.py

QWebEngineView wrapper that renders the full knowledge_graph.json as an interactive
PyVis network, with a QWebChannel bridge for Python→JavaScript node highlighting.

### PyVis HTML generation:

```python
def build_graph_html(graph_json_path: Path) -> str:
    """Load knowledge_graph.json and generate a full PyVis HTML string."""
    with open(graph_json_path) as f:
        data = json.load(f)
    
    net = Network(
        height="100%", width="100%",
        bgcolor="@color_bg_base",        # token — resolved at build time
        font_color="@color_text_primary",
        directed=True
    )
    net.set_options(json.dumps({
        "physics": {
            "enabled": True,
            "stabilization": {"iterations": 150, "fit": True},
            "barnesHut": {"gravitationalConstant": -8000, "springLength": 95}
        },
        "interaction": {
            "hover": True,
            "tooltipDelay": 100,
            "navigationButtons": False,  # custom controls in Qt toolbar
            "keyboard": {"enabled": True}
        },
        "edges": {"smooth": {"type": "curvedCW", "roundness": 0.2}},
        "nodes": {"borderWidth": 2, "borderWidthSelected": 4}
    }))
    
    # Add nodes with type-based colouring (using token names resolved to hex)
    type_colors = {
        "standard":  "#89b4fa",   # @color_accent_primary
        "concept":   "#a6e3a1",   # @color_accent_success
        "provision": "#f9e2af",   # @color_accent_warning
        "entity":    "#cba6f7",   # mauve
    }
    for node in data.get("nodes", []):
        node_data = node[1] if isinstance(node, list) else node
        net.add_node(
            str(node_data.get("id", "")),
            label=node_data.get("label", ""),
            color=type_colors.get(node_data.get("type", "entity"), "#cdd6f4"),
            title=node_data.get("type", ""),
            size=20
        )
    
    for src, tgt, attrs in data.get("edges", []):
        net.add_edge(str(src), str(tgt),
                     label=attrs.get("relation", ""),
                     color="#585b70", width=1.5)
    
    # Inject QWebChannel bootstrap and highlight API into the HTML
    html = net.generate_html()
    html = html.replace("</head>",
        """
        <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script>
        var pyBridge = null;
        new QWebChannel(qt.webChannelTransport, function(channel) {
            pyBridge = channel.objects.bridge;
        });
        
        // Highlight specific nodes and edges — called from Python
        function highlightNodes(nodeIds, edgeIds) {
            if (!network) return;
            network.selectNodes(nodeIds, false);
            network.selectEdges(edgeIds);
            if (nodeIds.length > 0) {
                network.focus(nodeIds[0], {
                    scale: 1.2,
                    animation: {duration: 800, easingFunction: "easeInOutQuad"}
                });
            }
            // Flash effect: temporarily increase node sizes
            var origPositions = network.getPositions(nodeIds);
            nodeIds.forEach(function(id) {
                network.body.data.nodes.update({id: id, size: 35, borderWidth: 4});
            });
            setTimeout(function() {
                nodeIds.forEach(function(id) {
                    network.body.data.nodes.update({id: id, size: 20, borderWidth: 2});
                });
            }, 1500);
        }
        
        // physics driven by requestAnimationFrame — 144Hz native
        </script>
        </head>
        """
    )
    return html
```

### Class: `GraphBridge(QObject)`
```python
class GraphBridge(QObject):
    """Exposed to JavaScript via QWebChannel."""
    node_clicked = pyqtSignal(str)   # emitted when JS clicks a node
    
    @pyqtSlot(str)
    def on_node_clicked(self, node_id: str) -> None:
        self.node_clicked.emit(node_id)
```

### Class: `GraphView(QWidget)`

```python
class GraphView(QWidget):
    node_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._web = QWebEngineView()
        self._channel = QWebChannel()
        self._bridge = GraphBridge()
        self._channel.registerObject("bridge", self._bridge)
        self._web.page().setWebChannel(self._channel)
        self._bridge.node_clicked.connect(self.node_selected)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._web)
    
    def load_graph(self, graph_json_path: Path) -> None:
        """Build PyVis HTML and load it. Runs in a QThread to avoid blocking."""
        html = build_graph_html(graph_json_path)
        # Write to temp file — QWebEngineView needs a file:// URL for local resources
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False,
                                         mode="w", encoding="utf-8") as f:
            f.write(html)
            f.flush()
            self._temp_path = f.name
        self._web.load(QUrl.fromLocalFile(self._temp_path))
    
    def highlight_nodes(self, node_ids: list[str],
                        edge_ids: list[str] | None = None) -> None:
        """Call JavaScript highlight function from Python."""
        ids_json = json.dumps(node_ids)
        edge_json = json.dumps(edge_ids or [])
        self._web.page().runJavaScript(
            f"highlightNodes({ids_json}, {edge_json});"
        )
    
    def show_placeholder(self) -> None:
        self._web.setHtml(
            "<body style='background:#1e1e2e;color:#585b70;"
            "display:flex;align-items:center;justify-content:center;"
            "height:100vh;font-family:system-ui;font-size:14px;'>"
            "Knowledge graph will appear here after a query is submitted.</body>"
        )
```

---

## STEP 8: gui/widgets/mutual_exclusion_dialog.py

Modal dialog shown when user tries to submit a query while ingestion is running.
**Exact string required** — do not paraphrase.

```python
class MutualExclusionDialog(QDialog):
    """Shown when query is attempted during active ingestion."""
    
    action_stop = pyqtSignal()
    action_pause = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("VRAM Conflict")
        self.setFixedWidth(480)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Required exact string
        msg = QLabel(
            "Ingestion is currently taking place.\n"
            "To Send a query kindly pause or stop the ingestion process."
        )
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg)
        
        btn_row = QHBoxLayout()
        
        stop_btn = QPushButton("Stop Ingestion")
        stop_btn.clicked.connect(self._on_stop)
        
        pause_btn = QPushButton("Pause Ingestion")
        pause_btn.clicked.connect(self._on_pause)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        btn_row.addWidget(stop_btn)
        btn_row.addWidget(pause_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
    
    def _on_stop(self) -> None:
        self.action_stop.emit()
        self.accept()
    
    def _on_pause(self) -> None:
        self.action_pause.emit()
        self.accept()
```

---

## STEP 9: gui/tabs/ingestion_tab.py

### Layout:

```
┌─────────────────────────────────────────────────────────────────────┐
│  INGESTION CONTROLS                                                   │
│  [▶ Start]  [⏸ Pause]  [■ Stop]          ← QButtonGroup, state-aware│
│                                                                      │
│  Queue: 142 files  │  Session: 3  │  Batch: 47/142                  │
│  Current file: 014. AS 16 Borrowing Costs.pdf                       │
│  Current stage: Stage 3 — Graph Construction                        │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  HARDWARE TELEMETRY                    (updates every 1000ms)         │
│                                                                      │
│  GPU Compute   [████████░░░░░░░░░░░░] 45%                           │
│  VRAM          [████████████░░░░░░░░] 8.4 / 12.0 GB                 │
│  CPU           [████░░░░░░░░░░░░░░░░] 22%                           │
│  CPU Temp      63°C                                                  │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  LIVE LOG                                                             │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ [11:42:03] Stage 1: Parsing: 014. AS 16 Borrowing Costs.pdf  │  │
│  │ [11:42:11] Stage 2: Embedding 847 chunks...                   │  │
│  │ [11:42:44] Stage 3: Graph construction — 0/847 chunks         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│  [Clear Log]                                                         │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  DIRECTORY WATCHER          /mnt/parameter-archives/.../staging/     │
│  Staging: 142 files   Archive: 1,847 files   Quarantine: 3 files    │
│  [Open Staging]  [Open Quarantine]  [View Error Logs]               │
└─────────────────────────────────────────────────────────────────────┘
```

### Control button state machine:

| Ingestion Status | Start | Pause | Stop |
|---|---|---|---|
| idle | enabled | disabled | disabled |
| running | disabled | enabled | enabled |
| paused | enabled (resumes) | disabled | enabled |
| stopping | disabled | disabled | disabled (greyed, "Stopping...") |

### QFileSystemWatcher setup:

```python
self._watcher = QFileSystemWatcher()
self._watcher.addPath(str(STAGING_DIR))
self._watcher.addPath(str(ARCHIVE_DIR))
self._watcher.addPath(str(QUARANTINE_DIR))
self._watcher.directoryChanged.connect(self._on_directory_changed)
```

Fires `_on_directory_changed` when any file is added or removed. Triggers
a recount of files in each directory and updates the directory status labels.

### Telemetry update slot:

```python
@pyqtSlot(dict)
def on_telemetry_updated(self, data: dict) -> None:
    """Receives TelemetryWorker signal every 1000ms. Updates all widgets."""
    self.gpu_bar.setValue(data["gpu_util"])
    self.vram_bar.setValue(int(data["vram_used_gb"] / data["vram_total_gb"] * 100))
    self.vram_label.setText(f"{data['vram_used_gb']:.1f} / {data['vram_total_gb']:.0f} GB")
    self.cpu_bar.setValue(int(data["cpu_util"]))
    self.cpu_temp_label.setText(f"{data['cpu_temp_c']:.0f}°C")
    
    self.session_label.setText(str(data["session_number"]))
    self.batch_label.setText(f"{data['batch_number']}/{data['total_files']}")
    self.current_file_label.setText(data["current_file"] or "—")
    self.current_stage_label.setText(data["current_stage"] or "—")
    
    self._update_button_states(data["ingestion_status"])
```

### Live log:

```python
# QTextEdit, read-only, monospace font, max 1000 lines
@pyqtSlot(str)
def on_log_line(self, line: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    self.log_view.append(f"[{timestamp}] {line}")
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
```

---

## STEP 10: gui/tabs/query_tab.py

### Layout:

```
┌──────────────────┬───────────────────────────────────────────────────┐
│  CHAT (25% W)    │  KNOWLEDGE GRAPH (75% W)                          │
│                  │                                                    │
│  Model:          │  [Physics-based PyVis network]                    │
│  [Qwen3.6 ▼]    │  Nodes auto-highlight after each query            │
│  (Sonnet — off)  │  Click any node for details                       │
│  (GPT-mini— off) │                                                    │
│                  │                                                    │
│  [Chat history]  │                                                    │
│  QScrollArea     │                                                    │
│                  │                                                    │
│  ─────────────── │  ────────────────────────────────────────────────│
│  [SpellEdit]     │  SOURCES                                           │
│  [Submit][Clear] │  [tab: Vector Sources] [tab: Graph Path]          │
│  [progress bar]  │                                                    │
└──────────────────┴───────────────────────────────────────────────────┘
```

### Model Selector:

```python
self.model_selector = QComboBox()
self.model_selector.addItem("Qwen3.6-12B (Local)", "local")
self.model_selector.addItem("Claude Sonnet ◈ coming soon", "sonnet")
self.model_selector.addItem("GPT-mini ◈ coming soon", "gpt-mini")

# Make placeholder items visually distinct and non-selectable
class ModelDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.row() > 0:
            option.palette.setColor(QPalette.ColorRole.Text,
                QColor("#585b70"))  # @color_border — dimmed
        super().paint(painter, option, index)

self.model_selector.setItemDelegate(ModelDelegate(self.model_selector))

# Prevent selecting disabled items
def on_model_index_changed(idx: int) -> None:
    if idx > 0:
        self.model_selector.setCurrentIndex(0)
self.model_selector.currentIndexChanged.connect(on_model_index_changed)
```

### Query submission with mutual exclusion check:

```python
def on_submit_clicked(self) -> None:
    query = self.input_edit.toPlainText().strip()
    if not query:
        return
    
    # Mutual exclusion check
    if StateManager.is_ingesting():
        dlg = MutualExclusionDialog(self)
        dlg.action_stop.connect(self._request_ingestion_stop)
        dlg.action_pause.connect(self._request_ingestion_pause)
        dlg.exec()
        return
    
    self._submit_query(query)

def _submit_query(self, query: str) -> None:
    self.input_edit.setEnabled(False)
    self.submit_btn.setEnabled(False)
    self.progress_bar.setVisible(True)
    self.progress_bar.setRange(0, 0)  # indeterminate
    
    self._worker = QueryWorker(query, self.current_session_id, "local")
    self._worker.response_ready.connect(self.on_response_received)
    self._worker.error_occurred.connect(self.on_error)
    self._worker.finished.connect(self._on_query_finished)
    self._worker.start()
```

### Graph highlighting after query response:

```python
@pyqtSlot(dict)
def on_response_received(self, data: dict) -> None:
    answer = data.get("answer", "")
    sources = data.get("sources", [])
    graph_nodes = data.get("graph_nodes", [])
    graph_edges = data.get("graph_edges", [])
    session_id = data.get("session_id")
    
    if session_id:
        self.current_session_id = session_id
    
    self.chat_history.add_ai_message(answer)
    self.source_panel.populate(sources, graph_nodes, graph_edges)
    
    # Highlight the nodes the LLM used — the core verification feature
    if graph_nodes:
        node_ids = [str(n["id"]) for n in graph_nodes]
        edge_ids = [str(e.get("id", "")) for e in graph_edges]
        self.graph_view.highlight_nodes(node_ids, edge_ids)
    
    # If graph data was returned and graph hasn't been loaded yet, load it
    if graph_nodes and not self._graph_loaded:
        self._load_full_graph()
```

### Full graph loading (background thread, not blocking):

```python
def _load_full_graph(self) -> None:
    """Load knowledge_graph.json in a background thread, then render."""
    graph_path = Path("/home/graphrag-automation/graphrag_engine/data/knowledge_graph.json")
    if not graph_path.exists():
        return
    
    class GraphLoader(QThread):
        html_ready = pyqtSignal(str)
        def run(self_):
            html = build_graph_html(graph_path)
            self_.html_ready.emit(html)
    
    self._graph_loader = GraphLoader()
    self._graph_loader.html_ready.connect(
        lambda html: self.graph_view._web.setHtml(html)
    )
    self._graph_loader.start()
    self._graph_loaded = True
```

---

## STEP 11: gui/main.py

```python

class GraphRAGApp(QMainWindow):
    """Master control interface for the GraphRAG pipeline."""
    
    def __init__(self):
        super().__init__()
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
        
        self.setWindowTitle("GraphRAG Control — GraphRAG Platform")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)
        
        # Load and apply stylesheet with design token substitution
        qss_path = Path(__file__).parent / "styles" / "theme.qss"
        if qss_path.exists():
            self.setStyleSheet(ThemeLoader.load(qss_path))
        
        # Build tabs
        self._ingestion_tab = IngestionTab()
        self._query_tab = QueryTab()
        
        tabs = QTabWidget()
        tabs.addTab(self._ingestion_tab, "⚙ Ingestion")
        tabs.addTab(self._query_tab, "🔍 Query")
        self.setCentralWidget(tabs)
        
        # Wire mutual exclusion: query tab needs to signal ingestion tab
        self._query_tab.ingestion_stop_requested.connect(
            self._ingestion_tab.on_stop_requested
        )
        self._query_tab.ingestion_pause_requested.connect(
            self._ingestion_tab.on_pause_requested
        )
        
        # Start telemetry worker (runs for the lifetime of the application)
        self._telemetry = TelemetryWorker()
        self._telemetry.telemetry_updated.connect(
            self._ingestion_tab.on_telemetry_updated
        )
        self._telemetry.start()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def closeEvent(self, event) -> None:
        """Clean shutdown — stop telemetry worker before closing."""
        self._telemetry.stop()
        self._telemetry.wait(3000)
        super().closeEvent(event)


def main() -> None:
    """Entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("GraphRAG Control")
    app.setOrganizationName("GraphRAG Platform")
    window = GraphRAGApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

---

## BACKEND CHANGES REQUIRED

Two changes to backend files are needed to support this GUI.
These are Coder agent tasks — do not do them inside the GUI code.

**1. batch_coordinator.py** must poll `gui_state.json` between every document:
```python
# After processing each file, before starting the next:
from gui.state.state_manager import StateManager
state = StateManager.read()["ingestion"]

if state.get("stop_requested"):
    logger.info("Stop requested by GUI. Flushing and exiting.")
    # Flush ChromaDB, save knowledge_graph.json, unload VRAM
    break

while state.get("pause_requested"):
    logger.info("Paused by GUI. Holding VRAM hot.")
    time.sleep(2)
    state = StateManager.read()["ingestion"]
```

**2. batch_coordinator.py** must write progress to `gui_state.json`:
```python
# Update state before processing each file:
s = StateManager.read()
s["ingestion"]["batch_number"] = current_batch
s["ingestion"]["current_file"] = filename
s["ingestion"]["current_stage"] = "Stage 1 — Parsing"
s["ingestion"]["files_remaining"] = remaining_count
StateManager.write(s)
```

---

## 144Hz COMPLIANCE CHECKLIST

Every item here must be true before the application is considered complete:

- [ ] No blocking calls in QApplication.exec() event loop thread
- [ ] All file I/O in workers/ QThreads
- [ ] All HTTP calls in QueryWorker QThread
- [ ] All hardware polling in TelemetryWorker QThread
- [ ] Graph HTML generation in background QThread (not main thread)
- [ ] QTimer intervals: telemetry=1000ms, QFileSystemWatcher=event-driven (no polling)
- [ ] PyVis physics runs in Chromium requestAnimationFrame (no Python intervention)
- [ ] Log view trim runs asynchronously (document operations don't block event loop)
- [ ] StateManager.read() is never called in the main thread except at init

---

## VERIFICATION CHECKLIST

- [ ] `python gui/main.py` launches, GNOME window appears
- [ ] Both tabs are accessible
- [ ] Telemetry values update every second
- [ ] Start button launches batch_coordinator.py, log lines appear
- [ ] Pause sets the flag, backend acknowledges in log
- [ ] Stop sets the flag, backend exits cleanly, state resets to idle
- [ ] QFileSystemWatcher fires when a file is added to staging/
- [ ] Submitting a query while ingesting shows the exact modal text
- [ ] Stop/Pause buttons in modal work and signal the ingestion tab
- [ ] Query worker sends POST to port 8000 without blocking GUI
- [ ] Response populates chat, sources, and graph pane
- [ ] graph_view.highlight_nodes() visually highlights correct nodes
- [ ] Camera pans and zooms to highlighted nodes with animation
- [ ] Model selector shows Qwen active, Sonnet and GPT-mini dimmed and unselectable
- [ ] SpellEdit underlines misspelled words in red
- [ ] Right-click on misspelled word shows correction suggestions
- [ ] Accepting suggestion replaces the word

---

## SCP COMMANDS

```powershell
# Full gui/ directory:
scp -r "graphrag_engine\gui" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/

# Individual files:
scp "graphrag_engine\gui\main.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/
scp "graphrag_engine\gui\tabs\ingestion_tab.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/tabs/
scp "graphrag_engine\gui\tabs\query_tab.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/tabs/
scp "graphrag_engine\gui\workers\ingestion_worker.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/workers/
scp "graphrag_engine\gui\workers\telemetry_worker.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/workers/
scp "graphrag_engine\gui\workers\query_worker.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/workers/
scp "graphrag_engine\gui\widgets\spell_edit.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/widgets/
scp "graphrag_engine\gui\widgets\graph_view.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/widgets/
scp "graphrag_engine\gui\widgets\mutual_exclusion_dialog.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/widgets/
scp "graphrag_engine\gui\state\state_manager.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/state/
scp "graphrag_engine\gui\styles\theme.qss" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/styles/
```
