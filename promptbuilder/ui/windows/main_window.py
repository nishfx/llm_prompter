# promptbuilder/ui/windows/main_window.py
from pathlib import Path
import html # Import html for escaping errors
from typing import Set # Use Set for paths

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QSplitter, QTabWidget, QPushButton, QLabel,
                             QMessageBox, QFileDialog, QInputDialog, QMenuBar,
                             QStatusBar, QProgressBar, QSizePolicy, QSpacerItem,
                             QApplication) # Added QApplication for clipboard
from PySide6.QtGui import QAction, QKeySequence, QIcon, QFontDatabase, QFont, QActionGroup # Added QActionGroup
from PySide6.QtCore import Qt, Slot, Signal, QByteArray, QSettings, QTimer, QObject # Added QObject

from loguru import logger

from ..widgets.project_tab import ProjectTabWidget
from ..widgets.prompt_panel import PromptPanelWidget
from ..widgets.text_edit import PromptTextEdit
from ...config.loader import get_config, save_config
from ...config.schema import TabConfig, AppConfig
from ...services.theming import Theme, apply_theme
from ...services.async_utils import run_in_background # Use helper to run tasks
# Import the *adapter* tasks, not the core logic directly
from ...core.fs_scanner import FileScannerTask # Adapter
from ...core.context_assembler import ContextAssemblerTask # Adapter
from ...core.models import ContextResult, FileNode
from ...core.prompt_engine import PromptEngine
# Fixes Blocker B-4: Check TIKTOKEN_AVAILABLE flag
from ...core.token_counter import count_tokens_sync, TIKTOKEN_AVAILABLE

# Assume icons are in an 'assets' folder copied by PyInstaller/build process
# from ..config.paths import get_bundle_dir # Helper to find assets
# ICON_COPY = get_bundle_dir() / "assets/copy.png"
# ICON_CLEAR = get_bundle_dir() / "assets/clear.png"
# ICON_FOLDER = get_bundle_dir() / "assets/folder.png"
# ICON_SAVE = get_bundle_dir() / "assets/save.png"
# ICON_THEME = get_bundle_dir() / "assets/theme.png"


class MainWindow(QMainWindow):
    """Main application window."""

    # Signal to indicate context needs rebuilding (debounced)
    request_context_rebuild = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("PromptBuilder")
        # self.setWindowIcon(QIcon(str(get_bundle_dir() / "assets/app_icon.png"))) # Set app icon

        self.config = get_config()
        self.prompt_engine = PromptEngine()
        self.current_context_task_runner: ContextAssemblerTask | None = None # Store the QRunnable adapter instance
        self._tiktoken_warning_shown = False # Flag to show warning only once

        # Debounce timer for context rebuild requests
        self.rebuild_debounce_timer = QTimer(self)
        self.rebuild_debounce_timer.setInterval(350) # ms delay
        self.rebuild_debounce_timer.setSingleShot(True)
        self.rebuild_debounce_timer.timeout.connect(self._trigger_context_assembly)

        self._setup_ui()
        self._setup_menus()
        self._setup_statusbar()
        self._connect_signals()

        self._load_state() # Load window geometry and tabs
        self._request_rebuild_context_debounced() # Initial prompt update (debounced)

        logger.info("MainWindow initialized.")
        # Check for tiktoken availability after init
        self._check_tiktoken_availability()

    # --- UI Setup, Menus, Statusbar, Connections (No changes needed here) ---
    def _setup_ui(self):
        """Create and arrange UI elements."""
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(self.main_splitter)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True); self.tabs.setMovable(True)
        right_container = QWidget(); right_layout = QVBoxLayout(right_container); right_layout.setContentsMargins(0,0,0,0)
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.prompt_panel = PromptPanelWidget(self.config.prompt_snippets, self.config.common_questions)
        self.right_splitter.addWidget(self.prompt_panel)
        preview_container = QWidget(); preview_layout = QVBoxLayout(preview_container); preview_layout.setContentsMargins(5,5,5,5)
        preview_label = QLabel("Generated Prompt Preview"); preview_label.setStyleSheet("font-weight: bold;"); preview_layout.addWidget(preview_label)
        self.prompt_preview_edit = PromptTextEdit()
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont); self.prompt_preview_edit.setFont(fixed_font)
        preview_layout.addWidget(self.prompt_preview_edit)
        bottom_bar_layout = QHBoxLayout(); self.clear_button = QPushButton("Clear All"); self.copy_button = QPushButton("Copy")
        self.word_count_label = QLabel("Words: 0"); self.char_count_label = QLabel("Chars: 0"); self.token_count_label = QLabel("Tokens: 0")
        bottom_bar_layout.addWidget(self.clear_button); bottom_bar_layout.addWidget(self.copy_button); bottom_bar_layout.addStretch(1)
        bottom_bar_layout.addWidget(self.word_count_label); bottom_bar_layout.addSpacerItem(QSpacerItem(10, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        bottom_bar_layout.addWidget(self.char_count_label); bottom_bar_layout.addSpacerItem(QSpacerItem(10, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        bottom_bar_layout.addWidget(self.token_count_label); preview_layout.addLayout(bottom_bar_layout)
        self.right_splitter.addWidget(preview_container); right_layout.addWidget(self.right_splitter)
        self.main_splitter.addWidget(self.tabs); self.main_splitter.addWidget(right_container)
        total_width = self.width() if self.width() > 800 else 1200
        self.main_splitter.setSizes([int(total_width * 0.4), int(total_width * 0.6)])
        self.right_splitter.setSizes([int(self.height() * 0.5), int(self.height() * 0.5)])
    def _setup_menus(self):
        menubar = self.menuBar(); file_menu = menubar.addMenu("&File")
        self.new_tab_action = file_menu.addAction("&New Project Tab", self.add_new_tab, QKeySequence.StandardKey.New)
        self.open_folder_action = file_menu.addAction("&Open Folder in Tab...", self._open_folder_in_current_tab, QKeySequence.StandardKey.Open)
        self.rename_tab_action = file_menu.addAction("&Rename Current Tab...", self.rename_current_tab)
        self.close_tab_action = file_menu.addAction("&Close Current Tab", self.remove_current_tab, QKeySequence.StandardKey.Close)
        file_menu.addSeparator(); self.save_config_action = file_menu.addAction("&Save Configuration", self._save_state_now, QKeySequence.StandardKey.Save)
        file_menu.addSeparator(); self.quit_action = file_menu.addAction("&Quit", self.close, QKeySequence.StandardKey.Quit)
        edit_menu = menubar.addMenu("&Edit"); self.copy_action = edit_menu.addAction("&Copy Prompt", self.copy_content, QKeySequence.StandardKey.Copy)
        self.clear_action = edit_menu.addAction("C&lear All Selections", self.clear_all)
        view_menu = menubar.addMenu("&View"); theme_menu = view_menu.addMenu("Theme"); self.theme_group = QActionGroup(self); self.theme_group.setExclusive(True)
        auto_action = self.theme_group.addAction("Auto"); auto_action.setCheckable(True); auto_action.triggered.connect(lambda: self._change_theme(Theme.AUTO)); theme_menu.addAction(auto_action)
        light_action = self.theme_group.addAction("Light"); light_action.setCheckable(True); light_action.triggered.connect(lambda: self._change_theme(Theme.LIGHT)); theme_menu.addAction(light_action)
        dark_action = self.theme_group.addAction("Dark"); dark_action.setCheckable(True); dark_action.triggered.connect(lambda: self._change_theme(Theme.DARK)); theme_menu.addAction(dark_action)
        current_theme_str = self.config.theme
        if current_theme_str == Theme.LIGHT.value: light_action.setChecked(True)
        elif current_theme_str == Theme.DARK.value: dark_action.setChecked(True)
        else: auto_action.setChecked(True)
        self.toggle_statusbar_action = view_menu.addAction("Toggle Status Bar", self._toggle_statusbar); self.toggle_statusbar_action.setCheckable(True); self.toggle_statusbar_action.setChecked(True)
        help_menu = menubar.addMenu("&Help"); self.about_action = help_menu.addAction("&About", self._show_about_dialog)
    def _setup_statusbar(self):
        self.status_bar = QStatusBar(self); self.setStatusBar(self.status_bar); self.status_label = QLabel("Ready")
        self.status_progress = QProgressBar(); self.status_progress.setRange(0, 0); self.status_progress.setVisible(False); self.status_progress.setFixedWidth(150)
        self.status_bar.addWidget(self.status_label, 1); self.status_bar.addPermanentWidget(self.status_progress)
    def _connect_signals(self):
        self.tabs.tabCloseRequested.connect(self.remove_tab_by_index); self.tabs.currentChanged.connect(self._on_tab_changed)
        self.prompt_panel.snippets_changed.connect(self._request_rebuild_context_debounced)
        self.copy_button.clicked.connect(self.copy_content); self.clear_button.clicked.connect(self.clear_all)
    def _connect_tab_signals(self, tab_widget: ProjectTabWidget):
        tab_widget.selection_changed.connect(self._request_rebuild_context_debounced)
        tab_widget.scan_started.connect(self._on_scan_started); tab_widget.scan_finished.connect(self._on_scan_finished)
        tab_widget.scan_progress.connect(self._show_status_message); tab_widget.scan_error.connect(self._on_scan_error)
    def _disconnect_tab_signals(self, tab_widget: ProjectTabWidget):
        try:
            tab_widget.selection_changed.disconnect(self._request_rebuild_context_debounced)
            tab_widget.scan_started.disconnect(self._on_scan_started); tab_widget.scan_finished.disconnect(self._on_scan_finished)
            tab_widget.scan_progress.disconnect(self._show_status_message); tab_widget.scan_error.disconnect(self._on_scan_error)
        except RuntimeError as e: logger.warning(f"Error disconnecting signals: {e}")
    @Slot()
    def _request_rebuild_context_debounced(self):
        logger.trace("Debounce timer restarted for context rebuild."); self.rebuild_debounce_timer.start()

    # --- State Management (No changes needed here) ---
    def _load_state(self):
        logger.info("Loading window state and tabs...")
        try:
            if self.config.window_geometry:
                geom_hex = self.config.window_geometry; geom = QByteArray.fromHex(geom_hex if isinstance(geom_hex, bytes) else geom_hex.encode('ascii'))
                if not self.restoreGeometry(geom): logger.warning("Failed to restore window geometry."); self.resize(1200, 800)
            else: self.resize(1200, 800)
            if self.config.window_state:
                state_hex = self.config.window_state; w_state = QByteArray.fromHex(state_hex if isinstance(state_hex, bytes) else state_hex.encode('ascii'))
                if not self.restoreState(w_state): logger.warning("Failed to restore window state.")
        except Exception as e: logger.error(f"Error restoring window state/geometry: {e}"); self.resize(1200, 800)
        self.tabs.clear()
        if not self.config.tabs: self.add_new_tab(title="Default Project", activate=True)
        else:
            for i, tab_config in enumerate(self.config.tabs): self.add_new_tab(config=tab_config, activate=(i == 0))
        if self.tabs.count() == 0: self.add_new_tab(title="Project 1", activate=True)
        try: apply_theme(Theme(self.config.theme))
        except Exception as e: logger.exception("Error applying theme during state load.")
        logger.info(f"Loaded {self.tabs.count()} tabs.")
    def update_config_before_save(self):
        logger.debug("Updating config object before saving...")
        try: self.config.window_geometry = bytes(self.saveGeometry().toHex()); self.config.window_state = bytes(self.saveState().toHex())
        except Exception as e: logger.error(f"Could not save window geometry/state: {e}")
        self.config.tabs.clear()
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, ProjectTabWidget): tab_conf = widget.get_config(); tab_conf.title = self.tabs.tabText(i); self.config.tabs.append(tab_conf)
            else: logger.warning(f"Widget at tab index {i} is not a ProjectTabWidget.")
        logger.debug("Config object updated.")
    def _save_state_now(self):
        self.update_config_before_save(); save_config(self.config); self._show_status_message("Configuration saved.", 3000)
    def closeEvent(self, event):
        logger.info("Close event triggered. Saving state...")
        if self.current_context_task_runner:
             reply = QMessageBox.question(self, "Task Running", "Context assembly task is running. Quit anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.No: event.ignore(); return
             else: logger.info("Requesting cancellation of context task on close."); self.current_context_task_runner.cancel()
        for i in range(self.tabs.count()):
             widget = self.tabs.widget(i);
             if isinstance(widget, ProjectTabWidget): widget.cancel_scan()
        self.update_config_before_save(); logger.info("Proceeding with close."); event.accept()

    # --- Tab Management (No changes needed here) ---
    @Slot()
    def add_new_tab(self, config: TabConfig | None = None, title: str | None = None, activate=True):
        if config is None: config = TabConfig()
        tab_title = title or config.title or f"Project {self.tabs.count() + 1}"
        logger.info(f"Adding new tab: '{tab_title}' (Dir: {config.directory})")
        new_tab_widget = ProjectTabWidget(config, parent=self.tabs); idx = self.tabs.addTab(new_tab_widget, tab_title)
        self._connect_tab_signals(new_tab_widget)
        if activate: self.tabs.setCurrentIndex(idx)
        if config.directory: QTimer.singleShot(50, new_tab_widget.scan_directory)
    @Slot(int)
    def remove_tab_by_index(self, index: int):
        if index < 0 or index >= self.tabs.count(): return
        widget = self.tabs.widget(index); tab_text = self.tabs.tabText(index); logger.info(f"Removing tab: '{tab_text}' at index {index}")
        if isinstance(widget, ProjectTabWidget): self._disconnect_tab_signals(widget); widget.cancel_scan(); widget.deleteLater()
        self.tabs.removeTab(index)
        if self.tabs.count() == 0: self.add_new_tab(activate=True)
        else: self._request_rebuild_context_debounced()
    @Slot()
    def remove_current_tab(self):
        current_index = self.tabs.currentIndex();
        if current_index != -1: self.remove_tab_by_index(current_index)
    @Slot()
    def rename_current_tab(self):
        idx = self.tabs.currentIndex();
        if idx < 0: return
        current_name = self.tabs.tabText(idx); new_name, ok = QInputDialog.getText(self, "Rename Tab", "Enter new tab name:", text=current_name)
        if ok and new_name and new_name != current_name:
            self.tabs.setTabText(idx, new_name); widget = self.tabs.widget(idx)
            if isinstance(widget, ProjectTabWidget): widget.config.title = new_name
            logger.info(f"Renamed tab {idx} to '{new_name}'")
    @Slot(int)
    def _on_tab_changed(self, index: int):
        if index < 0 or index >= self.tabs.count(): logger.warning(f"Tab changed to invalid index: {index}"); self.open_folder_action.setEnabled(False); self.rename_tab_action.setEnabled(False); self.close_tab_action.setEnabled(False); return
        tab_text = self.tabs.tabText(index); logger.debug(f"Switched to tab: '{tab_text}' (Index: {index})")
        self.open_folder_action.setEnabled(True); self.rename_tab_action.setEnabled(True); self.close_tab_action.setEnabled(True)
        self._request_rebuild_context_debounced()
    @Slot()
    def _open_folder_in_current_tab(self):
        current_widget = self.tabs.currentWidget()
        if not isinstance(current_widget, ProjectTabWidget): QMessageBox.warning(self, "No Active Project", "Please select a project tab first."); return
        current_dir = current_widget.get_config().directory or str(Path.home()); folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", current_dir)
        if folder: folder_path = Path(folder); logger.info(f"Setting folder for tab '{self.tabs.tabText(self.tabs.currentIndex())}': {folder_path}"); current_widget.set_directory(folder_path); self.tabs.setTabText(self.tabs.currentIndex(), folder_path.name)

    # --- Tiktoken Check ---
    def _check_tiktoken_availability(self):
        """Checks if tiktoken is available and shows a warning if not."""
        if not TIKTOKEN_AVAILABLE and not self._tiktoken_warning_shown:
            logger.warning("Tiktoken library not found or failed to load. Token counts will be estimated.")
            # Fixes Blocker B-4: Show persistent status bar message
            self._show_status_message("Warning: Token counts are estimated (tiktoken unavailable)", 0)
            # Optionally show a one-time message box (might be annoying)
            # QMessageBox.warning(self, "Token Count Estimation",
            #                     "The 'tiktoken' library is unavailable.\n"
            #                     "Token counts displayed will be estimates based on character count.\n"
            #                     "Install 'tiktoken' (and potentially C++ build tools) for accurate counts.")
            self._tiktoken_warning_shown = True # Show only once per session

    # --- Prompt Generation ---

    @Slot()
    def _trigger_context_assembly(self):
        """Gathers selections and triggers context assembly task."""
        logger.debug("Debounced trigger for context assembly.")
        if self.current_context_task_runner:
            logger.warning("Cancelling previous context assembly task.")
            self.current_context_task_runner.cancel()
            # Do NOT clear reference here, wait for signal handler

        all_selected_paths: Set[Path] = set()
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, ProjectTabWidget): all_selected_paths.update(widget.get_selected_file_paths())

        selected_snippets, selected_questions = self.prompt_panel.get_selected_items()
        instructions_xml = self.prompt_engine.build_instructions_xml(selected_snippets, selected_questions)

        if not all_selected_paths:
            logger.debug("No files selected, generating prompt with instructions only.")
            final_prompt = instructions_xml + "\n\n<context>\n</context>"
            self.prompt_preview_edit.setPlainText(final_prompt)
            self._update_counts(final_prompt)
            self._show_status_message("Ready (No files selected)", 5000, show_progress=False)
            self.token_count_label.setText("Tokens: 0")
            self.current_context_task_runner = None # Ensure cleared
            return

        logger.info(f"Starting context assembly task for {len(all_selected_paths)} selected file paths.")
        self._show_status_message("Assembling context...", 0, show_progress=True)

        context_task = ContextAssemblerTask(
            selected_paths=all_selected_paths, max_tokens=self.config.max_context_tokens,
            secret_patterns=self.config.secret_patterns
        )
        self.current_context_task_runner = context_task # Store reference *before* connecting

        context_task.signals.finished.connect(lambda result, task=context_task: self._on_context_assembly_finished(result, task))
        context_task.signals.error.connect(lambda error_message, task=context_task: self._on_context_assembly_error(error_message, task))
        context_task.signals.progress.connect(self._show_status_message)
        run_in_background(context_task)


    @Slot(object, QObject) # Receives ContextResult, Task instance
    def _on_context_assembly_finished(self, result: ContextResult, task: ContextAssemblerTask):
        """Called when the ContextAssemblerTask finishes successfully."""
        if task != self.current_context_task_runner:
             logger.warning("Received 'finished' signal from an outdated/cancelled context task. Ignoring.")
             return # Ignore signal from old/cancelled task
        self.current_context_task_runner = None # Clear reference now we know it's the right task
        logger.info(f"Context assembly finished. Tokens: {result.total_tokens}. Budget: {result.budget_details}")
        self._show_status_message(f"Context ready. {result.budget_details or 'All files included.'}", 5000, show_progress=False)
        selected_snippets, selected_questions = self.prompt_panel.get_selected_items()
        instructions_xml = self.prompt_engine.build_instructions_xml(selected_snippets, selected_questions)
        final_prompt = instructions_xml + "\n\n" + result.context_xml
        self.prompt_preview_edit.setPlainText(final_prompt)
        self._update_counts(final_prompt, result.total_tokens)


    @Slot(str, QObject) # Receives error_message, Task instance
    def _on_context_assembly_error(self, error_message: str, task: ContextAssemblerTask):
        """Called when the ContextAssemblerTask fails."""
        if task != self.current_context_task_runner:
             logger.warning("Received 'error' signal from an outdated/cancelled context task. Ignoring.")
             return # Ignore signal from old/cancelled task
        self.current_context_task_runner = None # Clear reference now we know it's the right task
        logger.error(f"Context assembly failed: {error_message}")
        self.status_progress.setVisible(False)
        is_cancel_error = "cancel" in error_message.lower()
        if not is_cancel_error:
            self._show_status_message(f"Error: {error_message}", 0)
            QMessageBox.warning(self, "Context Error", f"Failed to assemble context:\n{error_message}")
        else:
             self._show_status_message(f"Context assembly cancelled.", 4000)
        selected_snippets, selected_questions = self.prompt_panel.get_selected_items()
        instructions_xml = self.prompt_engine.build_instructions_xml(selected_snippets, selected_questions)
        error_context = f"\n\n<context>\n    <error>{html.escape(error_message)}</error>\n</context>"
        self.prompt_preview_edit.setPlainText(instructions_xml + error_context)
        self._update_counts(instructions_xml + error_context)


    def _update_counts(self, text: str, known_tokens: int | None = None):
        """Update word, char, and token counts in the UI."""
        char_count = len(text)
        word_count = len(text.split())
        self.char_count_label.setText(f"Chars: {char_count:,}")
        self.word_count_label.setText(f"Words: {word_count:,}")

        token_prefix = "Tokens"
        if not TIKTOKEN_AVAILABLE:
            token_prefix = "Tokens (est.)" # Indicate estimation if tiktoken is missing

        if known_tokens is not None:
             self.token_count_label.setText(f"{token_prefix}: {known_tokens:,}")
        else:
            self.token_count_label.setText(f"{token_prefix}: ...")
            try:
                token_count = count_tokens_sync(text)
                self.token_count_label.setText(f"{token_prefix}: {token_count:,}")
            except Exception as e:
                 logger.error(f"Failed to count tokens for preview: {e}")
                 self.token_count_label.setText(f"{token_prefix}: Error")


    # --- Actions (Copy, Clear, Theme, Statusbar, About - No changes needed here) ---
    @Slot()
    def copy_content(self):
        text = self.prompt_preview_edit.toPlainText();
        if text: QApplication.clipboard().setText(text); logger.info(f"Copied {len(text)} characters to clipboard."); self._show_status_message("Prompt copied to clipboard!", 3000)
        else: logger.warning("Attempted to copy empty prompt."); self._show_status_message("Nothing to copy.", 3000)
    @Slot()
    def clear_all(self):
        logger.info("Clearing all selections."); self.prompt_panel.clear_selections()
        for i in range(self.tabs.count()): widget = self.tabs.widget(i);
        if isinstance(widget, ProjectTabWidget): widget.clear_selection()
        self._show_status_message("Selections cleared.", 3000)
    @Slot(Theme)
    def _change_theme(self, theme: Theme):
        logger.info(f"User changed theme to: {theme.name}")
        try: apply_theme(theme); self.config.theme = theme.value; self._show_status_message(f"Theme changed to {theme.name}", 3000)
        except Exception as e: logger.exception(f"Failed to apply theme {theme.name}: {e}"); QMessageBox.warning(self, "Theme Error", f"Could not apply theme: {e}")
    @Slot()
    def _toggle_statusbar(self):
        is_visible = self.status_bar.isVisible(); self.status_bar.setVisible(not is_visible); self.toggle_statusbar_action.setChecked(not is_visible)
    @Slot()
    def _show_about_dialog(self):
        from ... import __version__; QMessageBox.about(self, "About PromptBuilder", f"<b>PromptBuilder v{__version__}</b><br><br>A workbench for crafting LLM prompts.<br><br>(c) 2023-2024 Your Name/Company")

    # --- Status Bar Updates ---
    @Slot(str)
    @Slot(str, int)
    def _show_status_message(self, message: str, timeout: int = 0, show_progress: bool | None = None):
        """Displays a message in the status bar. show_progress=None means don't change."""
        # Avoid overwriting tiktoken warning with transient messages unless persistent
        if self._tiktoken_warning_shown and "Token counts are estimated" in self.status_label.text() and timeout > 0:
             logger.trace(f"Skipping transient status message '{message}' due to active tiktoken warning.")
             return # Don't overwrite the persistent warning with a temporary message

        self.status_label.setText(message)
        if timeout <= 0: self.status_bar.clearMessage()
        else: self.status_bar.showMessage(message, timeout)
        if show_progress is True: self.status_progress.setVisible(True)
        elif show_progress is False: self.status_progress.setVisible(False)

    # --- Scan Status Callbacks (from ProjectTabWidget) ---
    @Slot()
    def _on_scan_started(self):
        self._show_status_message("Scanning files...", 0, show_progress=True)
    @Slot(list) # Receives list[FileNode]
    def _on_scan_finished(self, root_nodes: list):
        self._show_status_message("File scan complete.", 4000, show_progress=False)
        if self.sender() == self.tabs.currentWidget(): self._request_rebuild_context_debounced()
    @Slot(str)
    def _on_scan_error(self, error_msg: str):
         if "cancel" not in error_msg.lower():
             self._show_status_message(f"Scan Error: {error_msg}", 0, show_progress=False)
             QMessageBox.warning(self, "Scan Error", f"Could not scan directory:\n{error_msg}")
         else: self._show_status_message(f"Scan cancelled.", 4000, show_progress=False)