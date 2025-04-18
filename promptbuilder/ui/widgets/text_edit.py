# promptbuilder/ui/widgets/text_edit.py

from PySide6.QtWidgets import QTextEdit, QSizePolicy
from PySide6.QtCore import Slot
from PySide6.QtGui import QKeySequence, QFontDatabase, QTextOption


class PromptTextEdit(QTextEdit):
    """Read-only text edit for displaying the generated prompt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False) # Work with plain text
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth) # Wrap lines

        # Set fixed-width font correctly using QFontDatabase
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.setFont(fixed_font)

        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere) # Wrap long lines without spaces

        # Set background color slightly different? (Optional)
        # pal = self.palette()
        # pal.setColor(QPalette.ColorRole.Base, pal.color(QPalette.ColorRole.AlternateBase))
        # self.setPalette(pal)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # Override keyPressEvent to ensure only copy/select all work
    def keyPressEvent(self, event):
        # Allow copy (Ctrl+C), select all (Ctrl+A)
        if event.matches(QKeySequence.StandardKey.Copy) or \
           event.matches(QKeySequence.StandardKey.SelectAll):
            super().keyPressEvent(event)
        else:
            # Ignore other key presses like typing, delete, backspace etc.
            event.ignore()

    # Override mouse events if needed (e.g., disable drag/drop?) - usually not necessary for read-only

    @Slot(str)
    def setPlainText(self, text: str):
        """Sets the plain text content, ensuring read-only state."""
        # No need to toggle read-only state if it's always read-only
        super().setPlainText(text)
        # Move cursor to the beginning after setting text
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.setTextCursor(cursor)