# SKILL_PHASE2.md — Phase 2 Architecture Blueprint

# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine

# Extends: SKILL_GUI.md

# Read: CLAUDE.md → AGENTS.md → SKILL_GUI.md → this file, in that order

---

## HARDWARE CORRECTION — READ BEFORE ANYTHING ELSE

The Phase 2 directive references "RTX 5050 with 8GB VRAM ceiling." That is the
**Windows dev machine**. The GUI runs on the **Arch Linux server**, which has an
**RTX 3060 with 12GB VRAM**. All VRAM calculations in this document use 12GB.
Do not confuse the two machines. If code appears to target 8GB, it is wrong.

Server: RTX 3060, 12GB VRAM, Intel Xeon W-2125
Dev:    RTX 5050, 8GB VRAM, Ryzen 7 250 AI — code editing only, nothing runs here.

---

## WHAT THIS FILE IS

Phase 2 adds three major pillars to the existing Phase 1 GUI (SKILL_GUI.md):

1. **Granular Graph Pruning** — KnowledgeTab + PruningWorker + prune_document.py
2. **Inline Retrieval Audit Trail** — accordion chat bubble widget
3. **QSS Token Extremism + QSplitter Fluidity** — exhaustive design token system

All Phase 1 constraints remain in full force:

- Qt event loop must never block (144Hz compliance)
- State via atomic writes to data/gui_state.json only
- VRAM mutual exclusion intact and extended to cover pruning operations
- No REST APIs, no sockets, no pipes

---

## NEW FILE STRUCTURE (additions to Phase 1)

```
gui/
├── workers/
│   └── pruning_worker.py          ← NEW: QThread launching prune_document.py
├── tabs/
│   └── knowledge_tab.py           ← NEW: KnowledgeTab (Tab 3)
├── widgets/
│   └── accordion_message.py       ← NEW: Collapsible audit trail chat bubble
└── styles/
    └── theme.qss                  ← EXTENDED: exhaustive token coverage

prune_document.py                  ← NEW: standalone backend script (project root)
```

**Files modified from Phase 1:**

- `gui/state/state_manager.py` — add prune_requests field and helpers
- `gui/widgets/mutual_exclusion_dialog.py` — add pruning conflict state
- `gui/tabs/query_tab.py` — add QSplitter, replace message widget with accordion
- `gui/main.py` — add KnowledgeTab, wire pruning mutual exclusion

---

## EXTENDED MUTUAL EXCLUSION MATRIX

Phase 2 introduces a third system state: **pruning**. The full conflict table:

| User tries to... | While ingesting | While querying | While pruning |
|---|---|---|---|
| Start ingestion | — | BLOCKED (modal) | BLOCKED (modal) |
| Submit query | BLOCKED (modal) | — | BLOCKED (modal) |
| Prune document | BLOCKED (modal) | BLOCKED (modal) | — |

All three blocked states show the same `MutualExclusionDialog`, but with context-aware
text. Add a `conflict_reason` parameter to the dialog constructor:

```python
class MutualExclusionDialog(QDialog):
    MESSAGES = {
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
    
    def __init__(self, conflict_reason: str, parent=None):
        super().__init__(parent)
        # ... message set from MESSAGES[conflict_reason]
        # Buttons shown depend on conflict_reason:
        # "ingesting": [Stop Ingestion] [Pause Ingestion] [Cancel]
        # "querying":  [Cancel]
        # "pruning":   [Cancel]
```

**StateManager additions for pruning:**

```python
# New fields in gui_state.json schema:
{
  "pruning": {
    "status": "idle",        # idle | running | complete | error
    "document_id": "",       # filename being pruned
    "progress_pct": 0,       # 0–100
    "last_message": "",      # latest log line from prune_document.py
    "prune_requests": []     # queue of document IDs awaiting pruning
  }
}

# New StateManager methods:
@classmethod
def queue_prune(cls, document_id: str) -> None:
    """Append document_id to prune_requests array atomically."""

@classmethod
def pop_prune_request(cls) -> str | None:
    """Backend calls this. Atomically removes and returns first request."""

@classmethod
def is_pruning(cls) -> bool:
    return cls.read()["pruning"]["status"] == "running"

@classmethod
def is_system_busy(cls) -> bool:
    """True if ingesting, querying, or pruning."""
    state = cls.read()
    return (
        state["ingestion"]["status"] in ("running", "paused") or
        state["pruning"]["status"] == "running" or
        state["query"]["active"]
    )
```

---

## PILLAR 1: GRANULAR GRAPH PRUNING

### prune_document.py (standalone backend script, project root)

This is a self-contained Python script. It accepts one CLI argument: the document ID
(the PDF filename). It must be runnable standalone:

```bash
python prune_document.py "008. AS 10 Property plant and equipment.pdf"
```

It prints structured log lines to stdout (captured by PruningWorker for the GUI).

```python
#!/usr/bin/env python3
"""
Standalone document pruning script.
Accepts document_id (PDF filename) as CLI argument.
Deletes all vectors, graph nodes, and edges associated with the document.
Moves the PDF from archive/ to pruned/.
All operations are atomic. Prints progress to stdout.
"""
from __future__ import annotations
import sys
import json
import os
import shutil
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
HDD_BASE = Path(os.environ.get("HDD_BASE_PATH",
    "/opt/graphrag/data/ingestion_pool"))
ARCHIVE_DIR = HDD_BASE / "archive"
PRUNED_DIR = HDD_BASE / "pruned"
CHROMA_PATH = DATA_DIR / "chroma_db"
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"


def log(msg: str) -> None:
    """Print flush-forced line for subprocess stdout streaming."""
    print(msg, flush=True)


def prune(document_id: str) -> int:
    """Execute full pruning sequence. Returns 0 on success, 1 on error."""
    log(f"[PRUNE] Starting: {document_id}")
    PRUNED_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: ChromaDB vector deletion
    log("[PRUNE] Step 1/4: Deleting vector embeddings from ChromaDB...")
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_collection(
            os.environ.get("CHROMA_COLLECTION", "legal_chunks")
        )
        # Metadata field "source_path" contains the full path; filename is suffix
        # Also check "filename" metadata field
        results = collection.get(
            where={"$or": [
                {"source_path": {"$contains": document_id}},
                {"filename": document_id}
            ]},
            include=["metadatas"]
        )
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
            log(f"[PRUNE] Deleted {len(ids_to_delete)} vectors.")
        else:
            log("[PRUNE] No vectors found for this document (may already be pruned).")
    except Exception as e:
        log(f"[PRUNE][ERROR] ChromaDB deletion failed: {e}")
        return 1

    # Step 2: BM25 index rebuild (required after vector deletion)
    log("[PRUNE] Step 2/4: Rebuilding BM25 index...")
    try:
        # BM25 is rebuilt from ChromaDB — reimport keyword_index
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.extraction.keyword_index import build_bm25_from_chroma
        build_bm25_from_chroma()
        log("[PRUNE] BM25 index rebuilt.")
    except Exception as e:
        log(f"[PRUNE][WARN] BM25 rebuild failed (non-fatal): {e}")

    # Step 3: Knowledge graph node/edge pruning
    log("[PRUNE] Step 3/4: Pruning knowledge graph nodes and edges...")
    try:
        with open(GRAPH_PATH) as f:
            graph_data = json.load(f)

        nodes_before = len(graph_data.get("nodes", []))
        edges_before = len(graph_data.get("edges", []))

        # Filter out nodes whose source_path contains the document_id
        def node_belongs_to_doc(node) -> bool:
            # Node format: [node_id, {attrs}] for node-link format
            attrs = node[1] if isinstance(node, (list, tuple)) else node
            if isinstance(attrs, dict):
                sp = attrs.get("source_path", "")
                fn = attrs.get("filename", "")
                return document_id in sp or document_id in fn
            return False

        pruned_nodes = [n for n in graph_data.get("nodes", [])
                        if not node_belongs_to_doc(n)]
        surviving_node_ids = set()
        for n in pruned_nodes:
            nid = n[0] if isinstance(n, (list, tuple)) else n.get("id", "")
            surviving_node_ids.add(str(nid))

        # Filter edges: remove any edge where source or target no longer exists
        pruned_edges = []
        for e in graph_data.get("edges", []):
            if isinstance(e, (list, tuple)) and len(e) >= 2:
                src, tgt = str(e[0]), str(e[1])
            elif isinstance(e, dict):
                src, tgt = str(e.get("source", "")), str(e.get("target", ""))
            else:
                continue
            if src in surviving_node_ids and tgt in surviving_node_ids:
                pruned_edges.append(e)

        graph_data["nodes"] = pruned_nodes
        graph_data["edges"] = pruned_edges

        # Atomic write
        with tempfile.NamedTemporaryFile(
            mode="w", dir=DATA_DIR, suffix=".json",
            delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(graph_data, tmp, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, str(GRAPH_PATH))

        log(f"[PRUNE] Nodes: {nodes_before} → {len(pruned_nodes)} "
            f"(-{nodes_before - len(pruned_nodes)})")
        log(f"[PRUNE] Edges: {edges_before} → {len(pruned_edges)} "
            f"(-{edges_before - len(pruned_edges)})")
    except Exception as e:
        log(f"[PRUNE][ERROR] Graph pruning failed: {e}")
        return 1

    # Step 4: Move PDF from archive/ to pruned/
    log("[PRUNE] Step 4/4: Moving PDF to pruned/ directory...")
    try:
        src_path = ARCHIVE_DIR / document_id
        dst_path = PRUNED_DIR / document_id
        if src_path.exists():
            shutil.move(str(src_path), str(dst_path))
            log(f"[PRUNE] Moved to: {dst_path}")
        else:
            log(f"[PRUNE][WARN] PDF not found in archive: {src_path}")
    except PermissionError as e:
        log(f"[PRUNE][ERROR] Permission denied moving PDF: {e}")
        return 1
    except Exception as e:
        log(f"[PRUNE][ERROR] PDF move failed: {e}")
        return 1

    log(f"[PRUNE] Complete: {document_id}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python prune_document.py <document_id>", flush=True)
        sys.exit(1)
    sys.exit(prune(sys.argv[1]))
```

---

### gui/workers/pruning_worker.py

```python
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from gui.state.state_manager import StateManager

PROJECT_ROOT = Path(__file__).parent.parent.parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"


class PruningWorker(QThread):
    """Launches prune_document.py as an isolated subprocess. Streams stdout."""
    
    log_line = pyqtSignal(str)
    progress_updated = pyqtSignal(int)    # 0–100
    prune_complete = pyqtSignal(str, bool) # document_id, success
    
    def __init__(self, document_id: str):
        super().__init__()
        self.document_id = document_id
        self._process = None
    
    def run(self) -> None:
        """Execute prune_document.py in a subprocess. Never raises."""
        state = StateManager.read()
        state["pruning"]["status"] = "running"
        state["pruning"]["document_id"] = self.document_id
        state["pruning"]["progress_pct"] = 0
        StateManager.write(state)
        
        success = False
        try:
            self._process = subprocess.Popen(
                [str(VENV_PYTHON), "prune_document.py", self.document_id],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Never use shell=True — document_id comes from filesystem listing,
                # but defence in depth requires list-form Popen always.
            )
            
            # Parse log lines and infer progress from step numbers
            step_map = {
                "Step 1/4": 10, "Step 2/4": 35,
                "Step 3/4": 60, "Step 4/4": 85, "Complete": 100
            }
            
            for line in self._process.stdout:
                line = line.rstrip()
                self.log_line.emit(line)
                for marker, pct in step_map.items():
                    if marker in line:
                        self.progress_updated.emit(pct)
                        state = StateManager.read()
                        state["pruning"]["progress_pct"] = pct
                        state["pruning"]["last_message"] = line
                        StateManager.write(state)
                        break
            
            self._process.wait()
            success = (self._process.returncode == 0)
        
        except Exception as e:
            self.log_line.emit(f"[PRUNE][FATAL] Worker exception: {e}")
        
        finally:
            state = StateManager.read()
            state["pruning"]["status"] = "complete" if success else "error"
            state["pruning"]["progress_pct"] = 100 if success else 0
            StateManager.write(state)
            self.prune_complete.emit(self.document_id, success)
```

---

### gui/tabs/knowledge_tab.py

```python
from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextEdit, QProgressBar, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QFileSystemWatcher
from PyQt6.QtGui import QColor
from gui.workers.pruning_worker import PruningWorker
from gui.state.state_manager import StateManager

HDD_BASE = Path(os.environ.get("HDD_BASE_PATH",
    "/opt/graphrag/data/ingestion_pool"))
ARCHIVE_DIR = HDD_BASE / "archive"
PRUNED_DIR = HDD_BASE / "pruned"


class ArchiveLoaderWorker(QThread):
    """Reads archive/ directory asynchronously. Never blocks the GUI thread."""
    data_ready = pyqtSignal(list)  # list of (filename, size_bytes, modified_ts)
    
    def run(self) -> None:
        rows = []
        try:
            for p in sorted(ARCHIVE_DIR.glob("*.pdf")) + sorted(ARCHIVE_DIR.glob("*.PDF")):
                stat = p.stat()
                rows.append((p.name, stat.st_size, stat.st_mtime))
        except Exception:
            pass
        self.data_ready.emit(rows)


class KnowledgeTab(QWidget):
    """
    Tab 3: Knowledge Management.
    Lists archived documents. Provides per-row Prune action.
    All pruning delegated to PruningWorker subprocess.
    """
    
    prune_conflict = pyqtSignal(str)  # emitted when prune is blocked — reason string
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._active_worker: PruningWorker | None = None
        self._build_ui()
        self._setup_watcher()
        self._reload_table()
    
    def _build_ui(self) -> None:
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
        self.table.setRowCount(0)
        self.doc_count_label.setText(f"{len(rows)} documents")
        
        for filename, size_bytes, mtime in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            self.table.setItem(row, 0, QTableWidgetItem(filename))
            size_str = (f"{size_bytes / 1024:.1f} KB" if size_bytes < 1_000_000
                        else f"{size_bytes / 1_000_000:.1f} MB")
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
        # Mutual exclusion check
        if StateManager.is_ingesting():
            self.prune_conflict.emit("ingesting")
            return
        if StateManager.read()["query"]["active"]:
            self.prune_conflict.emit("querying")
            return
        if StateManager.is_pruning():
            return  # Already pruning — button should be disabled anyway
        
        # Confirmation dialog
        confirm = QMessageBox.question(
            self, "Confirm Pruning",
            f"Permanently remove all vectors, graph nodes, and edges for:\n\n"
            f"{document_id}\n\n"
            f"The PDF will be moved to pruned/. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        
        self._start_prune(document_id)
    
    def _start_prune(self, document_id: str) -> None:
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
        self.prune_log.append(line)
        self.prune_log.verticalScrollBar().setValue(
            self.prune_log.verticalScrollBar().maximum()
        )
    
    def _on_prune_complete(self, document_id: str, success: bool) -> None:
        if success:
            self.prune_bar.setValue(100)
            self.prune_log.append(f"[OK] Pruning complete: {document_id}")
        else:
            self.prune_log.append(f"[FAIL] Pruning failed. See log above.")
        self._reload_table()
        self._enable_all_prune_buttons()
    
    def _disable_all_prune_buttons(self) -> None:
        for row in range(self.table.rowCount()):
            btn = self.table.cellWidget(row, 3)
            if btn:
                btn.setEnabled(False)
    
    def _enable_all_prune_buttons(self) -> None:
        for row in range(self.table.rowCount()):
            btn = self.table.cellWidget(row, 3)
            if btn:
                btn.setEnabled(True)
```

---

## PILLAR 2: INLINE RETRIEVAL AUDIT TRAIL

### gui/widgets/accordion_message.py

```python
from __future__ import annotations
from datetime import datetime
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QToolButton, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont


class AccordionAIMessage(QFrame):
    """
    AI response chat bubble with collapsible source evidence accordion.
    
    Layout (top to bottom):
      1. Answer text (QLabel, word-wrap, selectable)
      2. Toggle button: "▶ View Source Evidence" / "▼ Hide Source Evidence"
      3. Evidence panel (QTextEdit, hidden by default)
      4. Timestamp
    """
    
    def __init__(self, answer_text: str, sources: list[dict],
                 graph_nodes: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("aiBubble")
        self._sources = sources
        self._expanded = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Answer text — selectable for copy-paste
        self.answer_label = QTextEdit()
        self.answer_label.setReadOnly(True)
        self.answer_label.setObjectName("answerText")
        self.answer_label.setPlainText(answer_text)
        self.answer_label.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.answer_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        # Auto-size height to content
        self.answer_label.document().setDocumentMargin(0)
        self.answer_label.document().contentsChanged.connect(
            self._resize_answer_to_content
        )
        layout.addWidget(self.answer_label)
        
        # Toggle button (only shown if sources exist)
        if sources:
            self.toggle_btn = QToolButton()
            self.toggle_btn.setObjectName("accordionToggle")
            self.toggle_btn.setText("▶  View Source Evidence")
            self.toggle_btn.setCheckable(False)
            self.toggle_btn.clicked.connect(self._toggle_evidence)
            layout.addWidget(self.toggle_btn)
            
            # Evidence panel (hidden by default)
            self.evidence_panel = QTextEdit()
            self.evidence_panel.setReadOnly(True)
            self.evidence_panel.setObjectName("evidencePanel")
            self.evidence_panel.setVisible(False)
            self.evidence_panel.setPlainText(self._format_sources(sources))
            self.evidence_panel.setMaximumHeight(300)
            layout.addWidget(self.evidence_panel)
        
        # Timestamp
        ts = QLabel(datetime.now().strftime("%H:%M:%S"))
        ts.setObjectName("messageTimestamp")
        ts.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(ts)
    
    def _format_sources(self, sources: list[dict]) -> str:
        """Format raw source chunks for the evidence panel."""
        lines = []
        for i, src in enumerate(sources, 1):
            meta = src.get("metadata", {})
            filename = meta.get("filename", meta.get("source_path", "Unknown"))
            section = meta.get("section_header", "")
            score = src.get("score", 0)
            text = src.get("text", "")
            
            lines.append(f"[{i}] {filename}")
            if section:
                lines.append(f"    Section: {section}")
            lines.append(f"    Relevance: {score:.0%}")
            lines.append(f"    ─────────────────────────────")
            lines.append(f"    {text[:500]}{'...' if len(text) > 500 else ''}")
            lines.append("")
        return "\n".join(lines)
    
    def _toggle_evidence(self) -> None:
        self._expanded = not self._expanded
        self.evidence_panel.setVisible(self._expanded)
        
        if self._expanded:
            self.toggle_btn.setText("▼  Hide Source Evidence")
        else:
            self.toggle_btn.setText("▶  View Source Evidence")
        
        # Tell the parent scroll area to recalculate and scroll to this widget
        QTimer.singleShot(10, self._scroll_to_self)
    
    def _scroll_to_self(self) -> None:
        """Find parent QScrollArea and scroll to keep this widget in view."""
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(self, 50, 50)
                break
            parent = parent.parent()
    
    def _resize_answer_to_content(self) -> None:
        doc_height = int(self.answer_label.document().size().height())
        self.answer_label.setFixedHeight(min(doc_height + 10, 600))


class UserMessage(QFrame):
    """User query bubble. Right-aligned. No accordion."""
    
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("userBubble")
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setObjectName("userText")
        ts = QLabel(datetime.now().strftime("%H:%M:%S"))
        ts.setObjectName("messageTimestamp")
        ts.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(label)
        layout.addWidget(ts)
```

---

## PILLAR 3: QSS TOKEN EXTREMISM

### Exhaustive token additions to ThemeLoader.TOKENS

Every new token must be added to `ThemeLoader.TOKENS`. Zero hardcoded values in Python.

```python
# Append to ThemeLoader.TOKENS dict:
TOKENS_EXTENDED = {
    # === SPLITTER ===
    "@splitter_handle_width":    "4px",
    "@splitter_handle_color":    "@color_border",
    "@splitter_handle_hover":    "@color_accent_primary",
    
    # === SCROLLBARS ===
    "@scrollbar_width":          "8px",
    "@scrollbar_track_color":    "@color_bg_surface",
    "@scrollbar_handle_color":   "@color_bg_surface_alt",
    "@scrollbar_handle_hover":   "@color_accent_primary",
    "@scrollbar_arrow_color":    "@color_bg_surface",
    
    # === TABLE / HEADER ===
    "@table_bg":                 "@color_bg_surface",
    "@table_row_alt":            "@color_bg_base",
    "@table_row_selected":       "@color_accent_primary",
    "@table_row_selected_text":  "@color_bg_base",
    "@header_bg":                "@color_bg_surface_alt",
    "@header_text":              "@color_text_secondary",
    "@header_border":            "none",
    "@header_padding":           "8px @spacing_md",
    
    # === COMBOBOX ===
    "@combo_dropdown_width":     "24px",
    "@combo_dropdown_bg":        "@color_bg_surface",
    "@combo_arrow_color":        "@color_text_secondary",
    "@combo_popup_bg":           "@color_bg_surface",
    "@combo_popup_border":       "1px solid @color_border",
    "@combo_item_hover":         "@color_bg_surface_alt",
    
    # === TOOLTIP ===
    "@tooltip_bg":               "@color_bg_surface_alt",
    "@tooltip_border":           "1px solid @color_border",
    "@tooltip_text":             "@color_text_primary",
    "@tooltip_padding":          "@spacing_sm @spacing_md",
    "@tooltip_radius":           "@radius_sm",
    
    # === ACCORDION / EVIDENCE ===
    "@accordion_toggle_bg":      "@color_bg_surface_alt",
    "@accordion_toggle_hover":   "@color_accent_primary",
    "@accordion_toggle_text":    "@color_text_secondary",
    "@accordion_toggle_padding": "@spacing_sm @spacing_md",
    "@accordion_toggle_radius":  "@radius_sm",
    "@evidence_panel_bg":        "@color_bg_base",
    "@evidence_panel_border":    "1px solid @color_border",
    "@evidence_panel_font":      "@font_family_mono",
    "@evidence_panel_size":      "@font_size_sm",
    
    # === CHAT BUBBLES ===
    "@ai_bubble_bg":             "@color_bg_surface",
    "@ai_bubble_border":         "1px solid @color_border",
    "@ai_bubble_radius":         "@radius_md",
    "@ai_bubble_padding":        "@spacing_md",
    "@user_bubble_bg":           "@color_bg_surface_alt",
    "@user_bubble_radius":       "@radius_md",
    "@user_bubble_padding":      "@spacing_md",
    
    # === DANGER BUTTON (Prune) ===
    "@btn_danger_bg":            "@color_accent_danger",
    "@btn_danger_text":          "@color_bg_base",
    "@btn_danger_hover":         "#eb6672",  # lighter danger
    
    # === PROGRESS PANEL ===
    "@progress_panel_bg":        "@color_bg_surface",
    "@progress_panel_border":    "1px solid @color_border",
    "@progress_panel_padding":   "@spacing_md",
    
    # === STATUS INDICATOR DOTS ===
    "@status_dot_size":          "10px",
    "@status_online_color":      "@color_accent_success",
    "@status_offline_color":     "@color_accent_danger",
    "@status_busy_color":        "@color_accent_warning",
}
```

### Exhaustive theme.qss additions (append to existing file)

```qss
/* === SPLITTER === */
QSplitter::handle {
    background-color: @splitter_handle_color;
    width: @splitter_handle_width;
}
QSplitter::handle:hover {
    background-color: @splitter_handle_hover;
}
QSplitter::handle:horizontal { width: @splitter_handle_width; }
QSplitter::handle:vertical   { height: @splitter_handle_width; }

/* === SCROLLBARS === */
QScrollBar:vertical {
    background: @scrollbar_track_color;
    width: @scrollbar_width;
    border: none;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: @scrollbar_handle_color;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: @scrollbar_handle_hover;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    background: @scrollbar_arrow_color;
    height: 0px;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical { background: none; }

/* === TABLE === */
QTableWidget { 
    background-color: @table_bg;
    gridline-color: transparent;
    border: none;
    alternate-background-color: @table_row_alt;
}
QTableWidget::item { padding: @spacing_sm @spacing_md; }
QTableWidget::item:selected {
    background-color: @table_row_selected;
    color: @table_row_selected_text;
}
QHeaderView::section {
    background-color: @header_bg;
    color: @header_text;
    padding: @header_padding;
    border: @header_border;
    font-size: @font_size_sm;
    font-weight: 600;
}
QHeaderView::section:first { border-radius: @radius_sm 0 0 @radius_sm; }

/* === COMBOBOX === */
QComboBox {
    background-color: @color_bg_surface;
    color: @color_text_primary;
    border: 1px solid @color_border;
    border-radius: @radius_md;
    padding: @spacing_sm @spacing_md;
    min-height: 32px;
}
QComboBox::drop-down {
    width: @combo_dropdown_width;
    background-color: @combo_dropdown_bg;
    border-left: 1px solid @color_border;
    border-radius: 0 @radius_md @radius_md 0;
}
QComboBox::down-arrow { color: @combo_arrow_color; }
QComboBox QAbstractItemView {
    background-color: @combo_popup_bg;
    border: @combo_popup_border;
    selection-background-color: @color_accent_primary;
    selection-color: @color_bg_base;
}
QComboBox QAbstractItemView::item:hover { background-color: @combo_item_hover; }

/* === TOOLTIP === */
QToolTip {
    background-color: @tooltip_bg;
    color: @tooltip_text;
    border: @tooltip_border;
    padding: @tooltip_padding;
    border-radius: @tooltip_radius;
}

/* === ACCORDION TOGGLE === */
QToolButton#accordionToggle {
    background-color: @accordion_toggle_bg;
    color: @accordion_toggle_text;
    border: none;
    border-radius: @accordion_toggle_radius;
    padding: @accordion_toggle_padding;
    text-align: left;
    font-size: @font_size_sm;
}
QToolButton#accordionToggle:hover { background-color: @accordion_toggle_hover; color: @color_bg_base; }

/* === EVIDENCE PANEL === */
QTextEdit#evidencePanel {
    background-color: @evidence_panel_bg;
    border: @evidence_panel_border;
    border-radius: @radius_md;
    font-family: @evidence_panel_font;
    font-size: @evidence_panel_size;
    color: @color_text_secondary;
    padding: @spacing_md;
}

/* === CHAT BUBBLES === */
QFrame#aiBubble {
    background-color: @ai_bubble_bg;
    border: @ai_bubble_border;
    border-radius: @ai_bubble_radius;
    padding: @ai_bubble_padding;
    margin-right: 20%;
}
QFrame#userBubble {
    background-color: @user_bubble_bg;
    border-radius: @user_bubble_radius;
    padding: @user_bubble_padding;
    margin-left: 20%;
}
QLabel#messageTimestamp {
    color: @color_text_secondary;
    font-size: @font_size_sm;
}

/* === DANGER BUTTON === */
QPushButton#btnDanger {
    background-color: @btn_danger_bg;
    color: @btn_danger_text;
    border: none;
    border-radius: @radius_md;
    padding: @spacing_sm @spacing_md;
}
QPushButton#btnDanger:hover { background-color: @btn_danger_hover; }
QPushButton#btnDanger:disabled { background-color: @color_bg_surface_alt; color: @color_border; }

/* === PROGRESS PANEL === */
QFrame#progressPanel {
    background-color: @progress_panel_bg;
    border-top: @progress_panel_border;
    padding: @progress_panel_padding;
}
```

---

## QUERY TAB QSPLITTER REFACTOR

Replace the fixed-width layout in `query_tab.py` with:

```python
# In QueryTab.__init__, replace the root layout with:
root_splitter = QSplitter(Qt.Orientation.Horizontal)
root_splitter.setHandleWidth(4)
root_splitter.setObjectName("mainSplitter")

# Left: chat panel (chat history + input)
root_splitter.addWidget(self._build_chat_panel())

# Right: vertical splitter (graph top, sources bottom)
right_splitter = QSplitter(Qt.Orientation.Vertical)
right_splitter.addWidget(self.graph_view)
right_splitter.addWidget(self.source_panel)
right_splitter.setSizes([600, 250])
right_splitter.setObjectName("rightSplitter")
root_splitter.addWidget(right_splitter)

# Default 25/75 split
root_splitter.setSizes([350, 1050])

layout = QVBoxLayout(self)
layout.setContentsMargins(0, 0, 0, 0)
layout.addWidget(root_splitter)
```

---

## PRUNING MUTUAL EXCLUSION — QUERY TAB ADDITION

Add to `QueryTab.on_submit_clicked()`:

```python
# Add after the ingesting check:
if StateManager.is_pruning():
    dlg = MutualExclusionDialog("pruning", self)
    dlg.exec()
    return
```

Add to `StateManager` in query response handling:

```python
# Before starting QueryWorker:
state = StateManager.read()
state["query"]["active"] = True
StateManager.write(state)

# In QueryWorker.finished signal handler:
state = StateManager.read()
state["query"]["active"] = False
StateManager.write(state)
```

---

## MAIN WINDOW ADDITIONS

Add `KnowledgeTab` as Tab 3 in `main.py`:

```python
from gui.tabs.knowledge_tab import KnowledgeTab

self._knowledge_tab = KnowledgeTab()
# Wire pruning conflict signals to mutual exclusion dialog
self._knowledge_tab.prune_conflict.connect(self._on_prune_conflict)
tabs.addTab(self._knowledge_tab, "📚 Knowledge")

def _on_prune_conflict(self, reason: str) -> None:
    dlg = MutualExclusionDialog(reason, self)
    # Wire stop/pause only if reason is "ingesting"
    if reason == "ingesting":
        dlg.action_stop.connect(self._ingestion_tab.on_stop_requested)
        dlg.action_pause.connect(self._ingestion_tab.on_pause_requested)
    dlg.exec()
```

---

## VERIFICATION CHECKLIST — PHASE 2 ADDITIONS

- [ ] KnowledgeTab populates table from archive/ without blocking GUI
- [ ] QFileSystemWatcher fires on archive/ change, table reloads automatically
- [ ] Prune button triggers confirmation dialog before proceeding
- [ ] Prune blocked while ingesting — shows correct modal text
- [ ] Prune blocked while querying — shows correct modal text
- [ ] Query blocked while pruning — shows correct modal text
- [ ] PruningWorker streams stdout to log view in real time
- [ ] Progress bar updates from 0→100 as prune steps complete
- [ ] After pruning: PDF is in pruned/, not in archive/
- [ ] After pruning: ChromaDB no longer contains vectors for that document
- [ ] After pruning: knowledge_graph.json no longer contains nodes for that document
- [ ] AI response renders as AccordionAIMessage, not plain QLabel
- [ ] Evidence panel hidden by default
- [ ] Click "View Source Evidence" expands panel, scrolls to it
- [ ] Click "Hide Source Evidence" collapses panel
- [ ] QSplitter in QueryTab is draggable — chat/graph boundary moves
- [ ] All hardcoded hex codes removed from Python files — only in theme.qss
- [ ] All new widgets use @token names in QSS, not hardcoded values
- [ ] prune_document.py runs as standalone: `python prune_document.py "filename.pdf"`
- [ ] prune_document.py uses atomic write (tempfile + os.replace) for graph JSON
- [ ] No shell=True anywhere in subprocess calls

---

## SCP ADDITIONS FOR PHASE 2

```powershell
scp "graphrag_engine\prune_document.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/
scp "graphrag_engine\gui\workers\pruning_worker.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/workers/
scp "graphrag_engine\gui\tabs\knowledge_tab.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/tabs/
scp "graphrag_engine\gui\widgets\accordion_message.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/widgets/
scp "graphrag_engine\gui\widgets\mutual_exclusion_dialog.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/widgets/
scp "graphrag_engine\gui\tabs\query_tab.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/tabs/
scp "graphrag_engine\gui\state\state_manager.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/state/
scp "graphrag_engine\gui\styles\theme.qss" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/styles/
scp "graphrag_engine\gui\main.py" graphrag-automation@127.0.0.1:/home/graphrag-automation/graphrag_engine/gui/
```
