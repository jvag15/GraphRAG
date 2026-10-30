# SKILL_PHASE4_UI.md — GraphRAG Editorial Design System PyQt6 Translation
# GraphRAG Engine — Legal & Regulatory Compliance Intelligence Engine
#
# WATERMARK POLICY: No watermark comments of any kind are permitted in this
# project from Phase 4 onward. If the string "Engineered by uncoalesced" or
# any similar attribution comment appears in any existing file (gui/main.py,
# gui/tabs/*.py, gui/widgets/*.py, gui/workers/*.py, gui/services/*.py,
# prune_document.py, or any other source file), the CODER agent must remove
# it as part of this phase. Do not add new watermarks. Do not preserve old ones.
#
# This file supersedes the Catppuccin Mocha theme defined in SKILL_GUI.md
# Section "STYLESHEET (styles.qss)" and the ThemeLoader.TOKENS defaults
# defined in SKILL_PHASE2.md. Those sections are now historical only.
#
# Read CLAUDE.md → AGENTS.md → SKILL.md → UNIFIED_MEMORY.md → this file
# before implementing.

---

## SCOPE

This is a pure visual layer replacement. No layout structure changes, no new
widgets, no new tabs, no behavioural changes. Every QWidget, QThread worker,
signal, and mutual-exclusion rule built in Phases 1–3 remains untouched.

This file translates `docs/DESIGN_SYSTEM.md` — written in web/Tailwind
terminology — into native PyQt6 constructs: `QFontDatabase` for font loading,
a flat Python dictionary for token mapping, and pure Qt Style Sheet (QSS)
syntax for visual states. No HTML, no CSS, no Tailwind, no React appears
anywhere in this document or in the resulting code.

---

## PART 1 — FONT LOADING

The GraphRAG design system specifies three font families: Cormorant Garamond
(display), DM Sans (UI), and DM Mono (monospace). PyQt6 does not read
system-installed web fonts automatically — fonts must be loaded explicitly
via `QFontDatabase` from bundled `.ttf` files at application startup.

### Required directory structure

```
gui/assets/fonts/
├── CormorantGaramond-Regular.ttf
├── CormorantGaramond-Medium.ttf
├── CormorantGaramond-SemiBold.ttf
├── DMSans-Regular.ttf
├── DMSans-Medium.ttf
├── DMSans-Bold.ttf
├── DMMono-Regular.ttf
└── DMMono-Medium.ttf
```

Font files must be sourced from Google Fonts (Open Font License) and placed
in this directory before the application will render correctly. If a font
file is missing, `QFontDatabase.addApplicationFont()` returns `-1` and the
loader must fall back to a system default without raising.

### Exact Python code for gui/main.py

Insert this at the very top of `GraphRAGApp.__init__`, before any widget
is constructed, so all subsequently created widgets inherit the correct
font metrics.

```python
from PyQt6.QtGui import QFontDatabase, QFont
from pathlib import Path


class FontLoader:
    """Loads GraphRAG brand fonts from gui/assets/fonts/ into the Qt font database."""

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
```

### Wiring into application startup

In `main()`, before `GraphRAGApp()` is constructed:

```python
def main() -> None:
    """Entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("GraphRAG Control")
    app.setOrganizationName("GraphRAG Platform")

    FontLoader.load_all()
    app.setFont(FontLoader.sans_font(10))

    window = GraphRAGApp()
    window.show()
    sys.exit(app.exec())
```

The font family names resolved by `FontLoader.family_names()` are merged into
`ThemeLoader.TOKENS` before the stylesheet is applied (see Part 2).

---

## PART 2 — COLOR AND TOKEN MAPPING

Replace the entire `ThemeLoader.TOKENS` dictionary defined in SKILL_PHASE2.md
with the following. Every value below is sourced directly from
`docs/DESIGN_SYSTEM.md` Sections 5–9 and 19–21. No value is invented.

```python
class ThemeLoader:
    """Load theme.qss and substitute design tokens with GraphRAG brand values."""

    # === LIGHT MODE (default) — docs/DESIGN_SYSTEM.md Section 5 ===
    LIGHT_TOKENS: dict[str, str] = {
        # Backgrounds
        "@color_bg_base":          "#faf8f5",   # Background
        "@color_bg_surface":       "#ffffff",   # Surface
        "@color_bg_surface_alt":   "#f5f2ed",   # derived: slightly darker than surface for alt rows
        "@color_border":           "#e5e0d8",   # derived from gray-200 equivalent, warm neutral

        # Text
        "@color_text_primary":     "#1c1410",   # Primary Text
        "@color_text_secondary":   "#6b5f54",   # derived: warm gray-500 equivalent

        # Accent
        "@color_accent_primary":   "#9a3324",   # Accent
        "@color_accent_hover":     "#c9523c",   # Accent Hover

        # Semantic
        "@color_accent_success":   "#3d9a5c",   # Success
        "@color_accent_warning":   "#c47b14",   # Warning
        "@color_accent_danger":    "#c93a2a",   # Error
        "@color_accent_info":      "#2b6cb0",   # Info
    }

    # === DARK MODE — docs/DESIGN_SYSTEM.md Section 5 + 12 ===
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
        # QSS does not support transition timing functions or transform on
        # hover natively the way CSS does. Equivalent behaviour (hover lift,
        # focus rings) is implemented via QSS pseudo-states in Part 3, and any
        # animated transform (translateY) is implemented in Python via
        # QPropertyAnimation where strictly necessary — see Part 3 note.
    }

    # === LAYOUT — Section 9 ===
    LAYOUT_TOKENS: dict[str, str] = {
        "@layout_max_width":  "1280px",  # informational — PyQt6 has no max-width
                                          # concept for top-level windows; applied
                                          # as setMaximumWidth() on content containers
                                          # where the design calls for a centred,
                                          # width-capped reading column
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
        with open(qss_path) as f:
            qss = f.read()
        # Sort by key length descending to avoid partial-match substitution bugs
        # (e.g. @spacing_4 being replaced inside @spacing_48 first)
        for token in sorted(tokens.keys(), key=len, reverse=True):
            qss = qss.replace(token, tokens[token])
        return qss
```

### Dark mode default

`docs/DESIGN_SYSTEM.md` Section 9 states "Dark mode first-class." The
application defaults to dark mode on the Arch Linux GNOME host. Wire this in
`gui/main.py`:

```python
qss_path = Path(__file__).parent / "styles" / "theme.qss"
if qss_path.exists():
    self.setStyleSheet(ThemeLoader.load(qss_path, dark_mode=True))
```

A future settings toggle to switch `dark_mode=False` is out of scope for
Phase 4 and is not implemented here.

---

## PART 3 — QSS STYLESHEET (gui/styles/theme.qss)

This replaces the Catppuccin Mocha stylesheet body in full. Token names are
identical in structure to the placeholder system used in Phases 1–3, so all
existing `objectName` targeting in `gui/tabs/*.py` and `gui/widgets/*.py`
continues to work without modification.

```qss
/* ====================================================================
   GraphRAG Platform — PyQt6 Theme Stylesheet
   Source of truth: docs/DESIGN_SYSTEM.md
   Token substitution performed at runtime by ThemeLoader.load()
   ==================================================================== */

/* === BASE === */
QMainWindow, QWidget {
    background-color: @color_bg_base;
    color: @color_text_primary;
    font-family: @font_family_primary;
    font-size: @font_size_base;
}

/* === DISPLAY TYPOGRAPHY (hero headings, panel titles) === */
QLabel#panelTitle {
    font-family: @font_family_display;
    font-size: @font_size_display;
    font-weight: 500;
    color: @color_text_primary;
}

QLabel#labelSecondary {
    color: @color_text_secondary;
    font-size: @font_size_sm;
}

QLabel#labelPrimary {
    color: @color_text_primary;
    font-size: @font_size_base;
}

QLabel#messageTimestamp {
    color: @color_text_secondary;
    font-size: @font_size_sm;
    font-family: @font_family_mono;
}

/* === SURFACES / PANELS === */
QFrame#panelHeader {
    background-color: @color_bg_surface;
    border-bottom: 1px solid @color_border;
    padding: @spacing_12 @spacing_16;
}

QFrame#progressPanel {
    background-color: @color_bg_surface;
    border-top: 1px solid @color_border;
    padding: @spacing_16;
    border-radius: @radius_card_sm;
}

/* === PRIMARY BUTTON — Section 20 Immutable Component Blueprint === */
QPushButton {
    background-color: @color_accent_primary;
    color: #ffffff;
    border: none;
    border-radius: @radius_control;
    padding: @spacing_8 @spacing_16;
    font-family: @font_family_primary;
    font-size: @font_size_base;
    font-weight: 500;
}
QPushButton:hover {
    background-color: @color_accent_hover;
}
QPushButton:pressed {
    background-color: @color_accent_primary;
    padding-top: @spacing_8;  /* QSS cannot animate translateY; pressed state
                                 removes the hover lift by re-flattening padding */
}
QPushButton:disabled {
    background-color: @color_border;
    color: @color_text_secondary;
}

/* === GHOST BUTTON — Section 20 === */
QPushButton#ghostButton {
    background-color: transparent;
    color: @color_text_primary;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    padding: @spacing_8 @spacing_16;
}
QPushButton#ghostButton:hover {
    background-color: @color_bg_surface_alt;
}

/* === DANGER BUTTON (Prune action) === */
QPushButton#btnDanger {
    background-color: @color_accent_danger;
    color: #ffffff;
    border: none;
    border-radius: @radius_control;
    padding: @spacing_8 @spacing_16;
}
QPushButton#btnDanger:hover {
    background-color: #dd5547;
}
QPushButton#btnDanger:disabled {
    background-color: @color_bg_surface_alt;
    color: @color_text_secondary;
}

/* === TEXT INPUT — Section 20 === */
QTextEdit, QLineEdit {
    background-color: transparent;
    color: @color_text_primary;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    padding: @spacing_8 @spacing_12;
    font-size: @font_size_base;
    selection-background-color: @color_accent_primary;
    selection-color: #ffffff;
}
QTextEdit:focus, QLineEdit:focus {
    border: 1px solid @color_accent_primary;
    outline: none;
}

/* === STANDARD CARD — Section 20 === */
QFrame#standardCard {
    background-color: @color_bg_surface;
    border: 1px solid @color_border;
    border-radius: @radius_card;
    padding: @spacing_24;
}

/* === CHAT BUBBLES === */
QFrame#aiBubble {
    background-color: @color_bg_surface;
    border: 1px solid @color_border;
    border-radius: @radius_card_sm;
    padding: @spacing_16;
    margin-right: 20%;
}
QFrame#userBubble {
    background-color: @color_bg_surface_alt;
    border-radius: @radius_card_sm;
    padding: @spacing_16;
    margin-left: 20%;
}
QTextEdit#answerText {
    background-color: transparent;
    border: none;
    padding: 0;
}
QTextEdit#userText {
    background-color: transparent;
    border: none;
    padding: 0;
}

/* === ACCORDION TOGGLE === */
QToolButton#accordionToggle {
    background-color: @color_bg_surface_alt;
    color: @color_text_secondary;
    border: none;
    border-radius: @radius_badge;
    padding: @spacing_8 @spacing_16;
    text-align: left;
    font-size: @font_size_sm;
}
QToolButton#accordionToggle:hover {
    background-color: @color_accent_primary;
    color: #ffffff;
}

QTextEdit#evidencePanel {
    background-color: @color_bg_base;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    font-family: @font_family_mono;
    font-size: @font_size_sm;
    color: @color_text_secondary;
    padding: @spacing_16;
}

/* === PROGRESS BAR === */
QProgressBar {
    border: none;
    border-radius: @radius_badge;
    background-color: @color_bg_surface_alt;
    text-align: center;
    color: @color_text_primary;
    font-size: @font_size_sm;
    height: 8px;
}
QProgressBar::chunk {
    background-color: @color_accent_primary;
    border-radius: @radius_badge;
}

/* === TABS === */
QTabWidget::pane {
    border: 1px solid @color_border;
    border-radius: @radius_card_sm;
    top: -1px;
}
QTabBar::tab {
    background-color: @color_bg_surface;
    color: @color_text_secondary;
    padding: @spacing_8 @spacing_16;
    border: 1px solid @color_border;
    border-bottom: none;
    border-top-left-radius: @radius_control;
    border-top-right-radius: @radius_control;
    margin-right: @spacing_4;
}
QTabBar::tab:selected {
    background-color: @color_bg_base;
    color: @color_text_primary;
    border-bottom: 2px solid @color_accent_primary;
}
QTabBar::tab:hover:!selected {
    background-color: @color_bg_surface_alt;
}

/* === TABLE / HEADER (Knowledge Management tab) === */
QTableWidget {
    background-color: @color_bg_surface;
    gridline-color: transparent;
    border: 1px solid @color_border;
    border-radius: @radius_card_sm;
    alternate-background-color: @color_bg_surface_alt;
}
QTableWidget::item {
    padding: @spacing_8 @spacing_16;
    border-bottom: 1px solid @color_border;
}
QTableWidget::item:selected {
    background-color: @color_accent_primary;
    color: #ffffff;
}
QHeaderView::section {
    background-color: @color_bg_surface_alt;
    color: @color_text_secondary;
    padding: @spacing_8 @spacing_16;
    border: none;
    border-bottom: 1px solid @color_border;
    font-size: @font_size_sm;
    font-weight: 500;
}

/* === COMBOBOX === */
QComboBox {
    background-color: @color_bg_surface;
    color: @color_text_primary;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    padding: @spacing_8 @spacing_12;
    min-height: 32px;
}
QComboBox:focus {
    border: 1px solid @color_accent_primary;
}
QComboBox::drop-down {
    width: 24px;
    background-color: transparent;
    border-left: 1px solid @color_border;
    border-top-right-radius: @radius_control;
    border-bottom-right-radius: @radius_control;
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
QComboBox QAbstractItemView {
    background-color: @color_bg_surface;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    selection-background-color: @color_accent_primary;
    selection-color: #ffffff;
    padding: @spacing_4;
}
QComboBox QAbstractItemView::item:hover {
    background-color: @color_bg_surface_alt;
}

/* === SCROLLBARS === */
QScrollBar:vertical {
    background: @color_bg_surface;
    width: 10px;
    border: none;
    border-radius: @radius_badge;
}
QScrollBar::handle:vertical {
    background: @color_border;
    border-radius: @radius_badge;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: @color_accent_primary;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}

/* === SPLITTER === */
QSplitter::handle {
    background-color: @color_border;
    width: 4px;
}
QSplitter::handle:hover {
    background-color: @color_accent_primary;
}

/* === TOOLTIP === */
QToolTip {
    background-color: @color_bg_surface;
    color: @color_text_primary;
    border: 1px solid @color_border;
    padding: @spacing_8 @spacing_12;
    border-radius: @radius_control;
    font-size: @font_size_sm;
}

/* === STATUS BAR === */
QStatusBar {
    background-color: @color_bg_surface;
    color: @color_text_secondary;
    border-top: 1px solid @color_border;
    font-size: @font_size_sm;
}

/* === MONOSPACE LOG VIEW (ingestion live log) === */
QTextEdit#logView {
    background-color: @color_bg_base;
    color: @color_text_secondary;
    font-family: @font_family_mono;
    font-size: @font_size_sm;
    border: 1px solid @color_border;
    border-radius: @radius_control;
    padding: @spacing_12;
}
```

### Note on motion (Section 8)

QSS does not support CSS-style `transition` properties or `transform:
translateY()` on hover. The design system's hover-lift behaviour
(`translateY(-2px)`, increased elevation) cannot be expressed in static QSS.
Where this matters most — the primary button hover state and standard card
hover state — the visual effect is approximated using a background-color
shift only (no Y-translation). Do not attempt to implement `QPropertyAnimation`
geometry shifts for hover states in Phase 4; this is explicitly deferred and
is not part of this skill file's scope. Document this gap in
`CHANGES_SUMMARY.md` if the Coder agent encounters a request to implement it.

---

## PART 4 — WATERMARK REMOVAL DIRECTIVE

Effective immediately, no source file in this project may contain any
attribution comment of the form `# Engineered by <anything>` or
`# Engineered for <anything>`.

**Required Coder action as part of Phase 4:**

```bash
# Run on server (SSH) or search Windows project tree before transfer:
grep -rln "Engineered by\|Engineered for" \
  gui/ src/ *.py 2>/dev/null
```

For every file returned by this grep, remove the matching comment line in
full. Do not leave an empty comment line in its place — delete the line
entirely, including its trailing newline if it leaves a double blank line.

This applies retroactively to every file built in Phase 1, Phase 2, and
Phase 3, including but not limited to: `gui/main.py`, all files under
`gui/tabs/`, `gui/widgets/`, `gui/workers/`, `gui/services/`,
`prune_document.py`, and `batch_coordinator.py`.

No replacement watermark, header comment, or attribution string is to be
added. Standard module docstrings describing functionality are permitted
and encouraged; attribution comments are not.

---

## VERIFICATION CHECKLIST — PHASE 4

- [ ] `gui/assets/fonts/` directory created with all 8 required `.ttf` files
- [ ] `FontLoader.load_all()` called before any widget construction in `main()`
- [ ] `ThemeLoader.TOKENS` fully replaced — no Catppuccin hex values remain
- [ ] `grep -rE "#[0-9a-fA-F]{6}" gui/styles/theme.qss` returns ONLY the values
      listed in Part 2 (no stray Catppuccin colours like `#1e1e2e`, `#89b4fa`)
- [ ] Dark mode is the default on application launch
- [ ] All spacing values in theme.qss map to the 8-point grid (4/8/12/16/20/24/32/40/48/64/80)
- [ ] All radius values match Section 7 exactly (4/6/8/12/16/9999px)
- [ ] QComboBox arrow renders visibly (regression check from Phase 3)
- [ ] `grep -rln "Engineered by\|Engineered for" gui/ src/ *.py` returns ZERO results
- [ ] No HTML, CSS, Tailwind class names, or React syntax anywhere in this file's
      generated code
- [ ] Application launches without font-loading exceptions even if `.ttf` files
      are temporarily absent (graceful fallback to system fonts confirmed)
```
