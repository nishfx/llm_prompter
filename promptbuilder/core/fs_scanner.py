# promptbuilder/core/fs_scanner.py
import os
import fnmatch
import threading
from pathlib import Path
from typing import List, Optional, Callable, Tuple
import time
from loguru import logger

from .models import FileNode

# --- Core Logic (Pure Python) ---

class _FileScannerCore:
    """Pure Python implementation of file system scanning."""

    def __init__(self,
                 root_path: Path, # Store root path for relative calculations
                 ignore_patterns: List[str],
                 progress_callback: Optional[Callable[[str], None]] = None,
                 error_callback: Optional[Callable[[str], None]] = None):
        self.root_path = root_path.resolve() # Ensure root is absolute and resolved
        self.ignore_patterns = ignore_patterns
        self.progress_callback = progress_callback
        self.error_callback = error_callback
        self._is_cancelled = threading.Event() # Use threading.Event for cancellation flag
        logger.debug(f"Scanner core initialized for {self.root_path} with ignores: {self.ignore_patterns}")

    def _emit_progress(self, message: str):
        if self.progress_callback:
            try: self.progress_callback(message)
            except Exception as e: logger.error(f"Error in progress callback: {e}")

    def _emit_error(self, message: str):
        if self.error_callback:
            try: self.error_callback(message)
            except Exception as e: logger.error(f"Error in error callback: {e}")

    def is_ignored(self, entry_path: Path, is_dir: bool) -> bool:
        """
        Check if a path should be ignored based on symlinks or ignore patterns.
        Patterns are matched against the name and the path relative to the root.
        NOTE: Symlink check happens *before* pattern matching.
        """
        # Check symlink first (important for security) - This check was already here and correct
        try:
             if entry_path.is_symlink(): # lstat is implicitly used by is_symlink
                 logger.trace(f"Ignoring symlink: {entry_path}")
                 return True
        except OSError as e:
             logger.warning(f"Could not check if path is symlink {entry_path}: {e}. Assuming ignored for safety.")
             self._emit_error(f"Permission error checking symlink: {entry_path.name}")
             return True

        # Calculate relative path for pattern matching
        try:
            relative_path = entry_path.relative_to(self.root_path)
            relative_path_str = relative_path.as_posix() # Use POSIX slashes for consistency
        except ValueError:
            logger.warning(f"Could not get relative path for {entry_path} against root {self.root_path}. Checking name only.")
            relative_path_str = None

        name = entry_path.name

        # Check against ignore patterns
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                logger.trace(f"Ignoring '{name}' due to basename pattern '{pattern}'")
                return True
            if relative_path_str and fnmatch.fnmatch(relative_path_str, pattern):
                 logger.trace(f"Ignoring '{relative_path_str}' due to relative path pattern '{pattern}'")
                 return True
            # TODO: Add support for directory-specific patterns (e.g., "build/")

        return False

    def scan_directory_sync(self) -> List[FileNode]: # Removed root_path arg, use self.root_path
        """
        Scans the configured root directory structure synchronously and returns the tree.
        Raises exceptions on major errors (e.g., root not found).
        """
        logger.info(f"[Sync Scan] Starting for: {self.root_path}")
        self._is_cancelled.clear()
        if not self.root_path.is_dir(): raise ValueError(f"Provided path is not a valid directory: {self.root_path}")
        root_node = self._scan_recursive(self.root_path)
        results = [root_node] if root_node else []
        if self._is_cancelled.is_set(): logger.info(f"[Sync Scan] Cancelled during execution for: {self.root_path}")
        else: logger.info(f"[Sync Scan] Finished successfully for: {self.root_path}")
        return results

    def _scan_recursive(self, dir_path: Path) -> Optional[FileNode]:
        """Recursive helper for scanning."""
        if self._is_cancelled.is_set(): return None
        resolved_dir_path = dir_path.resolve()
        is_root = (resolved_dir_path == self.root_path)
        # Check ignore status *before* stating the directory (avoids stating ignored dirs)
        # Note: is_ignored already checks for symlinks.
        if not is_root and self.is_ignored(resolved_dir_path, is_dir=True):
             return None

        try:
            dir_stat = resolved_dir_path.stat()
            dir_node = FileNode(path=resolved_dir_path, name=resolved_dir_path.name, is_dir=True, mod_time=dir_stat.st_mtime)
            if not is_root: self._emit_progress(f"Scanning: {resolved_dir_path.name}")

            child_nodes: List[FileNode] = []
            try: entries = list(os.scandir(resolved_dir_path))
            except OSError as scandir_err:
                 logger.warning(f"Could not scan directory contents {resolved_dir_path}: {scandir_err}")
                 self._emit_error(f"Access Error scanning: {resolved_dir_path.name}")
                 return dir_node # Return dir node even if contents unreadable

            for entry in entries:
                if self._is_cancelled.is_set(): return None
                entry_path_abs = Path(entry.path).resolve() # Resolve early for checks

                # Fixes Polish P-1: Check symlink *before* is_dir/is_file which might follow it
                try:
                    if entry.is_symlink(): # Use the DirEntry method which uses lstat
                        logger.trace(f"Ignoring symlink entry: {entry.name}")
                        continue
                except OSError as e:
                     logger.warning(f"Could not check if entry is symlink {entry.path}: {e}. Skipping.")
                     self._emit_error(f"Permission error checking symlink entry: {entry.name}")
                     continue

                # Now check if ignored based on patterns (using resolved path)
                entry_is_dir_flag = entry.is_dir() # Check type *after* symlink check
                if self.is_ignored(entry_path_abs, entry_is_dir_flag):
                    continue

                # Process directories and files
                if entry_is_dir_flag:
                    sub_dir_node = self._scan_recursive(entry_path_abs) # Pass resolved path
                    if sub_dir_node: sub_dir_node.parent = dir_node; child_nodes.append(sub_dir_node)
                elif entry.is_file(): # Check is_file *after* symlink and ignore checks
                    try:
                        file_stat = entry_path_abs.stat() # Use resolved path
                        file_node = FileNode(path=entry_path_abs, name=entry.name, is_dir=False, size=file_stat.st_size, mod_time=file_stat.st_mtime, parent=dir_node)
                        child_nodes.append(file_node)
                    except OSError as stat_err:
                        logger.warning(f"Could not stat file {entry_path_abs}: {stat_err}")
                        self._emit_error(f"Access Error stating: {entry.name}")
                # else: ignore other types

            dir_node.children = sorted(child_nodes, key=lambda n: (not n.is_dir, n.name.lower()))
            return dir_node

        except OSError as e:
            logger.warning(f"Could not stat directory {resolved_dir_path}: {e}")
            self._emit_error(f"Access Error stating dir: {resolved_dir_path.name}")
            return None

    def cancel(self):
        """Signals the scanner to stop processing."""
        logger.info("Cancellation requested for scanner core.")
        self._is_cancelled.set()

# --- Qt Adapter Task --- (No changes needed in adapter itself)

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

class FileScannerSignals(QObject):
    finished = Signal(list); error = Signal(str); progress = Signal(str)

class FileScannerTask(QRunnable):
    """QRunnable adapter for running _FileScannerCore in a background thread."""
    def __init__(self, root_path: Path, ignore_patterns: List[str]):
        super().__init__(); self.root_path = root_path; self.ignore_patterns = ignore_patterns
        self.signals = FileScannerSignals(); self.scanner_core: Optional[_FileScannerCore] = None
        self.setAutoDelete(True)
    @Slot()
    def run(self) -> None:
        try:
            self.scanner_core = _FileScannerCore(root_path=self.root_path, ignore_patterns=self.ignore_patterns,
                                                 progress_callback=self.signals.progress.emit, error_callback=self.signals.error.emit)
            results = self.scanner_core.scan_directory_sync()
            if self.scanner_core._is_cancelled.is_set(): self.signals.error.emit("Scan cancelled")
            else: self.signals.finished.emit(results)
        except ValueError as ve: logger.error(f"Scan Error for {self.root_path}: {ve}"); self.signals.error.emit(str(ve))
        except Exception as e: logger.exception(f"Unexpected error during file scan task for {self.root_path}: {e}"); self.signals.error.emit(f"Unexpected Scan Error: {e}")
        finally: self.scanner_core = None
    def cancel(self):
        logger.info(f"Cancellation signal received for scan task: {self.root_path}")
        if self.scanner_core: self.scanner_core.cancel()