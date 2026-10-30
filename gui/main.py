"""
GraphRAG Control — Master PyQt6 desktop application.

This module provides the single point of control for the entire GraphRAG
pipeline: ingestion monitoring, hardware telemetry, and legal query
interface with knowledge graph visualisation.

"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QStatusBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QFont

from gui.tabs.ingestion_tab import IngestionTab
from gui.tabs.query_tab import QueryTab
from gui.tabs.knowledge_tab import KnowledgeTab
from gui.workers.telemetry_worker import TelemetryWorker


class FontLoader:
    """Loads brand fonts from gui/assets/fonts/ into the Qt font database."""

    FONT_DIR = Path(__file__).parent / "assets" / "fonts"

    FONT_FILES = [
        "CormorantGaramond-Regular.ttf",
        "CormorantGaramond-Medium.ttf",
        "CormorantGaramond-SemiBold.ttf",
        "DMSans-Regular.ttf",
        "DMSans-Medium.ttf",
        "DMSans-Bold.ttf",
        "DMMono-Regular.ttf",
        "DMMono-Medium.ttf",
    ]

    DISPLAY_FAMILY_FALLBACK = "Georgia"
    SANS_FAMILY_FALLBACK = "Segoe UI"
    MONO_FAMILY_FALLBACK = "Consolas"

    _display_family: str = DISPLAY_FAMILY_FALLBACK
    _sans_family: str = SANS_FAMILY_FALLBACK
    _mono_family: str = MONO_FAMILY_FALLBACK

    @classmethod
    def load_all(cls) -> None:
        """Register every bundled font file. Call once at application startup."""
        loaded_families: list[str] = []

        for filename in cls.FONT_FILES:
            font_path = cls.FONT_DIR / filename
            if not font_path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id == -1:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            loaded_families.extend(families)

        if any("Cormorant Garamond" in f for f in loaded_families):
            cls._display_family = "Cormorant Garamond"
        if any("DM Sans" in f for f in loaded_families):
            cls._sans_family = "DM Sans"
        if any("DM Mono" in f for f in loaded_families):
            cls._mono_family = "DM Mono"

    @classmethod
    def display_font(cls, point_size: int = 24, weight: int = QFont.Weight.Medium) -> QFont:
        return QFont(cls._display_family, point_size, weight)

    @classmethod
    def sans_font(cls, point_size: int = 10, weight: int = QFont.Weight.Normal) -> QFont:
        return QFont(cls._sans_family, point_size, weight)

    @classmethod
    def mono_font(cls, point_size: int = 10, weight: int = QFont.Weight.Normal) -> QFont:
        return QFont(cls._mono_family, point_size, weight)

    @classmethod
    def family_names(cls) -> dict[str, str]:
        """Return resolved family names for QSS token substitution."""
        return {
            "@font_family_display": cls._display_family,
            "@font_family_primary": cls._sans_family,
            "@font_family_mono": cls._mono_family,
        }


class ThemeLoader:
    """Load theme.qss and substitute design tokens with brand values."""

    # === LIGHT MODE (default) — DESIGN_SYSTEM.md Section 5 ===
    LIGHT_TOKENS: dict[str, str] = {
        "@color_bg_base":          "#faf8f5",   # Background
        "@color_bg_surface":       "#ffffff",   # Surface
        "@color_bg_surface_alt":   "#f5f2ed",   # derived: slightly darker than surface for alt rows
        "@color_border":           "#e5e0d8",   # derived from gray-200 equivalent, warm neutral

        "@color_text_primary":     "#1c1410",   # Primary Text
        "@color_text_secondary":   "#6b5f54",   # derived: warm gray-500 equivalent

        "@color_accent_primary":   "#9a3324",   # Accent
        "@color_accent_hover":     "#c9523c",   # Accent Hover

        "@color_accent_success":   "#3d9a5c",   # Success
        "@color_accent_warning":   "#c47b14",   # Warning
        "@color_accent_danger":    "#c93a2a",   # Error
        "@color_accent_info":      "#2b6cb0",   # Info
    }

    # === DARK MODE — DESIGN_SYSTEM.md Section 5 + 12 ===
    DARK_TOKENS: dict[str, str] = {
        "@color_bg_base":          "#191919",   # Dark Background
        "@color_bg_surface":       "#1f1c19",   # Dark Surface
        "@color_bg_surface_alt":   "#262320",   # derived: warm charcoal, one step lighter
        "@color_border":           "#3a352e",   # derived: warm neutral dark border

        "@color_text_primary":     "#f0ebe3",   # Dark Text
        "@color_text_secondary":   "#a89e90",   # derived: warm gray-400 equivalent

        "@color_accent_primary":   "#c9523c",   # Accent Hover value used as base in dark mode
        "@color_accent_hover":     "#d97259",   # derived: lighter accent for dark mode hover

        "@color_accent_success":   "#4db377",   # derived: lightened for dark contrast
        "@color_accent_warning":   "#dd9332",   # derived: lightened for dark contrast
        "@color_accent_danger":    "#dd5547",   # derived: lightened for dark contrast
        "@color_accent_info":      "#4585c9",   # derived: lightened for dark contrast
    }

    # === TYPOGRAPHY — Section 4 (family names injected by FontLoader) ===
    TYPOGRAPHY_TOKENS: dict[str, str] = {
        "@font_family_display":    "Cormorant Garamond",   # overridden by FontLoader.family_names()
        "@font_family_primary":    "DM Sans",               # overridden by FontLoader.family_names()
        "@font_family_mono":       "DM Mono",                # overridden by FontLoader.family_names()
        "@font_size_display":      "24px",
        "@font_size_lg":           "16px",
        "@font_size_base":         "14px",
        "@font_size_sm":           "12px",
    }

    # === SPACING — Section 6, 8-point grid only ===
    SPACING_TOKENS: dict[str, str] = {
        "@spacing_4":   "4px",
        "@spacing_8":   "8px",
        "@spacing_12":  "12px",
        "@spacing_16":  "16px",
        "@spacing_20":  "20px",
        "@spacing_24":  "24px",
        "@spacing_32":  "32px",
        "@spacing_40":  "40px",
        "@spacing_48":  "48px",
        "@spacing_64":  "64px",
        "@spacing_80":  "80px",
        # Semantic aliases used throughout existing QSS — map onto the grid:
        "@spacing_sm":  "8px",
        "@spacing_md":  "16px",
        "@spacing_lg":  "24px",
    }

    # === RADIUS — Section 7 ===
    RADIUS_TOKENS: dict[str, str] = {
        "@radius_badge":    "4px",
        "@radius_control":  "6px",
        "@radius_card_sm":  "8px",
        "@radius_card":     "12px",
        "@radius_panel":    "16px",
        "@radius_pill":     "9999px",
        # Semantic aliases used throughout existing QSS:
        "@radius_sm":       "6px",   # maps to control radius
        "@radius_md":       "12px",  # maps to standard card radius
    }

    # === MOTION — Section 8 ===
    MOTION_TOKENS: dict[str, str] = {
        "@duration_fast":    "80ms",
        "@duration_base":    "150ms",
        "@duration_slow":    "200ms",
        "@duration_slower":  "300ms",
    }

    # === LAYOUT — Section 9 ===
    LAYOUT_TOKENS: dict[str, str] = {
        "@layout_max_width":  "1280px",
        "@header_height":     "56px",
    }

    @classmethod
    def build_tokens(cls, dark_mode: bool = False) -> dict[str, str]:
        """Compose the full token set for the requested mode."""
        from gui.main import FontLoader  # local import avoids circular import
        tokens: dict[str, str] = {}
        tokens.update(cls.DARK_TOKENS if dark_mode else cls.LIGHT_TOKENS)
        tokens.update(cls.TYPOGRAPHY_TOKENS)
        tokens.update(cls.SPACING_TOKENS)
        tokens.update(cls.RADIUS_TOKENS)
        tokens.update(cls.MOTION_TOKENS)
        tokens.update(cls.LAYOUT_TOKENS)
        tokens.update(FontLoader.family_names())  # resolved font names win
        return tokens

    @classmethod
    def load(cls, qss_path: Path, dark_mode: bool = False,
              overrides: dict[str, str] | None = None) -> str:
        """Read QSS file and substitute all @token_name placeholders."""
        tokens = {**cls.build_tokens(dark_mode), **(overrides or {})}
        cls.TOKENS = tokens  # cache for runtime lookups (spell_edit.py, query_tab.py)
        with open(qss_path, encoding="utf-8") as f:
            qss = f.read()
        # Sort by key length descending to avoid partial-match substitution bugs
        # (e.g. @spacing_4 being replaced inside @spacing_48 first)
        for token in sorted(tokens.keys(), key=len, reverse=True):
            qss = qss.replace(token, tokens[token])
        return qss


class GraphRAGApp(QMainWindow):
    """Master control interface for the GraphRAG pipeline."""

    def __init__(self) -> None:
        super().__init__()
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

        self.setWindowTitle("GraphRAG Control Platform")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)

        # Load and apply stylesheet with design token substitution
        qss_path = Path(__file__).parent / "styles" / "theme.qss"
        if qss_path.exists():
            self.setStyleSheet(ThemeLoader.load(qss_path, dark_mode=True))

        # Build tabs
        self._ingestion_tab = IngestionTab()
        self._query_tab = QueryTab()
        self._knowledge_tab = KnowledgeTab()

        tabs = QTabWidget()
        tabs.addTab(self._ingestion_tab, "⚙ Ingestion")
        tabs.addTab(self._query_tab, "🔍 Query")
        tabs.addTab(self._knowledge_tab, "📚 Knowledge")
        self.setCentralWidget(tabs)

        # Wire mutual exclusion: query tab signals to ingestion tab slots
        self._query_tab.ingestion_stop_requested.connect(
            self._ingestion_tab.on_stop_requested
        )
        self._query_tab.ingestion_pause_requested.connect(
            self._ingestion_tab.on_pause_requested
        )

        # Wire knowledge tab prune_conflict signal
        self._knowledge_tab.prune_conflict.connect(self._on_prune_conflict)

        # Start telemetry worker (runs for the lifetime of the application)
        self._telemetry = TelemetryWorker()
        # Connect telemetry to BOTH tabs (avoids StateManager.read() in GUI thread)
        self._telemetry.telemetry_updated.connect(
            self._ingestion_tab.on_telemetry_updated
        )
        self._telemetry.telemetry_updated.connect(
            self._query_tab.on_telemetry_updated
        )
        self._telemetry.start()

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _on_prune_conflict(self, reason: str) -> None:
        """Handle prune conflict from KnowledgeTab.

        Shows context-aware dialog. Stop/Pause buttons wired only for "ingesting".
        """
        from gui.widgets.mutual_exclusion_dialog import MutualExclusionDialog

        dlg = MutualExclusionDialog(reason, self)
        if reason == "ingesting":
            dlg.action_stop.connect(self._ingestion_tab.on_stop_requested)
            dlg.action_pause.connect(self._ingestion_tab.on_pause_requested)
        dlg.exec()

    def closeEvent(self, event) -> None:
        """Clean shutdown — stop telemetry worker before closing."""
        self._telemetry.stop()
        self._telemetry.wait(3000)
        super().closeEvent(event)


def main() -> None:
    """Entry point."""
    # Wayland / Chromium safety flag must precede QApplication instantiation
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

    app = QApplication(sys.argv)
    app.setApplicationName("GraphRAG Control")
    app.setOrganizationName("GraphRAG")

    FontLoader.load_all()
    app.setFont(FontLoader.sans_font(10))

    window = GraphRAGApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
