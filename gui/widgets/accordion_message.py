#!/usr/bin/env python3
"""AccordionAIMessage and UserMessage — Chat bubble widgets with collapsible evidence.

AccordionAIMessage displays AI responses with an optional collapsible source evidence
panel. UserMessage displays user queries as right-aligned bubbles.

# Phase 2 — Audit Trail Chat Bubbles
# GraphRAG Engine — Legal Discovery & Knowledge Engine
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)


class AccordionAIMessage(QFrame):
    """AI response chat bubble with collapsible source evidence accordion.

    Layout (top to bottom):
        1. Answer text (QTextEdit, read-only, auto-sized)
        2. Toggle button: "▶ View Source Evidence" / "▼ Hide Source Evidence"
        3. Evidence panel (QTextEdit, hidden by default, max 300px)
        4. Timestamp
    """

    def __init__(
        self,
        answer_text: str,
        sources: list[dict],
        graph_nodes: list[dict] | None = None,
        parent=None,
    ) -> None:
        """Initialise the accordion message.

        Args:
            answer_text: The AI's answer text.
            sources: List of source chunk dictionaries from the API response.
            graph_nodes: Optional list of graph node dictionaries (unused for now).
            parent: Optional parent widget.
        """
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
            filename = meta.get(
                "filename", meta.get("source_path", "Unknown")
            )
            section = meta.get("section_header", "")
            score = src.get("score", 0)
            text = src.get("text", "")

            lines.append(f"[{i}] {filename}")
            if section:
                lines.append(f"    Section: {section}")
            lines.append(f"    Relevance: {score:.0%}")
            lines.append("    ─────────────────────────────")
            lines.append(
                f"    {text[:500]}{'...' if len(text) > 500 else ''}"
            )
            lines.append("")
        return "\n".join(lines)

    def _toggle_evidence(self) -> None:
        """Toggle the evidence panel visibility."""
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
        """Resize the answer label to fit its content."""
        doc_height = int(self.answer_label.document().size().height())
        self.answer_label.setFixedHeight(min(doc_height + 10, 600))


class UserMessage(QFrame):
    """User query bubble. Right-aligned. No accordion."""

    def __init__(self, text: str, parent=None) -> None:
        """Initialise the user message.

        Args:
            text: The user's query text.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("userBubble")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setObjectName("userText")
        layout.addWidget(label)

        ts = QLabel(datetime.now().strftime("%H:%M:%S"))
        ts.setObjectName("messageTimestamp")
        ts.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(ts)