"""
QueryTab — Tab 2: Chat interface, knowledge graph, model selector, and sources.

Layout:
┌──────────────────┬───────────────────────────────────────────────────┐
│  CHAT (25% W)    │  KNOWLEDGE GRAPH (75% W)                          │
│  Model selector  │                                                   │
│  Chat history    │  (PyVis interactive network)                       │
│  Input + buttons │                                                   │
│  Progress bar    │  ──────────────────────────────────────────────── │
│                  │  SOURCES (Vector Sources / Graph Path tabs)      │
└──────────────────┴───────────────────────────────────────────────────┘

Mutual exclusion: query submission is blocked if ingestion is active.
Full graph loading happens in a background QThread.

NOTE: StateManager.read() is NEVER called from the GUI thread. Status is
received via the telemetry_updated signal from TelemetryWorker.
"""

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QScrollArea,
    QLabel,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QFrame,
    QTextEdit,
    QComboBox,
    QStyledItemDelegate,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPalette

from gui.workers.query_worker import QueryWorker
from gui.widgets.spell_edit import SpellEdit
from gui.widgets.graph_view import GraphView
from gui.widgets.mutual_exclusion_dialog import MutualExclusionDialog
from gui.widgets.accordion_message import AccordionAIMessage, UserMessage
from gui.state.state_manager import StateManager
from gui.services.server_manager import ServerManager


class ModelDelegate(QStyledItemDelegate):
    """Dim non-selectable placeholder items in the model selector."""

    def paint(self, painter, option, index):
        if index.row() > 0:
            from gui.main import ThemeLoader
            dim_color = QColor(ThemeLoader.TOKENS["@color_border"])
            option.palette.setColor(QPalette.ColorRole.Text, dim_color)
        super().paint(painter, option, index)


class QueryTab(QWidget):
    """Chat + knowledge graph + model selector tab."""

    # Signals for mutual exclusion wiring (forwarded to IngestionTab)
    ingestion_stop_requested = pyqtSignal()
    ingestion_pause_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.current_session_id: str | None = None
        self._query_worker: QueryWorker | None = None
        self._graph_loaded = False
        self._graph_loader: QThread | None = None

        # Cache statuses from telemetry signal (avoid GUI thread StateManager reads)
        self._cached_ingestion_status = "idle"
        self._cached_pruning_status = "idle"
        self._cached_query_active = False

        self._setup_ui()

        # ServerManager integration — ensure query server is running
        was_running = ServerManager.ensure_running()
        from gui.api_client import HealthCheckWorker

        self._health_worker = HealthCheckWorker()
        self._health_worker.status_changed.connect(self._on_server_status_changed)
        self._health_worker.start()

        # Disable submit until server is confirmed bound
        if not was_running:
            self.submit_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # UI setup
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setHandleWidth(4)
        main_splitter.setObjectName("mainSplitter")

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 25)
        main_splitter.setStretchFactor(1, 75)
        main_splitter.setSizes([350, 1050])  # default 25/75 split

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # — Model selector —
        self.models_label = QLabel("Models")
        self.models_label.setObjectName("label_secondary")
        layout.addWidget(self.models_label)
        self.model_selector = QComboBox()
        self.model_selector.addItem("Qwen3.6-12B (Local)", "local")
        self.model_selector.addItem("Claude Sonnet ◈ coming soon", "sonnet")
        self.model_selector.addItem("GPT-mini ◈ coming soon", "gpt-mini")
        self.model_selector.setItemDelegate(ModelDelegate(self.model_selector))
        self.model_selector.currentIndexChanged.connect(self._on_model_index_changed)
        layout.addWidget(self.model_selector)

        # — Chat history —
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.setSpacing(6)

        self.chat_scroll.setWidget(self.chat_container)
        layout.addWidget(self.chat_scroll, stretch=1)

        # — Input area —
        input_group = QWidget()
        input_layout = QVBoxLayout(input_group)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self.input_edit = SpellEdit()
        self.input_edit.setPlaceholderText("Enter your legal query…")
        self.input_edit.setMaximumHeight(120)
        input_layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        self.submit_btn = QPushButton("Submit")
        self.clear_btn = QPushButton("Clear")
        self.submit_btn.clicked.connect(self._on_submit_clicked)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        btn_row.addWidget(self.submit_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        input_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate while querying
        self.progress_bar.setVisible(False)
        input_layout.addWidget(self.progress_bar)

        layout.addWidget(input_group)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Graph view (top)
        self.graph_view = GraphView()
        self.graph_view.show_placeholder()

        # Sources (bottom) — tab widget
        self.sources_tabs = QTabWidget()

        # Vector Sources tab
        self.vector_sources_widget = QWidget()
        vs_layout = QVBoxLayout(self.vector_sources_widget)
        vs_layout.setContentsMargins(0, 0, 0, 0)
        self.vector_sources_scroll = QScrollArea()
        self.vector_sources_scroll.setWidgetResizable(True)
        self.vector_sources_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.vector_sources_container = QWidget()
        self.vector_sources_layout = QVBoxLayout(self.vector_sources_container)
        self.vector_sources_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vector_sources_scroll.setWidget(self.vector_sources_container)
        vs_layout.addWidget(self.vector_sources_scroll)
        self.sources_tabs.addTab(self.vector_sources_widget, "Vector Sources")

        # Graph Path tab
        self.graph_path_edit = QTextEdit()
        self.graph_path_edit.setReadOnly(True)
        self.sources_tabs.addTab(self.graph_path_edit, "Graph Path")

        # Vertical splitter for graph + sources
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(self.graph_view)
        right_splitter.addWidget(self.sources_tabs)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([600, 250])
        right_splitter.setObjectName("rightSplitter")

        layout.addWidget(right_splitter)
        return panel

    # ------------------------------------------------------------------ #
    # Telemetry status (receives from TelemetryWorker via signal — NOT direct call)
    # ------------------------------------------------------------------ #

    @pyqtSlot(dict)
    def on_telemetry_updated(self, data: dict) -> None:
        """Update cached ingestion status from telemetry signal.

        This avoids calling StateManager.read() from the GUI thread.
        The telemetry worker runs in a QThread and emits this signal.
        """
        self._cached_ingestion_status = data.get("ingestion_status", "idle")

    # ------------------------------------------------------------------ #
    # Model selector
    # ------------------------------------------------------------------ #

    def _on_model_index_changed(self, idx: int) -> None:
        """Prevent selecting placeholder (disabled) model items."""
        if idx > 0:
            self.model_selector.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    # Server health check
    # ------------------------------------------------------------------ #

    @pyqtSlot(bool)
    def _on_server_status_changed(self, is_online: bool) -> None:
        """Enable/disable submit based on server availability.

        Called by HealthCheckWorker every 30 seconds. If the server goes
        offline, submit is disabled and a warning is shown in the chat.
        """
        if is_online:
            self.submit_btn.setEnabled(True)
        else:
            self.submit_btn.setEnabled(False)
            # Show a one-time warning if server goes offline
            if self._cached_ingestion_status == "idle":
                self._add_chat_message(
                    "⚠ Query server is offline. Attempting to restart…",
                    is_user=False,
                )
                ServerManager.ensure_running()

    # ------------------------------------------------------------------ #
    # Query submission
    # ------------------------------------------------------------------ #

    def _on_submit_clicked(self) -> None:
        query = self.input_edit.toPlainText().strip()
        if not query:
            return

        # Mutual exclusion check — ingestion
        if self._cached_ingestion_status in ("running", "paused"):
            dlg = MutualExclusionDialog("ingesting", self)
            dlg.action_stop.connect(self.ingestion_stop_requested.emit)
            dlg.action_pause.connect(self.ingestion_pause_requested.emit)
            dlg.exec()
            return

        # Mutual exclusion check — pruning
        if StateManager.is_pruning():
            dlg = MutualExclusionDialog("pruning", self)
            dlg.exec()
            return

        self._submit_query(query)

    def _submit_query(self, query: str) -> None:
        self._add_chat_message(query, is_user=True)
        self.input_edit.clear()

        self.input_edit.setEnabled(False)
        self.submit_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

        # Set query active state
        try:
            state = StateManager.read()
            state["query"]["active"] = True
            StateManager.write(state)
        except Exception:
            pass  # Best-effort state update

        model_mode = self.model_selector.currentData() or "local"
        self._query_worker = QueryWorker(query, self.current_session_id, model_mode)
        self._query_worker.response_ready.connect(self._on_response_received)
        self._query_worker.error_occurred.connect(self._on_error_occurred)
        self._query_worker.finished.connect(self._on_query_finished)
        self._query_worker.start()

    def _on_clear_clicked(self) -> None:
        self._clear_chat()
        self.graph_view.show_placeholder()
        self.current_session_id = None

    # ------------------------------------------------------------------ #
    # Response handling
    # ------------------------------------------------------------------ #

    @pyqtSlot(dict)
    def _on_response_received(self, data: dict) -> None:
        answer = data.get("answer", "")
        sources = data.get("sources", [])
        graph_nodes = data.get("graph_nodes", [])
        graph_edges = data.get("graph_edges", [])
        session_id = data.get("session_id")

        if session_id:
            self.current_session_id = session_id

        self._add_chat_message(answer, is_user=False, sources=sources,
                            graph_nodes=graph_nodes)

        # Populate sources
        self._populate_vector_sources(sources)
        self._populate_graph_path(graph_nodes, graph_edges)

        # Highlight graph nodes used by the LLM (core verification feature)
        if graph_nodes:
            node_ids = [str(n["id"]) for n in graph_nodes]
            edge_ids = [str(e.get("id", "")) for e in graph_edges]
            self.graph_view.highlight_nodes(node_ids, edge_ids)

        # Load full knowledge graph if not yet rendered
        if graph_nodes and not self._graph_loaded:
            self._load_full_graph()

    @pyqtSlot(str)
    def _on_error_occurred(self, error_msg: str) -> None:
        self._add_chat_message(f"Error: {error_msg}", is_user=False)

    @pyqtSlot()
    def _on_query_finished(self) -> None:
        self.input_edit.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Clear query active state
        try:
            state = StateManager.read()
            state["query"]["active"] = False
            StateManager.write(state)
        except Exception:
            pass  # Best-effort state update

    # ------------------------------------------------------------------ #
    # Chat helpers
    # ------------------------------------------------------------------ #

    def _add_chat_message(self, text: str, is_user: bool = False,
                          sources: list[dict] | None = None,
                          graph_nodes: list[dict] | None = None) -> None:
        if is_user:
            bubble = UserMessage(text)
        else:
            bubble = AccordionAIMessage(answer_text=text, sources=sources or [],
                                         graph_nodes=graph_nodes or [])
        self.chat_layout.addWidget(bubble)

        # Auto-scroll to bottom
        vbar = self.chat_scroll.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def _clear_chat(self) -> None:
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ------------------------------------------------------------------ #
    # Sources helpers
    # ------------------------------------------------------------------ #

    def _populate_vector_sources(self, sources: list[dict]) -> None:
        # Clear existing
        while self.vector_sources_layout.count():
            item = self.vector_sources_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not sources:
            label = QLabel("No sources found for this query.")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setObjectName("emptySourcesLabel")
            self.vector_sources_layout.addWidget(label)
            return

        for source in sources:
            card = self._build_source_card(source)
            self.vector_sources_layout.addWidget(card)

    def _build_source_card(self, source: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("sourceCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header
        metadata = source.get("metadata", {})
        filename = metadata.get("filename", "Unknown")
        section = metadata.get("section_header", "")
        header = f"{filename}" + (f" — {section}" if section else "")
        header_label = QLabel(header)
        header_label.setObjectName("sourceHeader")
        layout.addWidget(header_label)

        # Score
        score = int(source.get("score", 0) * 100)
        score_label = QLabel(f"Relevance: {score}%")
        score_label.setObjectName("sourceScore")
        layout.addWidget(score_label)

        # Preview
        text = source.get("text", "")
        preview = text[:300] + ("..." if len(text) > 300 else "")
        preview_label = QLabel(preview)
        preview_label.setWordWrap(True)
        preview_label.setObjectName("sourcePreview")
        layout.addWidget(preview_label)

        return card

    def _populate_graph_path(self, nodes: list[dict], edges: list[dict]) -> None:
        if not nodes and not edges:
            self.graph_path_edit.setPlainText("No graph path data available.")
            return

        node_map = {
            str(node.get("id", "")): str(node.get("label", ""))
            for node in nodes
            if node.get("id")
        }
        lines = []
        for edge in edges:
            src = str(edge.get("source", ""))
            tgt = str(edge.get("target", ""))
            relation = str(edge.get("relation", ""))
            if src and tgt:
                src_label = node_map.get(src, src)
                tgt_label = node_map.get(tgt, tgt)
                lines.append(f"{src_label} ——[{relation}]——▶ {tgt_label}")

        self.graph_path_edit.setPlainText(
            "\n".join(lines) if lines else "No path data to display."
        )

    # ------------------------------------------------------------------ #
    # Graph loading (background thread — does NOT block GUI)
    # ------------------------------------------------------------------ #

    def _load_full_graph(self) -> None:
        """Build PyVis HTML in a background thread, then render in the graph view."""
        from gui.widgets.graph_view import build_graph_html

        graph_path = Path(os.environ.get("GRAPH_PATH", "data/knowledge_graph.json"))
        if not graph_path.exists():
            return

        class GraphLoader(QThread):
            html_ready = pyqtSignal(str)

            def run(self_):
                html = build_graph_html(graph_path)
                self_.html_ready.emit(html)

        self._graph_loader = GraphLoader()
        self._graph_loader.html_ready.connect(self.graph_view.load_html)
        self._graph_loader.start()
        self._graph_loaded = True