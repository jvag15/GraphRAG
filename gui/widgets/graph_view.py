"""
GraphView — QWebEngineView wrapper rendering knowledge_graph.json as a PyVis network.

Includes QWebChannel bridge for Python→JavaScript node highlighting.
The core verification feature: after a query, the LLM-used nodes are
highlighted and the camera pans/zooms to them.

Graph HTML generation runs in a background QThread to avoid blocking
the GUI thread (knowledge_graph.json can be 50MB+).
"""

import json
import tempfile
from pathlib import Path

from pyvis.network import Network
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QUrl


def build_graph_html(graph_json_path: Path) -> str:
    """Load knowledge_graph.json and generate a full PyVis HTML string.

    This function does file I/O and should be called from a QThread,
    never from the GUI thread.
    """
    with open(graph_json_path, encoding="utf-8") as f:
        data = json.load(f)

    net = Network(
        height="100%",
        width="100%",
        bgcolor="rgb(30, 30, 46)",  # color_bg_base resolved
        font_color="rgb(205, 214, 244)",  # color_text_primary resolved
        directed=True,
    )
    net.set_options(
        json.dumps(
            {
                "physics": {
                    "enabled": True,
                    "stabilization": {"iterations": 150, "fit": True},
                    "barnesHut": {
                        "gravitationalConstant": -8000,
                        "springLength": 95,
                    },
                },
                "interaction": {
                    "hover": True,
                    "tooltipDelay": 100,
                    "navigationButtons": False,
                    "keyboard": {"enabled": True},
                },
                "edges": {"smooth": {"type": "curvedCW", "roundness": 0.2}},
                "nodes": {"borderWidth": 2, "borderWidthSelected": 4},
            }
        )
    )

    # Add nodes with type-based colouring
    type_colors = {
        "standard": "rgb(137, 180, 250)",  # accent_primary
        "concept": "rgb(166, 227, 161)",  # accent_success
        "provision": "rgb(249, 226, 175)",  # accent_warning
        "entity": "rgb(203, 166, 247)",  # mauve
    }

    for node in data.get("nodes", []):
        # Handle both node-link format and internal NetworkX format
        if isinstance(node, list) and len(node) >= 2:
            node_data = node[1]
        else:
            node_data = node
        nid = str(node_data.get("id", ""))
        label = node_data.get("label", "")
        ntype = node_data.get("type", "entity")
        color = type_colors.get(ntype, "rgb(205, 214, 244)")
        if nid and label:
            net.add_node(nid, label=label, color=color, title=ntype, size=20)

    for edge in data.get("edges", []):
        # Handle both formats
        if isinstance(edge, list) and len(edge) >= 3:
            src, tgt = str(edge[0]), str(edge[1])
            attrs = edge[2] if len(edge) > 2 else {}
        elif isinstance(edge, dict):
            src = str(edge.get("source", ""))
            tgt = str(edge.get("target", ""))
            attrs = edge
        else:
            continue
        relation = attrs.get("relation", attrs.get("label", ""))
        if src and tgt:
            net.add_edge(src, tgt, label=relation, color="rgb(88, 91, 112)", width=1.5)

    # Generate the HTML and inject QWebChannel bootstrap
    html = net.generate_html()

    # Inject QWebChannel bootstrap and highlight API
    inject_script = """
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
    var pyBridge = null;
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.bridge;
    });

    // Highlight specific nodes and edges — called from Python
    function highlightNodes(nodeIds, edgeIds) {
        if (typeof network === 'undefined') return;
        network.selectNodes(nodeIds, false);
        if (edgeIds && edgeIds.length > 0) {
            network.selectEdges(edgeIds);
        }
        if (nodeIds.length > 0) {
            network.focus(nodeIds[0], {
                scale: 1.2,
                animation: {duration: 800, easingFunction: "easeInOutQuad"}
            });
        }
        // Flash effect: temporarily increase node sizes
        nodeIds.forEach(function(id) {
            if (network.body.data.nodes) {
                try {
                    network.body.data.nodes.update({id: id, size: 35, borderWidth: 4});
                } catch(e) {}
            }
        });
        setTimeout(function() {
            nodeIds.forEach(function(id) {
                if (network.body.data.nodes) {
                    try {
                        network.body.data.nodes.update({id: id, size: 20, borderWidth: 2});
                    } catch(e) {}
                }
            });
        }, 1500);
    }

    // Node click handler — emit signal back to Python
    if (typeof network !== 'undefined') {
        network.on("click", function(params) {
            if (params.nodes.length > 0 && pyBridge) {
                pyBridge.on_node_clicked(params.nodes[0]);
            }
        });
    }
    </script>
    """
    html = html.replace("</head>", inject_script + "\n</head>")

    return html


class GraphBridge(QObject):
    """Exposed to JavaScript via QWebChannel for bidirectional communication."""

    node_clicked = pyqtSignal(str)

    @pyqtSlot(str)
    def on_node_clicked(self, node_id: str) -> None:
        """Called from JavaScript when a node is clicked in the graph."""
        self.node_clicked.emit(node_id)


class GraphView(QWidget):
    """QWebEngineView wrapper that renders the knowledge graph as PyVis HTML."""

    node_selected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._web = QWebEngineView()
        self._channel = QWebChannel()
        self._bridge = GraphBridge()
        self._channel.registerObject("bridge", self._bridge)
        self._web.page().setWebChannel(self._channel)
        self._bridge.node_clicked.connect(self.node_selected)

        self._temp_path: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._web)

    def load_graph(self, graph_json_path: Path) -> None:
        """Build PyVis HTML and load it. MUST be called from a QThread only."""
        html = build_graph_html(graph_json_path)
        # Write to temp file — QWebEngineView needs a file:// URL for local resources
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(html)
            f.flush()
            self._temp_path = f.name
        self._web.load(QUrl.fromLocalFile(self._temp_path))

    def load_html(self, html: str) -> None:
        """Load pre-built HTML string directly into the web view."""
        # Write to temp file for proper resource loading
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as f:
            f.write(html)
            f.flush()
            self._temp_path = f.name
        self._web.load(QUrl.fromLocalFile(self._temp_path))

    def highlight_nodes(
        self, node_ids: list[str], edge_ids: list[str] | None = None
    ) -> None:
        """Call JavaScript highlight function from Python."""
        ids_json = json.dumps(node_ids)
        edge_json = json.dumps(edge_ids or [])
        self._web.page().runJavaScript(
            f"highlightNodes({ids_json}, {edge_json});"
        )

    def show_placeholder(self) -> None:
        """Show placeholder text when no graph data is available."""
        self._web.setHtml(
            "<body style='background:rgb(30, 30, 46);color:rgb(88, 91, 112);'"
            "display:flex;align-items:center;justify-content:center;"
            "height:100vh;font-family:system-ui;font-size:14px;'>"
            "Knowledge graph will appear here after a query is submitted.</body>"
        )

    def cleanup_temp(self) -> None:
        """Remove temporary HTML file if it exists."""
        if self._temp_path:
            try:
                import os
                os.unlink(self._temp_path)
            except OSError:
                pass
            self._temp_path = None
