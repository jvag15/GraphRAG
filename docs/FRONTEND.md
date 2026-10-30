# FRONTEND.md — PyQt6 GraphRAG Desktop Client

# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine

# Read CLAUDE.md, AGENTS.md, and ROUTINES.md before reading this file

---

## WHAT THIS FILE IS

Complete specification for the PyQt6 desktop GUI that runs on the Arch Linux GNOME
desktop. This is the auditor-facing interface. It communicates exclusively with the
FastAPI backend at <http://127.0.0.1:8000>. It is a separate application from the
backend — it does not import anything from src/.

---

## CRITICAL OPERATING CONTEXT

This GUI runs on the SAME physical machine as the FastAPI server — the Arch Linux
server (graphrag-automation@127.0.0.1). The auditor sits at this machine physically.
There is no remote desktop, no web browser, no Streamlit. A native GNOME window
opens directly on the display.

The backend (FastAPI + Qwen routing + BGE + Reranker) is already running as a daemon on
port 8000. The GUI is a pure HTTP client. It never loads any ML models. It never
imports llama_cpp, sentence_transformers, chromadb, or networkx. All intelligence
lives in the backend. The GUI's only job is to present results beautifully and
keep the interface responsive.

Final answer generation is handled by whichever backend is configured:

- **Local testing:** Qwen3.6-12B running on the RTX 3060 via llama-cpp-python
- **Production:** Claude Sonnet (Anthropic API) or GPT-4o-mini (OpenAI API)
The GUI is identical regardless — it just receives the `answer` field in the JSON response.

**This means the VRAM budget is NOT affected by the GUI.** The GUI uses zero VRAM.

---

## FILE STRUCTURE

All GUI files live in:

```
/home/graphrag-automation/graphrag_engine/gui/
├── main.py          ← Main window, layout, widget wiring, entry point
├── api_client.py    ← QThread worker, all HTTP calls, signal definitions
├── styles.qss       ← Complete Qt stylesheet (dark theme)
└── __init__.py      ← Empty, makes gui/ a package
```

Windows dev path: `graphrag_engine\gui\`

These four files are the complete frontend. No other files are needed.
Do not create additional modules unless explicitly planned.

---

## DEPENDENCIES

### System packages (install on Arch Linux server via pacman)

```bash
sudo pacman -S --needed python-pyqt6 python-pyqt6-webengine
```

### Python packages (install in the existing venv)

```bash
source /home/graphrag-automation/graphrag_engine/venv/bin/activate
pip install PyQt6 PyQt6-WebEngine pyvis httpx
```

### Add to requirements.txt

```
PyQt6>=6.6.0
PyQt6-WebEngine>=6.6.0
pyvis>=0.3.2
httpx>=0.27.0
```

---

## LAYOUT SPECIFICATION

### Top-level window

- Class: `GraphRAGMainWindow(QMainWindow)`
- Title: "GraphRAG Legal Discovery — GraphRAG Platform"
- Minimum size: 1400 × 900 pixels
- Default size: 1600 × 1000 pixels
- Layout: `QSplitter(Qt.Orientation.Horizontal)` at the root level

### Pane 1 — Chat Interface (Left, 30% width)

Implemented as `ChatPanel(QWidget)`:

```
┌─────────────────────────────┐
│  [●] GraphRAG Legal          │  ← Header bar with status dot
│  Discovery                   │
├─────────────────────────────┤
│                              │
│  [AI bubble] Answer text...  │  ← QScrollArea containing
│                              │     message history
│       [User bubble] Query    │
│                              │
│  [AI bubble] Next answer...  │
│                              │
├─────────────────────────────┤
│  [QTextEdit multiline input] │  ← Input box, min 4 lines
│                              │
│  [Submit Inquiry] [Clear]    │  ← Buttons
│  [════════════════] (hidden) │  ← QProgressBar, shown on query
└─────────────────────────────┘
```

Status dot: green (#4CAF50) when API healthy, red (#F44336) when offline.
Message bubbles: user messages right-aligned, dark accent background.
AI messages left-aligned, slightly lighter background.
Each message bubble shows timestamp in small text below it.

### Pane 2 — Knowledge Graph Visualizer (Top-right, 70% width, 60% height)

Implemented as `GraphPanel(QWidget)`:

```
┌─────────────────────────────────────────────────────┐
│  Knowledge Graph  [Clear Graph]  [Export PNG]        │
├─────────────────────────────────────────────────────┤
│                                                      │
│          QWebEngineView                              │
│     (renders pyvis HTML graph)                       │
│                                                      │
│   Nodes: AS 16 ──── Borrowing Costs                  │
│               └──── Depreciation                     │
│                                                      │
└─────────────────────────────────────────────────────┘
```

On first launch: shows placeholder text "Submit a query to visualize the knowledge graph."
After a query: renders the sub-graph of nodes/edges returned by the API.
Nodes are colour-coded by entity type (standard, concept, provision, etc.).

### Pane 3 — Source Citation Inspector (Bottom-right, 70% width, 40% height)

Implemented as `SourcePanel(QWidget)`:

```
┌─────────────────────────────────────────────────────┐
│  [Vector Sources] [Graph Path]                       │  ← QTabWidget
├─────────────────────────────────────────────────────┤
│  Vector Sources Tab:                                 │
│  ┌───────────────────────────────────────────────┐  │
│  │ [1] 008. AS 10 Property plant and equipment   │  │
│  │     Section: Depreciation                      │  │
│  │     Score: 0.92                                │  │
│  │     "The depreciable amount of an asset..."    │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  Graph Path Tab:                                     │
│  AS 10 → [GOVERNS] → Depreciation                   │
│  AS 16 → [RELATED_TO] → Borrowing Costs             │
└─────────────────────────────────────────────────────┘
```

---

## API RESPONSE CONTRACT

The GUI expects the FastAPI server to return this structure:

```json
{
  "answer": "string — the full answer text with inline [chunk_id] citations",
  "sources": [
    {
      "chunk_id": "abc123",
      "text": "raw chunk text",
      "score": 0.92,
      "metadata": {
        "source_path": "/path/to/file.pdf",
        "filename": "008. AS 10 Property plant and equipment.pdf",
        "section_header": "Depreciation"
      }
    }
  ],
  "session_id": "uuid-string",
  "has_sufficient_context": true,
  "graph_nodes": [
    {"id": "node_id", "label": "AS 10", "type": "standard"},
    {"id": "node_id2", "label": "Depreciation", "type": "concept"}
  ],
  "graph_edges": [
    {"source": "node_id", "target": "node_id2", "relation": "GOVERNS"}
  ]
}
```

**IMPORTANT:** The current FastAPI backend may not yet return `graph_nodes` and
`graph_edges`. The GUI must handle their absence gracefully — if these keys are
missing from the response, the graph pane shows "No graph data returned for this query."
It must NOT crash. Use `.get("graph_nodes", [])` and `.get("graph_edges", [])`.

The Coder agent responsible for api_client.py must implement this defensively.

---

## CONCURRENCY ARCHITECTURE — THE QTHREAD MANDATE

This is the most important engineering constraint. Violation causes GNOME freeze.

**NEVER** put an HTTP request directly in a button click handler or any GUI event.
The Qwen model takes 15-30 seconds to generate a response. If the HTTP call blocks
the GUI thread, the entire window becomes unresponsive. GNOME will show "Force Quit."

### Correct architecture

```python
# api_client.py
class QueryWorker(QThread):
    response_ready = pyqtSignal(dict)      # emitted on success
    error_occurred = pyqtSignal(str)       # emitted on failure
    
    def __init__(self, query: str, session_id: str | None = None):
        super().__init__()
        self.query = query
        self.session_id = session_id
    
    def run(self):
        # This runs in a background thread — safe to block here
        try:
            payload = {"query": self.query}
            if self.session_id:
                payload["session_id"] = self.session_id
            response = httpx.post(
                "http://127.0.0.1:8000/query",
                json=payload,
                timeout=120.0
            )
            response.raise_for_status()
            self.response_ready.emit(response.json())
        except Exception as e:
            self.error_occurred.emit(str(e))

# main.py — button handler
def on_submit_clicked(self):
    query = self.input_box.toPlainText().strip()
    if not query:
        return
    self.submit_button.setEnabled(False)
    self.progress_bar.setVisible(True)
    
    self.worker = QueryWorker(query, self.current_session_id)
    self.worker.response_ready.connect(self.on_response_received)
    self.worker.error_occurred.connect(self.on_error_received)
    self.worker.finished.connect(self.on_worker_finished)
    self.worker.start()

def on_worker_finished(self):
    self.submit_button.setEnabled(True)
    self.progress_bar.setVisible(False)
```

### Health check worker (separate QThread, runs at startup and every 30 seconds)

```python
class HealthCheckWorker(QThread):
    status_changed = pyqtSignal(bool)  # True = online, False = offline
    
    def run(self):
        try:
            response = httpx.get("http://127.0.0.1:8000/health", timeout=5.0)
            self.status_changed.emit(response.status_code == 200)
        except Exception:
            self.status_changed.emit(False)
```

---

## GRAPH VISUALISATION

Use pyvis to generate an interactive HTML graph, then render it in QWebEngineView.

```python
# In GraphPanel
def render_graph(self, nodes: list, edges: list):
    if not nodes:
        self.web_view.setHtml("<p style='color:#888'>No graph data for this query.</p>")
        return
    
    net = Network(height="100%", width="100%", bgcolor="#1e1e2e", font_color="#cdd6f4")
    net.set_options("""{"physics": {"enabled": true, "stabilization": {"iterations": 100}}}""")
    
    # Colour by node type
    type_colors = {
        "standard": "#89b4fa",    # blue — AS standards
        "concept": "#a6e3a1",     # green — accounting concepts
        "provision": "#fab387",   # peach — legal provisions
        "entity": "#cba6f7",      # mauve — entities
    }
    
    for node in nodes:
        color = type_colors.get(node.get("type", "entity"), "#cdd6f4")
        net.add_node(node["id"], label=node["label"], color=color, size=20)
    
    for edge in edges:
        net.add_edge(edge["source"], edge["target"], 
                     label=edge.get("relation", ""), color="#6c7086")
    
    # Write to temp file and load in webview
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        self.web_view.load(QUrl.fromLocalFile(f.name))
        self._temp_graph_file = f.name
```

---

## STYLESHEET (styles.qss)

The stylesheet must produce a dark, professional, GNOME-native appearance.
Catppuccin Mocha palette is the reference (matches GNOME dark themes):

```
Background (base):     #1e1e2e
Surface:               #313244
Surface variant:       #45475a
Text primary:          #cdd6f4
Text secondary:        #a6adc8
Accent blue:           #89b4fa
Accent green:          #a6e3a1
Accent red:            #f38ba8
Accent yellow:         #f9e2af
Border:                #585b70
```

Key QSS rules to implement:

- `QMainWindow`, `QWidget`: background #1e1e2e, color #cdd6f4
- `QTextEdit`, `QScrollArea`: background #313244, border 1px solid #585b70, border-radius 6px
- `QPushButton`: background #89b4fa, color #1e1e2e, border-radius 6px, padding 8px 16px
- `QPushButton:hover`: background #b4befe
- `QPushButton:disabled`: background #45475a, color #6c7086
- `QTabWidget::pane`: border 1px solid #585b70
- `QTabBar::tab`: background #313244, padding 8px 16px, border-radius 4px 4px 0 0
- `QTabBar::tab:selected`: background #45475a, color #cdd6f4
- `QProgressBar`: border-radius 3px, background #313244
- `QProgressBar::chunk`: background #89b4fa
- `QSplitter::handle`: background #585b70, width 2px

---

## PYVIS BACKEND REQUIREMENT

The FastAPI backend currently does NOT return `graph_nodes` and `graph_edges`.
This needs to be added. The Coder agent assigned to backend changes must:

1. In `src/retrieval/hybrid_search.py`, collect the node IDs of chunks returned
   by graph traversal and add them to the SearchResults dataclass.
2. In `src/api/fastapi_service.py`, add a `graph_nodes` and `graph_edges` field
   to the query response, populated from the search results' graph node IDs.
3. Look up those node IDs in the loaded NetworkX graph to get labels and types.
4. Serialize to the format: `[{"id": str, "label": str, "type": str}]`

This is a backend task, not a frontend task. The frontend GUI must be built to
handle both the presence and absence of this data (defensive parsing).

---

## SESSION MANAGEMENT

The GUI maintains a session_id across turns in a conversation:

- On first query: send `{"query": "..."}` with no session_id
- Parse `session_id` from the response
- On all subsequent queries: send `{"query": "...", "session_id": "uuid"}`
- "Clear" button resets session_id to None, clears the chat history display,
  clears the graph pane, clears the source pane

---

## WHAT THE GUI MUST NEVER DO

- Import anything from `src/` — the GUI is a pure HTTP client
- Load any ML models — zero VRAM usage from the GUI
- Make HTTP calls in the GUI thread — always use QThread
- Hardcode the API URL — read from environment variable `GRAPHRAG_API_URL`
  with fallback `http://127.0.0.1:8000`
- Use `os.system()` or `subprocess` for anything
- Crash when `graph_nodes` or `graph_edges` are missing from the API response
- Crash when the API is offline — show an error state, do not raise unhandled exceptions
- Use Windows paths anywhere in the code

---

## LAUNCH COMMAND

```bash
# Run on server (SSH) or directly on GNOME terminal:
cd /home/graphrag-automation/graphrag_engine
source venv/bin/activate
python gui/main.py
```

Requires an active display (GNOME session). Will not work over SSH without
X11 forwarding or a Wayland socket.
