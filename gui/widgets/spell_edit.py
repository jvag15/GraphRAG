import re
from spellchecker import SpellChecker

from PyQt6.QtWidgets import QTextEdit, QMenu
from PyQt6.QtGui import (
    QSyntaxHighlighter,
    QTextCharFormat,
    QColor,
    QTextCursor,
    QAction
)
from PyQt6.QtCore import Qt

class SpellCheckHighlighter(QSyntaxHighlighter):
    """Highlights misspelled words with a red underline."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self._spell = SpellChecker()
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        from gui.main import ThemeLoader
        self._format.setUnderlineColor(QColor(ThemeLoader.TOKENS["@color_accent_danger"]))
    
def highlightBlock(self, text: str) -> None:
        """Called by Qt whenever a block changes. Mark misspelled words."""
        # Tokenise on word boundaries, skip numbers and single chars
        for match in re.finditer(r"\b[a-zA-Z]{2,}\b", text):
            word = match.group()
            if word.lower() in self._spell.unknown([word.lower()]):
                self.setFormat(match.start(), len(word), self._format)

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
                actions = menu.actions()
                if actions:
                    first_action = actions[0]
                    menu.insertSeparator(first_action)
                    for suggestion in reversed(suggestions):
                        action = QAction(suggestion, self)
                        action.triggered.connect(
                            lambda checked, s=suggestion, c=cursor:
                            self._replace_word(c, s)
                        )
                        menu.insertAction(first_action, action)
                    menu.insertSeparator(first_action)
        
        menu.exec(event.globalPos())
    
    def _replace_word(self, cursor: QTextCursor, replacement: str) -> None:
        cursor.insertText(replacement)