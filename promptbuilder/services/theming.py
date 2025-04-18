# promptbuilder/services/theming.py
from enum import Enum
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt
from loguru import logger

class Theme(Enum):
    AUTO = "AUTO"
    LIGHT = "LIGHT"
    DARK = "DARK"

def apply_theme(theme: Theme):
    """Applies the selected theme to the QApplication."""
    app = QApplication.instance()
    if not app:
        logger.warning("QApplication instance not found for applying theme.")
        return

    current_theme = theme
    if theme == Theme.AUTO:
        # Basic system theme detection (can be unreliable)
        # A more robust method might involve platform-specific APIs or libraries
        # For now, default to light if detection fails or isn't implemented
        # system_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark # Requires Qt >= 6.5
        # A simpler check based on background color (less reliable)
        bg_color = app.palette().window().color()
        system_dark = bg_color.value() < 128 # Guess based on default palette
        current_theme = Theme.DARK if system_dark else Theme.LIGHT
        logger.info(f"Auto theme detection: {'Dark' if system_dark else 'Light'}")

    logger.info(f"Applying theme: {current_theme.name}")

    if current_theme == Theme.DARK:
        # Apply a dark palette
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)

        # Disabled states
        disabled_text = QColor(127, 127, 127)
        disabled_button = QColor(80, 80, 80)
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
        dark_palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, disabled_button)

        app.setPalette(dark_palette)
        # Optional: Set a style that works well with dark mode
        # app.setStyle("Fusion")
    else:
        # Apply the default system palette (Light)
        # Resetting to original style palette might be better
        original_palette = QApplication.style().standardPalette()
        app.setPalette(original_palette)
        # app.setStyle(QApplication.style().objectName()) # Reset to original style if changed
