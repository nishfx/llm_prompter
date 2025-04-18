# promptbuilder/ui/widgets/file_tree.py

import html
import os
import platform
import subprocess
import time # For formatting modification time
from pathlib import Path
from typing import List, Optional, Set, Dict # Added Dict

from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView,  # ← add this
    QAbstractItemView, QMenu, QTreeWidgetItemIterator, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QPoint
from PySide6.QtGui import QFontMetrics, QPalette, QFontDatabase, QFont, QIcon # Added FontDatabase, Font, QIcon
from loguru import logger

from ...core.models import FileNode

class FileTreeWidget(QTreeWidget):
    """Displays the file/folder structure with checkboxes."""

    # Signal emitted when the checked state of any item changes
    item_selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(4) # Name, Size, Modified, FullPath (Hidden)
        self.setHeaderLabels(["Name", "Size", "Modified", "Path"])
        self.setColumnHidden(3, True) # Hide full path column
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection) # Disable standard selection
        self.setAlternatingRowColors(True)
        # Fixes Polish P-4: Disable animation for potentially large trees
        self.setAnimated(False)

        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.setFont(fixed_font); self.header().setFont(fixed_font)

        self._item_map: Dict[QTreeWidgetItem, FileNode] = {}
        self._node_map: Dict[Path, QTreeWidgetItem] = {}

        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.resizeColumnToContents(1); self.resizeColumnToContents(2)
        self.setColumnWidth(0, 300); self.setMinimumWidth(400)

        self.itemChanged.connect(self._on_item_changed)
        self.itemExpanded.connect(lambda: self.resizeColumnToContents(0))
        self.itemCollapsed.connect(lambda: self.resizeColumnToContents(0))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # --- Helper methods (_format_size, _create_tree_item) --- (No changes needed)
    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024: return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
        else: return f"{size_bytes / (1024 * 1024):.1f} MB"
    def _create_tree_item(self, node: FileNode, parent_item: Optional[QTreeWidgetItem] = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent_item) if parent_item else QTreeWidgetItem(self)
        item.setText(0, node.name); item.setToolTip(0, str(node.path)); item.setText(3, str(node.path))
        if node.is_dir: item.setText(1, ""); item.setText(2, "")
        else:
            item.setText(1, self._format_size(node.size))
            try: mod_time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(node.mod_time))
            except ValueError: mod_time_str = "Invalid Date"
            item.setText(2, mod_time_str)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        self._item_map[item] = node; self._node_map[node.path] = item
        return item

    # --- Tree Population and Management --- (No changes needed)
    def populate_tree(self, root_node: FileNode):
        self.clear_tree(); logger.debug(f"Populating tree with root: {root_node.name}")
        self.blockSignals(True)
        try:
            stack = [(root_node, None)];
            while stack:
                node, parent_qt_item = stack.pop()
                current_qt_item = self._create_tree_item(node, parent_qt_item)
                for child_node in reversed(node.children):
                    stack.append((child_node, current_qt_item))
            for i in range(self.topLevelItemCount()): self.topLevelItem(i).setExpanded(True)
            self.resizeColumnToContents(0); self.resizeColumnToContents(1); self.resizeColumnToContents(2)
        finally: self.blockSignals(False)
        logger.debug("Tree population complete.")
    def clear_tree(self):
        logger.debug("Clearing file tree."); self.blockSignals(True)
        self.clear(); self._item_map.clear(); self._node_map.clear()
        self.blockSignals(False)

    def show_loading_indicator(self, show: bool):
        self.blockSignals(True)
        try:
            # ----- NEW: handle empty tree safely -----
            if self.topLevelItemCount() == 0:
                current_item = None
            else:
                current_item = self.topLevelItem(0)

            # remove existing “Scanning …” placeholder
            if current_item and "Scanning" in current_item.text(0):
                self.takeTopLevelItem(0)
            # -----------------------------------------

            if show:
                # insert fresh placeholder
                self.clear_tree()
                loading_item = QTreeWidgetItem(self)
                loading_item.setText(0, "Scanning directory…")
                loading_item.setFlags(loading_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                loading_item.setForeground(
                    0, self.palette().color(QPalette.ColorRole.PlaceholderText)
                )
        finally:
            self.blockSignals(False)

    # --- Checkbox Handling & Propagation --- (No changes needed)
    @Slot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column == 0:
            if not item or item not in self._item_map: return
            is_checked = item.checkState(0) == Qt.CheckState.Checked; node = self._item_map.get(item)
            if node:
                logger.trace(f"Item '{node.name}' check state changed to: {is_checked}")
                self.blockSignals(True)
                try:
                    if node.is_dir: self._set_children_check_state(item, item.checkState(0))
                    self._update_parent_check_state(item)
                finally: self.blockSignals(False)
                self.item_selection_changed.emit()
            else: logger.warning("Item changed but no corresponding FileNode found.")
    def _set_children_check_state(self, item: QTreeWidgetItem, state: Qt.CheckState):
        for i in range(item.childCount()): child = item.child(i);
        if child.checkState(0) != state: child.setCheckState(0, state)
    def _update_parent_check_state(self, item: QTreeWidgetItem):
        parent = item.parent()
        if not parent:
            return
        child_states = set()
        has_children = False
        for i in range(parent.childCount()):
            has_children = True
        child_states.add(parent.child(i).checkState(0))
        if not has_children:
            return
        new_parent_state = Qt.CheckState.Unchecked
        if len(child_states) == 1:
            state = list(child_states)[0]
        if state == Qt.CheckState.Checked:
            new_parent_state = Qt.CheckState.Checked
        elif state == Qt.CheckState.Unchecked:
            new_parent_state = Qt.CheckState.Unchecked
        elif state == Qt.CheckState.PartiallyChecked:
            new_parent_state = Qt.CheckState.PartiallyChecked
        else:
            new_parent_state = Qt.CheckState.PartiallyChecked
        if parent.checkState(0) != new_parent_state:
            parent.setCheckState(0, new_parent_state)

    # --- Selection Retrieval --- (No changes needed)
    def get_selected_nodes(self) -> List[FileNode]:
        selected_nodes: List[FileNode] = []; iterator = QTreeWidgetItemIterator(self)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked):
                node = self._item_map.get(item);
                if node: selected_nodes.append(node)
            iterator += 1
        logger.debug(f"Found {len(selected_nodes)} selected (checked or partial) nodes.")
        return selected_nodes
    def get_selected_file_paths(self) -> Set[Path]:
        selected_files: Set[Path] = set(); iterator = QTreeWidgetItemIterator(self, QTreeWidgetItemIterator.IteratorFlag.All)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                node = self._item_map.get(item);
                if node and not node.is_dir: selected_files.add(node.path)
            iterator += 1
        logger.debug(f"Collected {len(selected_files)} selected file paths.")
        return selected_files
    def uncheck_all_items(self):
        logger.debug("Unchecking all items in the tree."); changed = False; self.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(self)
            while iterator.value():
                item = iterator.value();
                if item.checkState(0) != Qt.CheckState.Unchecked: item.setCheckState(0, Qt.CheckState.Unchecked); changed = True
                iterator += 1
        finally:
            self.blockSignals(False)
            if changed:
                logger.debug("Items were unchecked, emitting selection change.")
                self.item_selection_changed.emit()

    # --- Filtering & Context Menu --- (No changes needed)
    def filter_tree(self, text: str):
        filter_text = text.strip().lower(); logger.debug(f"Filtering tree view by: '{filter_text}'")
        self.blockSignals(True)
        try:
            iterator = QTreeWidgetItemIterator(self, QTreeWidgetItemIterator.IteratorFlag.All)
            while iterator.value():
                item = iterator.value(); node = self._item_map.get(item); item_text = item.text(0).lower() if item else ""
                should_hide = bool(filter_text) and (filter_text not in item_text)
                # TODO: Implement proper recursive filtering that keeps parents visible if children match.
                item.setHidden(should_hide)
                iterator += 1
        finally: self.blockSignals(False)
    @Slot(QPoint)
    def _show_context_menu(self, pos: QPoint):
        item = self.itemAt(pos);
        if not item: return
        node = self._item_map.get(item);
        if not node: return
        menu = QMenu(self)
        if node.is_dir: action_expand = menu.addAction("Expand All"); action_collapse = menu.addAction("Collapse All"); action_expand.triggered.connect(lambda: self.expandRecursively(item)); action_collapse.triggered.connect(lambda: self.collapseRecursively(item)); menu.addSeparator()
        action_check = menu.addAction("Check"); action_uncheck = menu.addAction("Uncheck"); action_check.triggered.connect(lambda: self._set_item_checked_state(item, Qt.CheckState.Checked)); action_uncheck.triggered.connect(lambda: self._set_item_checked_state(item, Qt.CheckState.Unchecked)); menu.addSeparator()
        action_open_externally = menu.addAction("Open Location"); action_open_externally.triggered.connect(lambda: self._open_item_location(node))
        menu.exec(self.mapToGlobal(pos))
    def expandRecursively(self, item: QTreeWidgetItem):
        if not item:
            return
        item.setExpanded(True)
        for i in range(item.childCount()):
            self.expandRecursively(item.child(i))
    def collapseRecursively(self, item: QTreeWidgetItem):
        if not item: return
        for i in range(item.childCount()): self.collapseRecursively(item.child(i))
        item.setExpanded(False)
    def _set_item_checked_state(self, item: QTreeWidgetItem, state: Qt.CheckState):
        if item and item.checkState(0) != state: item.setCheckState(0, state)
    def _open_item_location(self, node: FileNode):
        path_to_open = node.path
        try:
            if platform.system() == "Windows":
                if path_to_open.is_file(): subprocess.run(['explorer', '/select,', str(path_to_open)], check=True, shell=False) # Avoid shell=True if possible
                elif path_to_open.is_dir(): subprocess.run(['explorer', str(path_to_open)], check=True, shell=False)
                else: logger.warning(f"Cannot open location for non-file/dir: {path_to_open}"); return
                logger.info(f"Opened location for: {path_to_open}")
            else: logger.warning(f"Unsupported OS for opening location: {platform.system()}"); QMessageBox.information(self, "Unsupported", "Opening location is only supported on Windows.")
        except FileNotFoundError: logger.error(f"'explorer.exe' not found? Could not open location {path_to_open}"); QMessageBox.warning(self, "Open Error", f"Could not run explorer.exe to open location.")
        except Exception as e: logger.error(f"Failed to open location {path_to_open}: {e}"); QMessageBox.warning(self, "Open Error", f"Could not open location:\n{e}")