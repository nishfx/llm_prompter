import sys
import os
import json
import time

# If you have tiktoken installed:
try:
    import tiktoken
except ImportError:
    tiktoken = None

from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QTreeWidget, QTreeWidgetItem, QFileDialog,
    QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QSplitter,
    QLineEdit, QCheckBox, QLabel, QFrame,
    QMessageBox, QComboBox, QSizePolicy, QScrollArea,
    QGroupBox, QPlainTextEdit, QDialog, QDialogButtonBox, QInputDialog
)
from PySide6.QtGui import QAction, QGuiApplication, QPalette, QColor
from PySide6.QtCore import Qt

# ------------------------------------------------------------------------------------
# Example prompt config (could be loaded from an external JSON file)
# ------------------------------------------------------------------------------------
PROMPT_CONFIG = {
    "Objective": {
        "Concept": "Your task is to develop a concept.",
        "Review": "Review the provided context carefully and thoroughly.",
        "Debug": "Try to debug any errors.",
        "Develop": "Implement a new feature or system.",
        "Custom": ""
    },
    "Scope": {
        "Everything": "Scope includes everything.",
        "High-level": "Scope: High-level.",
        "Low-level": "Scope: Low-level or details.",
        "Custom": ""
    },
    "Requirements": {
        "In-depth": "Your solution should be prepared in-depth.",
        "Superficial": "A superficial solution will suffice.",
        "High Quality": "Provide a solution of extraordinary quality.",
        "Creative": "Provide a creative, unexpected solution, not a super predictable one.",
        "Custom": ""
    },
    "Constraints": {
        "2 sentences": "Explain in exactly 2 sentences.",
        "2 paragraphs": "Explain in exactly 2 paragraphs.",
        "500 lines of code": "Limit to 500 lines of code.",
        "No placeholders": "Don't use placeholders, always provide the full solution.",
        "Custom": ""
    },
    "Process": {
        "CoT": "Chain-of-thought reasoning recommended.",
        "3 iterations": (
            "Iterate on this solution 3 times by reviewing it, "
            "finding improvements, and refining further."
        ),
        "Custom": ""
    },
    "Output": {
        "XML": "Use an XML-styled output format.",
        "Summary": "At the end, provide a verbose summary.",
        "Prod-ready": "Must be production-ready.",
        "Full and final": "Give me the full and final scripts you added or modified.",
        "Custom": ""
    }
}

SYSTEM_DIRS = {'.git', '.idea', '.pytest_cache', '__pycache__'}
SYSTEM_FILES = {'requirements.txt', 'setup.py', 'pyproject.toml'}
VENV_DIR_NAMES = {'env', 'venv', '.env', '.venv'}

FILE_EXTENSIONS = ('.py', '.txt', '.md', '.json', '.yaml', '.yml')

SORT_NONE = "None"
SORT_NAME = "Name"
SORT_SIZE = "Size"
SORT_MOD_TIME = "Modified Time"

CONFIG_FILE = "config.json"


class CustomTextDialog(QDialog):
    """
    A simple multiline input dialog for custom text.
    Displays a QPlainTextEdit plus OK/Cancel buttons.

    WARNING Fix:
    Instead of QDialogButtonBox.Ok/Cancel, use QDialogButtonBox.StandardButton.Ok/Cancel
    to avoid "Unresolved attribute reference" warnings in some PySide/PyQt versions.
    """

    def __init__(self, title="Custom Text", instruction="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.label = QLabel(instruction)
        layout.addWidget(self.label)

        self.text_edit = QPlainTextEdit()
        layout.addWidget(self.text_edit)

        # Fix for "Unresolved attribute reference 'Ok'/'Cancel'"
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.resize(400, 300)

    def get_text(self):
        return self.text_edit.toPlainText()


class PromptBuilder(QWidget):
    """
    Displays categories side by side (horizontally),
    each category is a QGroupBox with multiple checkboxes.
    A "Prompt Builder" headline at top-left.
    """

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.selected_snippets = {}

        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        title_label = QLabel("Prompt Builder")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(title_label, alignment=Qt.AlignLeft)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        container = QWidget()
        scroll_area.setWidget(container)

        self.categories_layout = QHBoxLayout(container)
        container.setLayout(self.categories_layout)

        self.checkboxes_by_category = {}

        # Build categories horizontally
        for category, items_dict in PROMPT_CONFIG.items():
            group_box = QGroupBox(category)
            group_box_layout = QVBoxLayout(group_box)

            self.checkboxes_by_category[category] = {}

            for item_name, snippet in items_dict.items():
                cb = QCheckBox(item_name)
                # DEBUG: partial ensures (category, item_name) are passed,
                # plus the int from stateChanged.
                cb.stateChanged.connect(
                    partial(self.on_checkbox_changed, category, item_name)
                )
                group_box_layout.addWidget(cb)
                self.checkboxes_by_category[category][item_name] = cb

            group_box_layout.addStretch(1)
            self.categories_layout.addWidget(group_box)

        self.categories_layout.addStretch(1)

    def on_checkbox_changed(self, category, item_name, state):
        """
        DEBUG: We'll add a print here to confirm it's actually called.
        """

        # In Qt, state=2 means checked, state=0 means unchecked, state=1 = partially
        checked = (state == 2)
        if checked:
            # If user checked "Custom", show dialog:
            if item_name == "Custom":
                dialog = CustomTextDialog(
                    title="Custom Text",
                    instruction=f"Enter custom snippet for '{category}':",
                    parent=self
                )
                if dialog.exec() == QDialog.Accepted:
                    text = dialog.get_text().strip()
                    if text:
                        self.selected_snippets.setdefault(category, {})[item_name] = text
                    else:
                        # If empty => uncheck
                        cb = self.checkboxes_by_category[category][item_name]
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                        self.parent_app.update_context_in_real_time()
                        return
                else:
                    # If user canceled => revert
                    cb = self.checkboxes_by_category[category][item_name]
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                    self.parent_app.update_context_in_real_time()
                    return
            else:
                # Normal snippet
                self.selected_snippets.setdefault(category, {})[item_name] = None
        else:
            # Unchecked => remove
            if category in self.selected_snippets and item_name in self.selected_snippets[category]:
                del self.selected_snippets[category][item_name]
                if not self.selected_snippets[category]:
                    del self.selected_snippets[category]

        # Rebuild final prompt
        self.parent_app.update_context_in_real_time()

    def build_instructions_xml(self):
        """
        Always produce <instructions>...</instructions>, even if no items selected.
        """
        lines = []
        lines.append("<instructions>")
        # If no items are chosen, this remains empty in the middle
        for category in PROMPT_CONFIG.keys():
            if category not in self.selected_snippets:
                continue
            cat_lower = category.lower()
            items_chosen = self.selected_snippets[category]
            if not items_chosen:
                continue

            lines.append(f"    <{cat_lower}>")
            for item_name in items_chosen:
                if item_name == "Custom":
                    custom_text = self.selected_snippets[category]["Custom"]
                    lines.append(f"        {custom_text}")
                else:
                    snippet = PROMPT_CONFIG[category][item_name]
                    lines.append(f"        {snippet}")
            lines.append(f"    </{cat_lower}>")
        lines.append("</instructions>\n")
        return "\n".join(lines)


class FileTab(QFrame):
    """
    A single "project tab" with a QTreeWidget of files/folders + filter & options.
    """

    def __init__(self, parent_notebook, app, directory=None):
        super().__init__()
        self.app = app
        self.last_selected_folder = directory

        self.include_subdirs = True
        self.ignore_env = True
        self.ignore_init = True
        self.hide_system = True
        self.search_text = ""
        self.sort_mode = SORT_NAME

        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        # Top row: folder, refresh, sort, filter, expand/collapse
        top_row = QHBoxLayout()
        main_layout.addLayout(top_row)

        self.open_folder_button = QPushButton("Select Folder")
        self.open_folder_button.clicked.connect(self.select_folder)
        top_row.addWidget(self.open_folder_button)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.list_files)
        top_row.addWidget(self.refresh_button)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([SORT_NAME, SORT_SIZE, SORT_MOD_TIME, SORT_NONE])
        self.sort_combo.currentTextChanged.connect(self.on_sort_changed)
        top_row.addWidget(self.sort_combo)

        filter_label = QLabel("Filter:")
        top_row.addWidget(filter_label)

        self.filter_edit = QLineEdit()
        self.filter_edit.textChanged.connect(self.on_filter_text_changed)
        top_row.addWidget(self.filter_edit)

        self.expand_button = QPushButton("+")
        self.expand_button.setToolTip("Expand all directories")
        self.expand_button.clicked.connect(self.expand_all)
        top_row.addWidget(self.expand_button)

        self.collapse_button = QPushButton("-")
        self.collapse_button.setToolTip("Collapse all directories")
        self.collapse_button.clicked.connect(self.collapse_all)
        top_row.addWidget(self.collapse_button)

        # Middle row: checkboxes on left, tree on right
        middle_row = QHBoxLayout()
        main_layout.addLayout(middle_row)

        checkbox_layout = QVBoxLayout()
        middle_row.addLayout(checkbox_layout)

        self.cb_include_subdirs = QCheckBox("Include Subdirs")
        self.cb_include_subdirs.setChecked(True)
        self.cb_include_subdirs.stateChanged.connect(self.update_options)
        checkbox_layout.addWidget(self.cb_include_subdirs)

        self.cb_ignore_env = QCheckBox("Ignore Env")
        self.cb_ignore_env.setChecked(True)
        self.cb_ignore_env.stateChanged.connect(self.update_options)
        checkbox_layout.addWidget(self.cb_ignore_env)

        self.cb_ignore_init = QCheckBox("Ignore __init__")
        self.cb_ignore_init.setChecked(True)
        self.cb_ignore_init.stateChanged.connect(self.update_options)
        checkbox_layout.addWidget(self.cb_ignore_init)

        self.cb_hide_system = QCheckBox("Hide System")
        self.cb_hide_system.setChecked(True)
        self.cb_hide_system.stateChanged.connect(self.update_options)
        checkbox_layout.addWidget(self.cb_hide_system)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        checkbox_layout.addWidget(spacer)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Fullpath", "Size", "Modified"])
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnWidth(0, 300)

        # WARNING fix: "Unresolved attribute reference 'ShowIndicator'"
        # Instead of QTreeWidgetItem.ShowIndicator, in PySide6 we do:
        #   QTreeWidgetItem.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        # We'll set that below in code. It's slightly different usage.

        self.tree.itemExpanded.connect(lambda item: self.tree.resizeColumnToContents(0))
        self.tree.itemCollapsed.connect(lambda item: self.tree.resizeColumnToContents(0))
        self.tree.itemChanged.connect(self.on_item_changed)

        middle_row.addWidget(self.tree, stretch=1)

        if self.last_selected_folder:
            self.list_files()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", "")
        if folder:
            self.last_selected_folder = folder
            self.list_files()

    def update_options(self):
        self.include_subdirs = self.cb_include_subdirs.isChecked()
        self.ignore_env = self.cb_ignore_env.isChecked()
        self.ignore_init = self.cb_ignore_init.isChecked()
        self.hide_system = self.cb_hide_system.isChecked()
        self.list_files()

    def on_sort_changed(self, new_val):
        self.sort_mode = new_val
        self.list_files()

    def on_filter_text_changed(self, new_text):
        self.search_text = new_text.strip().lower()
        self.list_files()

    def list_files(self):
        self.tree.clear()
        if not self.last_selected_folder or not os.path.isdir(self.last_selected_folder):
            return

        root_item = QTreeWidgetItem(self.tree)
        root_path = self.last_selected_folder
        root_name = os.path.basename(root_path) or root_path
        root_item.setText(0, root_name)
        root_item.setText(1, root_path)
        root_item.setCheckState(0, Qt.Unchecked)

        # WARNING fix:
        # Instead of QTreeWidgetItem.ShowIndicator:
        #   root_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        from PySide6.QtWidgets import QTreeWidgetItem as TWI
        root_item.setChildIndicatorPolicy(TWI.ChildIndicatorPolicy.ShowIndicator)

        root_item.setData(0, Qt.UserRole, True)

        if self.include_subdirs:
            matched_any = self.build_filtered_tree(root_item, root_path)
            if not matched_any:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(root_item))
        else:
            self.populate_flat(root_item, root_path)

        self.tree.expandItem(root_item)
        self.app.update_context_in_real_time()

    def build_filtered_tree(self, parent_item, path):
        folder_name = os.path.basename(path).lower()
        dir_matches_by_name = (self.search_text in folder_name) if self.search_text else True

        try:
            entries = os.listdir(path)
        except OSError as e:  # narrower exception than plain 'except:'
            return dir_matches_by_name

        if self.ignore_env:
            entries = [e for e in entries if e.lower() not in VENV_DIR_NAMES]
        if self.hide_system:
            entries = [e for e in entries if e not in SYSTEM_DIRS]

        subdirs = []
        files = []
        for e in entries:
            fp = os.path.join(path, e)
            if os.path.isdir(fp):
                subdirs.append(e)
            else:
                if self.should_list_file(e, fp):
                    files.append(e)

        subdirs = self.sort_entries(path, subdirs, is_dir=True)
        files = self.sort_entries(path, files, is_dir=False)

        subdir_matches_exist = False
        for d in subdirs:
            full_d = os.path.join(path, d)
            sub_item = QTreeWidgetItem(parent_item)
            sub_item.setText(0, d)
            sub_item.setText(1, full_d)
            sub_item.setCheckState(0, Qt.Unchecked)

            # ShowIndicator fix:
            from PySide6.QtWidgets import QTreeWidgetItem as TWI
            sub_item.setChildIndicatorPolicy(TWI.ChildIndicatorPolicy.ShowIndicator)

            sub_item.setData(0, Qt.UserRole, True)

            matched = self.build_filtered_tree(sub_item, full_d)
            if not matched:
                parent_item.removeChild(sub_item)
            else:
                subdir_matches_exist = True
                parent_item.setExpanded(True)

        file_matches_exist = False
        for f in files:
            fp = os.path.join(path, f)
            file_name_lower = f.lower()
            if self.search_text and (self.search_text not in file_name_lower):
                continue
            sz = os.path.getsize(fp)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fp)))

            file_item = QTreeWidgetItem(parent_item)
            file_item.setText(0, f)
            file_item.setText(1, fp)
            file_item.setText(2, str(sz))
            file_item.setText(3, mtime)
            file_item.setCheckState(0, Qt.Unchecked)
            file_item.setData(0, Qt.UserRole, False)
            file_matches_exist = True

        anything_matched = (dir_matches_by_name or subdir_matches_exist or file_matches_exist)
        return anything_matched

    def populate_flat(self, root_item, path):
        try:
            entries = os.listdir(path)
        except OSError as e:
            return
        if self.ignore_env:
            entries = [e for e in entries if e.lower() not in VENV_DIR_NAMES]
        if self.hide_system:
            entries = [e for e in entries if e not in SYSTEM_DIRS]

        subdirs = []
        files = []
        for e in entries:
            fp = os.path.join(path, e)
            if os.path.isdir(fp):
                subdirs.append(e)
            else:
                if self.should_list_file(e, fp):
                    files.append(e)

        subdirs = self.sort_entries(path, subdirs, is_dir=True)
        files = self.sort_entries(path, files, is_dir=False)

        for d in subdirs:
            if self.search_text and (self.search_text not in d.lower()):
                continue
            fp = os.path.join(path, d)
            item = QTreeWidgetItem(root_item)
            item.setText(0, d)
            item.setText(1, fp)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, True)

        for f in files:
            if self.search_text and (self.search_text not in f.lower()):
                continue
            fp = os.path.join(path, f)
            sz = os.path.getsize(fp)
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fp)))
            item = QTreeWidgetItem(root_item)
            item.setText(0, f)
            item.setText(1, fp)
            item.setText(2, str(sz))
            item.setText(3, mtime)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, False)

    def sort_entries(self, parent_path, entries, is_dir=False):
        if self.sort_mode == SORT_NONE:
            return entries
        elif self.sort_mode == SORT_NAME:
            return sorted(entries, key=lambda x: x.lower())
        elif is_dir:
            # fallback to alphabetical
            return sorted(entries, key=lambda x: x.lower())
        elif self.sort_mode == SORT_SIZE:
            return sorted(
                entries,
                key=lambda x: os.path.getsize(os.path.join(parent_path, x)),
                reverse=True
            )
        elif self.sort_mode == SORT_MOD_TIME:
            return sorted(
                entries,
                key=lambda x: os.path.getmtime(os.path.join(parent_path, x)),
                reverse=True
            )
        return entries

    def should_list_file(self, fname, fullpath):
        # Filter out system or non-ext files
        if self.hide_system and fname in SYSTEM_FILES:
            return False
        if not fname.lower().endswith(FILE_EXTENSIONS):
            return False
        # If ignoring empty __init__.py
        if self.ignore_init and self.is_init_file(fname):
            if self.should_ignore_init_file(fullpath):
                return False
        return True

    @staticmethod
    def is_init_file(fname):
        base, ext = os.path.splitext(fname)
        return (base == "__init__" and ext == ".py")

    @staticmethod
    def should_ignore_init_file(path):
        """
        If the file is an empty __init__.py, skip it.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            code_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith('#')]
            return (len(code_lines) == 0)
        except OSError:
            return False

    def on_item_changed(self, item, column):
        if column == 0:
            is_dir = item.data(0, Qt.UserRole)
            if is_dir:
                self.tree.blockSignals(True)
                state = item.checkState(0)
                self.apply_check_to_descendants(item, state)
                self.tree.blockSignals(False)
            self.app.update_context_in_real_time()

    def apply_check_to_descendants(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            if child.data(0, Qt.UserRole) is True:
                self.apply_check_to_descendants(child, state)

    def gather_all_files_under_directory(self, directory):
        gathered_files = []
        for root, dirs, fs in os.walk(directory):
            if self.ignore_env:
                dirs[:] = [d for d in dirs if d.lower() not in VENV_DIR_NAMES]
            if self.hide_system:
                dirs[:] = [d for d in dirs if d not in SYSTEM_DIRS]
            for f in fs:
                if self.hide_system and f in SYSTEM_FILES:
                    continue
                fp = os.path.join(root, f)
                if self.should_list_file(f, fp):
                    gathered_files.append(fp)
        return gathered_files

    def get_all_checked_items(self):
        results = []
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            self.collect_checked_items(root_item, results)
        return results

    def collect_checked_items(self, item, results):
        if item.checkState(0) == Qt.Checked:
            results.append(item)
        for i in range(item.childCount()):
            self.collect_checked_items(item.child(i), results)

    def expand_all(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            self.recursive_expand(root_item, True)
        self.tree.blockSignals(False)

    def collapse_all(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            self.recursive_expand(root_item, False)
        self.tree.blockSignals(False)

    def recursive_expand(self, item, expand):
        item.setExpanded(expand)
        for i in range(item.childCount()):
            child = item.child(i)
            self.recursive_expand(child, expand)


class FileContentApp(QMainWindow):
    """
    Main window with left side: tabs,
    right side: vertical splitter => top = prompt builder, bottom = prompt text area.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Content Viewer (Qt)")

        # If tiktoken is installed, use it. Otherwise, skip token counting
        self.encoder = None
        if tiktoken:
            try:
                self.encoder = tiktoken.get_encoding("cl100k_base")
            except:
                self.encoder = tiktoken.get_encoding("gpt2")

        self.resize(1300, 800)

        self.main_splitter = QSplitter(self)
        self.main_splitter.setOrientation(Qt.Horizontal)
        self.setCentralWidget(self.main_splitter)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        self.tabs = QTabWidget()
        left_layout.addWidget(self.tabs)
        self.main_splitter.addWidget(left_container)

        self.right_splitter = QSplitter(self)
        self.right_splitter.setOrientation(Qt.Vertical)

        # Prompt Builder
        self.prompt_builder = PromptBuilder(self)
        self.right_splitter.addWidget(self.prompt_builder)

        # Bottom half: text area
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)

        prompt_label = QLabel("Prompt")
        prompt_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        bottom_layout.addWidget(prompt_label, alignment=Qt.AlignLeft)

        self.content_text = QTextEdit()
        self.content_text.setAcceptRichText(False)
        bottom_layout.addWidget(self.content_text)

        button_bar = QHBoxLayout()
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_content)
        button_bar.addWidget(self.clear_button)

        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_content)
        button_bar.addWidget(self.copy_button)

        self.word_count_label = QLabel("Words: 0")
        self.char_count_label = QLabel("Characters: 0")
        self.token_count_label = QLabel("Tokens: 0")
        button_bar.addWidget(self.word_count_label)
        button_bar.addWidget(self.char_count_label)
        button_bar.addWidget(self.token_count_label)

        self.dark_mode_button = QPushButton("Toggle Dark Mode")
        self.dark_mode_button.clicked.connect(self.toggle_dark_mode)
        button_bar.addWidget(self.dark_mode_button)

        bottom_layout.addLayout(button_bar)
        self.right_splitter.addWidget(bottom_container)

        self.main_splitter.addWidget(self.right_splitter)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        new_tab_action = QAction("New Project Tab", self)
        new_tab_action.triggered.connect(self.add_new_tab)
        file_menu.addAction(new_tab_action)

        rename_tab_action = QAction("Rename Current Tab", self)
        rename_tab_action.triggered.connect(self.rename_current_tab)
        file_menu.addAction(rename_tab_action)

        remove_tab_action = QAction("Remove Current Tab", self)
        remove_tab_action.triggered.connect(self.remove_current_tab)
        file_menu.addAction(remove_tab_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        self.load_config()

        # Optionally set top/bottom splitter ratio
        self.right_splitter.setSizes([400, 400])

        # Initialize empty instructions/context
        self.update_context_in_real_time()

    def add_new_tab(self, directory=None, title="New Project"):
        new_tab = FileTab(self.tabs, self, directory=directory)
        idx = self.tabs.addTab(new_tab, title)
        self.tabs.setCurrentIndex(idx)

    def rename_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        new_name, ok = QInputDialog().getText(self, "Rename Tab", "Enter new tab name:")
        if ok and new_name:
            self.tabs.setTabText(idx, new_name)

    def remove_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx >= 0:
            self.tabs.removeTab(idx)
            self.update_context_in_real_time()

    def clear_content(self):
        """
        Uncheck all items in all tabs, uncheck prompt builder, clear text.
        """
        self.content_text.clear()

        # Uncheck file items
        for i in range(self.tabs.count()):
            tab_widget = self.tabs.widget(i)
            tab_widget.tree.blockSignals(True)
            self.uncheck_all(tab_widget.tree.invisibleRootItem())
            tab_widget.tree.blockSignals(False)

        # Uncheck prompt builder
        for cat, items_dict in self.prompt_builder.checkboxes_by_category.items():
            for item_name, cb in items_dict.items():
                if cb.isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)

        self.prompt_builder.selected_snippets.clear()

        self.update_context_in_real_time()

    def uncheck_all(self, parent_item):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, Qt.Unchecked)
            self.uncheck_all(child)

    def copy_content(self):
        text = self.content_text.toPlainText()
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Content copied to clipboard.")

    def update_context_in_real_time(self):
        """
        Rebuild the final prompt:
          1) <instructions> from PromptBuilder
          2) <context> from checked files
        """
        self.content_text.clear()

        instructions_block = self.prompt_builder.build_instructions_xml()

        unique_files = set()
        for i in range(self.tabs.count()):
            tab_widget = self.tabs.widget(i)
            checked_items = tab_widget.get_all_checked_items()
            for item in checked_items:
                fp = item.text(1)
                is_dir = item.data(0, Qt.UserRole)
                if is_dir:
                    subfiles = tab_widget.gather_all_files_under_directory(fp)
                    for sf in subfiles:
                        unique_files.add(sf)
                else:
                    unique_files.add(fp)

        context_lines = []
        context_lines.append("<context>")
        for fpath in sorted(unique_files):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except OSError as e:
                content = f"ERROR reading file {fpath}: {e}"
            filename_only = os.path.basename(fpath)
            context_lines.append(f"    <file name='{filename_only}'>\n{content}\n    </file>")
        context_lines.append("</context>\n")

        final_text = instructions_block + "\n" + "\n".join(context_lines)
        self.content_text.insertPlainText(final_text)
        self.update_counts()

    def update_counts(self):
        content = self.content_text.toPlainText()
        words = len(content.split())
        chars = len(content)
        tokens = 0
        if self.encoder:
            tokens = len(self.encoder.encode(content))

        self.word_count_label.setText(f"Words: {words}")
        self.char_count_label.setText(f"Characters: {chars}")
        self.token_count_label.setText(f"Tokens: {tokens}")

    def toggle_dark_mode(self):
        dark = self.is_dark_mode()
        self.set_dark_mode(not dark)

    def is_dark_mode(self):
        # QPalette window color
        bg = self.palette().window().color()
        return (bg.value() < 128)

    def set_dark_mode(self, enabled):
        pal = self.palette()
        if enabled:
            # Fix for "Unresolved attribute reference 'Window', 'WindowText' etc."
            # Official usage is pal.setColor(QPalette.ColorRole.Window, QColor(...))
            pal.setColor(QPalette.ColorRole.Window, QColor(46, 46, 46))
            pal.setColor(QPalette.ColorRole.WindowText, Qt.white)
            pal.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(46, 46, 46))
            pal.setColor(QPalette.ColorRole.ToolTipBase, Qt.white)
            pal.setColor(QPalette.ColorRole.ToolTipText, Qt.white)
            pal.setColor(QPalette.ColorRole.Text, Qt.white)
            pal.setColor(QPalette.ColorRole.Button, QColor(46, 46, 46))
            pal.setColor(QPalette.ColorRole.ButtonText, Qt.white)
            pal.setColor(QPalette.ColorRole.BrightText, Qt.red)
            pal.setColor(QPalette.ColorRole.Highlight, QColor(70, 70, 70))
            pal.setColor(QPalette.ColorRole.HighlightedText, Qt.white)
            self.setPalette(pal)
        else:
            self.setPalette(QApplication.style().standardPalette())

    def save_config(self):
        tab_data = []
        for i in range(self.tabs.count()):
            tab_widget = self.tabs.widget(i)
            directory = tab_widget.last_selected_folder
            title = self.tabs.tabText(i)
            tab_data.append({"directory": directory, "title": title})
        config = {"tabs": tab_data}
        try:
            with open(CONFIG_FILE, "w", encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except OSError:
            pass

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    data = json.load(f)
                for t in data.get("tabs", []):
                    directory = t.get("directory", None)
                    title = t.get("title", "Project")
                    self.add_new_tab(directory=directory, title=title)
                return
            except OSError:
                pass
        # If no config or error => just one tab
        self.add_new_tab()

    def closeEvent(self, event):
        self.save_config()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = FileContentApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
