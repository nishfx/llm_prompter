# promptbuilder/ui/widgets/project_tab.py
from pathlib import Path
from typing import List, Set

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLineEdit, QLabel, QCheckBox, QFileDialog, QSizePolicy,
                             QMessageBox, QComboBox, QFrame)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QObject  # Added QTimer
from loguru import logger

from ...config.schema import TabConfig
from ...core.models import FileNode
# Import the *adapter* task
from ...core.fs_scanner import FileScannerTask
from ...services.async_utils import run_in_background, get_global_thread_pool
from .file_tree import FileTreeWidget

class ProjectTabWidget(QWidget):
    """Widget contained within each tab, holding file tree and controls."""

    # Signals
    selection_changed = Signal() # Emitted when file selection changes
    scan_started = Signal()
    scan_finished = Signal(list) # Emits root FileNode list
    scan_progress = Signal(str)
    scan_error = Signal(str)

    def __init__(self, config: TabConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.current_scan_task_runner: FileScannerTask | None = None # Store the QRunnable adapter

        # Debounce timer for filter changes
        self.filter_debounce_timer = QTimer(self)
        self.filter_debounce_timer.setInterval(300) # ms delay
        self.filter_debounce_timer.setSingleShot(True)
        self.filter_debounce_timer.timeout.connect(self._apply_filter_to_tree)

        self._setup_ui()
        self._connect_signals()

        # Load initial state if directory is set
        if self.config.directory:
            self.directory_label.setText(f"Folder: {self.config.directory}")
            # Initial scan is triggered by MainWindow after tab is added and potentially made current

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(main_layout)

        # --- Top Control Bar ---
        control_bar = QHBoxLayout()
        self.select_folder_button = QPushButton("Select Folder...")
        # Add icon?
        control_bar.addWidget(self.select_folder_button)

        self.directory_label = QLabel(f"Folder: {self.config.directory or 'None selected'}")
        self.directory_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.directory_label.setWordWrap(True) # Allow long paths to wrap
        control_bar.addWidget(self.directory_label)

        self.refresh_button = QPushButton("Refresh")
        # Add icon?
        self.refresh_button.setEnabled(bool(self.config.directory)) # Enable only if dir is set
        control_bar.addWidget(self.refresh_button)
        main_layout.addLayout(control_bar)

        # --- Filter/Options Bar ---
        options_bar = QHBoxLayout()
        filter_label = QLabel("Filter:")
        options_bar.addWidget(filter_label)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter files/folders by name...")
        options_bar.addWidget(self.filter_edit)

        # Add sort combo, expand/collapse etc. here if desired
        # self.sort_combo = QComboBox() ...
        # self.expand_button = QPushButton("+") ...
        # self.collapse_button = QPushButton("-") ...

        main_layout.addLayout(options_bar)

        # --- File Tree ---
        self.file_tree = FileTreeWidget() # The actual tree view
        main_layout.addWidget(self.file_tree)

        # --- Optional: Ignore Options (could be global config) ---
        # ignore_frame = QFrame() ...
        # self.cb_ignore_venv = QCheckBox("Ignore venv") ...

    def _connect_signals(self):
        self.select_folder_button.clicked.connect(self.select_directory)
        self.refresh_button.clicked.connect(self.scan_directory)
        # Connect filter text changes to the debounce timer
        self.filter_edit.textChanged.connect(self.filter_debounce_timer.start)

        # Connect file tree's internal signal to this widget's signal
        self.file_tree.item_selection_changed.connect(self.selection_changed.emit)

    # --- Public API ---

    def get_config(self) -> TabConfig:
        """Returns the current configuration state of this tab."""
        # Update config object with current state if needed (e.g., filters)
        # self.config.last_filter = self.filter_edit.text() # Example
        return self.config

    def set_directory(self, directory: Path):
        """Sets the root directory for this tab and triggers a scan."""
        if not directory.is_dir():
             logger.error(f"Invalid directory selected: {directory}")
             QMessageBox.warning(self, "Invalid Folder", f"The selected path is not a valid folder:\n{directory}")
             return

        resolved_dir = str(directory.resolve())
        self.config.directory = resolved_dir
        self.directory_label.setText(f"Folder: {resolved_dir}")
        self.directory_label.setToolTip(resolved_dir) # Show full path on hover
        self.refresh_button.setEnabled(True)
        logger.info(f"Directory set for tab: {resolved_dir}")
        self.scan_directory() # Automatically scan when directory is set

    @Slot()
    def scan_directory(self):
        """Initiates a file scan for the configured directory using the adapter task."""
        if not self.config.directory:
            logger.warning("Scan requested but no directory is set for this tab.")
            # QMessageBox.information(self, "No Folder", "Please select a folder first.")
            return

        if self.current_scan_task_runner:
            logger.warning("Scan already in progress, cancelling previous.")
            self.cancel_scan()
            # Wait briefly? Or let the new scan start immediately?
            # QTimer.singleShot(100, self._start_scan_task) # Option to delay slightly
            self._start_scan_task()
        else:
             self._start_scan_task()


    def _start_scan_task(self):
        """Internal helper to create and run the scan task."""
        if not self.config.directory: return # Should not happen if called correctly

        root_path = Path(self.config.directory)
        logger.info(f"Starting scan task for: {root_path}")
        self.scan_started.emit()
        self.file_tree.clear_tree() # Clear tree before scan
        self.file_tree.show_loading_indicator(True) # Show loading state

        # Get ignore patterns from global config
        from ...config.loader import get_config as get_global_config
        ignore_patterns = get_global_config().ignore_patterns

        # Create the *adapter* task
        scan_task = FileScannerTask(root_path, ignore_patterns)
        self.current_scan_task_runner = scan_task # Store reference

        # Connect signals for this specific task run
        # Use lambda to capture task instance for checking on arrival
        scan_task.signals.finished.connect(
            lambda nodes, task=scan_task: self._on_scan_task_finished(nodes, task)
        )
        scan_task.signals.error.connect(
            lambda msg, task=scan_task: self._on_scan_task_error(msg, task)
        )
        scan_task.signals.progress.connect(self.scan_progress.emit) # Pass progress through

        # Run the adapter task in the background
        run_in_background(scan_task)


    def cancel_scan(self):
        """Requests cancellation of the current scan task adapter."""
        if self.current_scan_task_runner:
            logger.info("Requesting scan cancellation via adapter.")
            self.current_scan_task_runner.cancel() # Call cancel on the adapter
            self.current_scan_task_runner = None # Clear reference immediately


    def get_selected_nodes(self) -> List[FileNode]:
        """Returns a list of the currently selected FileNode objects."""
        return self.file_tree.get_selected_nodes()

    def get_selected_file_paths(self) -> Set[Path]:
        """Returns a set of paths for all selected *files* (recursive for dirs)."""
        return self.file_tree.get_selected_file_paths() # Delegate to tree widget


    def clear_selection(self):
        """Clears the selection in the file tree."""
        self.file_tree.uncheck_all_items() # Use the specific method
        # self.file_tree.clearSelection() # This clears visual selection, not checks
        # No need to emit selection_changed here, uncheck_all_items should trigger it via itemChanged


    # --- Slots ---

    @Slot()
    def select_directory(self):
        """Opens the folder selection dialog."""
        current_dir = self.config.directory or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", current_dir)
        if folder:
            self.set_directory(Path(folder))

    @Slot()
    def _apply_filter_to_tree(self):
        """Applies the text filter to the file tree (called by debounce timer)."""
        filter_text = self.filter_edit.text()
        logger.debug(f"Applying debounced filter: '{filter_text}'")
        self.file_tree.filter_tree(filter_text)

    @Slot(list, QObject) # Receives list[FileNode], Task instance
    def _on_scan_task_finished(self, root_nodes: List[FileNode], task: FileScannerTask):
        """Handles the successful completion of the scan task adapter."""
        # Ignore signals from outdated tasks
        if task != self.current_scan_task_runner:
             logger.warning("Received 'finished' signal from an outdated scan task. Ignoring.")
             return

        logger.info("Scan task finished successfully.")
        self.file_tree.show_loading_indicator(False)
        self.current_scan_task_runner = None # Clear task reference
        if root_nodes:
            self.file_tree.populate_tree(root_nodes[0]) # Populate with the first root
        else:
             logger.warning("Scan finished but returned no root nodes.")
             self.file_tree.clear_tree() # Ensure tree is empty
             # Show message in tree?
        self.scan_finished.emit(root_nodes) # Forward the result

    @Slot(str, QObject) # Receives error_message, Task instance
    def _on_scan_task_error(self, error_message: str, task: FileScannerTask):
        """Handles errors from the scan task adapter."""
        # Ignore signals from outdated tasks
        if task != self.current_scan_task_runner:
             logger.warning("Received 'error' signal from an outdated scan task. Ignoring.")
             return

        logger.error(f"Scan task failed: {error_message}")
        self.file_tree.show_loading_indicator(False)
        self.current_scan_task_runner = None # Clear task reference
        self.file_tree.clear_tree() # Clear tree on error
        # Show error message in tree? Or just rely on status bar/dialog?
        self.scan_error.emit(error_message) # Forward the error