# promptbuilder/ui/widgets/prompt_panel.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QCheckBox, QLabel, QScrollArea, QSizePolicy,
                             QDialog, QPlainTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, Signal, Slot
from typing import Dict, List, Set, Tuple, Optional
from functools import partial
from loguru import logger

from ...config.schema import SnippetCategory # For type hinting

# --- Custom Text Dialog --- (Could be in a separate dialogs.py)
class CustomTextDialog(QDialog):
    def __init__(self, title="Custom Text", instruction="", initial_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)
        self.label = QLabel(instruction)
        layout.addWidget(self.label)

        self.text_edit = QPlainTextEdit()
        if initial_text:
             self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

# --- Prompt Panel Widget ---
class PromptPanelWidget(QWidget):
    """Widget for selecting prompt snippets and questions."""

    # Signal emitting the selected snippets and questions
    # Format: Dict[str, Dict[str, Optional[str]]], Set[str]
    # {Category: {Name: CustomTextOrNone}}, {QuestionText}
    snippets_changed = Signal()

    def __init__(self,
                 snippet_definitions: Dict[str, SnippetCategory],
                 common_questions: List[str],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.snippet_definitions = snippet_definitions
        self.common_questions = common_questions

        # Internal state
        self.selected_snippets: Dict[str, Dict[str, Optional[str]]] = {}
        self.selected_questions: Set[str] = set()

        # Store references to checkboxes for state management
        self.category_checkboxes: Dict[str, Dict[str, QCheckBox]] = {} # {Cat: {Name: CheckBox}}
        self.question_checkboxes: Dict[str, QCheckBox] = {} # {QuestionText: CheckBox}

        self._setup_ui()
        logger.debug("PromptPanelWidget initialized.")

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # --- Snippet Categories Section ---
        snippets_group = QGroupBox("Instruction Snippets")
        snippets_layout = QVBoxLayout(snippets_group)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        snippets_layout.addWidget(scroll_area)

        container = QWidget() # Container for horizontal layout inside scroll area
        scroll_area.setWidget(container)
        categories_layout = QHBoxLayout(container) # Horizontal layout for categories
        container.setLayout(categories_layout)

        # Build category group boxes horizontally
        for category_name, category_data in self.snippet_definitions.items():
            cat_group_box = QGroupBox(category_name)
            cat_group_layout = QVBoxLayout(cat_group_box)
            cat_group_layout.setSpacing(2) # Compact layout

            self.category_checkboxes[category_name] = {}

            # Sort items? Maybe keep definition order. Add "Custom" if present.
            item_names = list(category_data.items.keys())
            # Ensure "Custom" is last if it exists
            if "Custom" in item_names:
                 item_names.remove("Custom")
                 item_names.append("Custom")

            for item_name in item_names:
                cb = QCheckBox(item_name)
                # Use partial to pass category and item name to the handler
                cb.stateChanged.connect(
                    partial(self._on_snippet_checkbox_changed, category_name, item_name)
                )
                cat_group_layout.addWidget(cb)
                self.category_checkboxes[category_name][item_name] = cb

            cat_group_layout.addStretch(1) # Push checkboxes to the top
            categories_layout.addWidget(cat_group_box)

        categories_layout.addStretch(1) # Push group boxes to the left
        main_layout.addWidget(snippets_group)

        # --- Additional Questions Section ---
        questions_group = QGroupBox("Additional Questions")
        questions_layout = QVBoxLayout(questions_group)
        questions_layout.setSpacing(2)

        for q_text in self.common_questions:
            q_cb = QCheckBox(q_text)
            # ----- replace the invalid call -----
            # q_cb.setWordWrap(True)        # <-- remove this
            q_cb.setStyleSheet("QCheckBox { white-space: normal; }")
            # or, if you prefer the HTML trick:
            # q_cb.setText(f"<html>{q_text}</html>")
            # ------------------------------------

            q_cb.stateChanged.connect(
                partial(self._on_question_checkbox_changed, q_text)
            )
            questions_layout.addWidget(q_cb)
            self.question_checkboxes[q_text] = q_cb

        questions_layout.addStretch(1)
        main_layout.addWidget(questions_group)

        # Set stretch factors for vertical layout if needed
        main_layout.setStretchFactor(snippets_group, 3) # Give more space to snippets
        main_layout.setStretchFactor(questions_group, 1)


    @Slot(str, str, int) # category_name, item_name, state
    def _on_snippet_checkbox_changed(self, category: str, item_name: str, state: int):
        """Handles state changes for snippet checkboxes."""
        is_checked = (state == Qt.CheckState.Checked.value) # Use enum value for comparison
        cb = self.category_checkboxes[category][item_name]

        logger.debug(f"Snippet changed: {category}/{item_name}, Checked: {is_checked}")

        if is_checked:
            # Handle "Custom" snippet input
            if item_name == "Custom":
                # Get existing custom text if re-checking
                existing_text = ""
                if category in self.selected_snippets and item_name in self.selected_snippets[category]:
                     existing_text = self.selected_snippets[category].get(item_name) or ""

                dialog = CustomTextDialog(
                    title=f"Custom '{category}' Snippet",
                    instruction=f"Enter custom text for '{category}':",
                    initial_text=existing_text,
                    parent=self
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    custom_text = dialog.get_text()
                    if custom_text:
                        # Store the custom text
                        self.selected_snippets.setdefault(category, {})[item_name] = custom_text
                        logger.debug(f"Custom text set for {category}: '{custom_text[:50]}...'")
                    else:
                        # User entered empty text, uncheck the box
                        logger.debug(f"Custom text empty for {category}, unchecking.")
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                        # Remove if it existed
                        if category in self.selected_snippets:
                            self.selected_snippets[category].pop(item_name, None)
                            if not self.selected_snippets[category]:
                                del self.selected_snippets[category]
                        self.snippets_changed.emit() # Emit change
                        return # Don't proceed further
                else:
                    # User cancelled the dialog, uncheck the box
                    logger.debug(f"Custom text dialog cancelled for {category}, unchecking.")
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    # Remove if it existed
                    if category in self.selected_snippets:
                        self.selected_snippets[category].pop(item_name, None)
                        if not self.selected_snippets[category]:
                            del self.selected_snippets[category]
                    self.snippets_changed.emit() # Emit change
                    return # Don't proceed further
            else:
                # Normal snippet checked, store None for custom text
                self.selected_snippets.setdefault(category, {})[item_name] = None
        else:
            # Unchecked: remove from selection
            if category in self.selected_snippets:
                self.selected_snippets[category].pop(item_name, None)
                # If category becomes empty, remove it too
                if not self.selected_snippets[category]:
                    del self.selected_snippets[category]

        # Emit signal after any change
        self.snippets_changed.emit()


    @Slot(str, int) # question_text, state
    def _on_question_checkbox_changed(self, question_text: str, state: int):
        """Handles state changes for question checkboxes."""
        is_checked = (state == Qt.CheckState.Checked.value)
        logger.debug(f"Question changed: '{question_text[:50]}...', Checked: {is_checked}")

        if is_checked:
            self.selected_questions.add(question_text)
        else:
            self.selected_questions.discard(question_text) # Use discard to avoid KeyError

        # Emit signal after any change
        self.snippets_changed.emit()


    # --- Public API ---

    def get_selected_items(self) -> Tuple[Dict[str, Dict[str, Optional[str]]], Set[str]]:
        """Returns the currently selected snippets and questions."""
        # Return copies to prevent external modification
        return self.selected_snippets.copy(), self.selected_questions.copy()

    def clear_selections(self):
        """Unchecks all checkboxes and clears internal state."""
        logger.info("Clearing prompt panel selections.")
        changed = False
        self.blockSignals(True) # Block main signal during batch changes
        try:
            # Uncheck category checkboxes
            for cat_name, items in self.category_checkboxes.items():
                for item_name, cb in items.items():
                    if cb.isChecked():
                        cb.blockSignals(True) # Block individual signals
                        cb.setChecked(False)
                        cb.blockSignals(False)
                        changed = True

            # Uncheck question checkboxes
            for q_text, q_cb in self.question_checkboxes.items():
                if q_cb.isChecked():
                    q_cb.blockSignals(True)
                    q_cb.setChecked(False)
                    q_cb.blockSignals(False)
                    changed = True

            # Clear internal state
            if self.selected_snippets:
                 self.selected_snippets.clear()
                 changed = True
            if self.selected_questions:
                 self.selected_questions.clear()
                 changed = True

        finally:
            self.blockSignals(False)

        # Emit signal only if something actually changed
        if changed:
            logger.debug("Selections cleared, emitting snippets_changed.")
            self.snippets_changed.emit()
        else:
             logger.debug("Selections already clear, no change emitted.")