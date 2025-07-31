import os
import re
from datetime import datetime
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QDialogButtonBox, QPushButton, 
    QTextEdit, QHBoxLayout, QMessageBox, QSplitter, QStyle, QMenu, QAction
)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QTextDocument, QIcon, QFont
from difflib import Differ
from .settings_manager import WWSettingsManager
from .autosave_manager import build_scene_identifier
from .theme_manager import ThemeManager

class BackupDialog(QDialog):
    """Dialog to display and manage backup files for a specific project item."""
    
    def __init__(self, parent, project_name, item_name, item_hierarchy, is_scene=True):
        super().__init__(parent)
        self.project_name = project_name
        self.item_name = item_name
        self.hierarchy = item_hierarchy
        self.is_scene = is_scene
        self.selected_file = None
        self.backup_files = []
        self.diff_font_size = 12  # Initial font size for diff viewer
        self.init_ui()
        self.populate_backup_files()
        self.read_settings()

    def init_ui(self):
        """Initialize the dialog's user interface."""
        self.setWindowTitle(_("Backup Versions"))
        self.setModal(True)
        self.resize(800, 600)

        # Main layout
        layout = QVBoxLayout(self)

        # Splitter for list and diff viewer
        self.splitter = QSplitter(Qt.Horizontal)

        # Left panel: Backup file list
        self.list_widget = QListWidget()
        self.list_widget.setMaximumWidth(200)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)  # Allow multiple selection
        self.list_widget.currentItemChanged.connect(self.update_diff_view)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.splitter.addWidget(self.list_widget)

        # Right panel: Diff viewer
        self.diff_viewer = QTextEdit()
        self.diff_viewer.setReadOnly(True)
        self.diff_viewer.setHtml("<p>Select a backup file to view differences.</p>")
        self.update_diff_font()  # Set initial font size
        self.splitter.addWidget(self.diff_viewer)

        self.splitter.setSizes([200, 600])
        layout.addWidget(self.splitter)

        # Buttons
        button_layout = QHBoxLayout()
        self.delete_button = QPushButton(QIcon("assets/icons/trash.svg"), _("Delete"))
        self.delete_button.clicked.connect(self.delete_selected_backup)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        # Lock/Unlock button
        self.lock_button = QPushButton()
        self.lock_button.setCheckable(True)
        self.lock_button.clicked.connect(self.toggle_lock)
        self.update_lock_button_state()  # Initialize button state
        button_layout.addWidget(self.lock_button)

        # Zoom buttons
        self.zoom_in_button = QPushButton()
        self.zoom_in_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-in.svg"))
        self.zoom_in_button.setToolTip(_("Zoom in diff viewer (CMD++)"))
        self.zoom_in_button.clicked.connect(self.zoom_in)
        button_layout.addWidget(self.zoom_in_button)

        self.zoom_out_button = QPushButton()
        self.zoom_out_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/zoom-out.svg"))
        self.zoom_out_button.setToolTip(_("Zoom out diff viewer (CMD+-)"))
        self.zoom_out_button.clicked.connect(self.zoom_out)
        button_layout.addWidget(self.zoom_out_button)

        self.reset_zoom_button = QPushButton()
        self.reset_zoom_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reset_zoom_button.setToolTip(_("Reset diff viewer zoom"))
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        button_layout.addWidget(self.reset_zoom_button)

        button_layout.addStretch()
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_layout.addWidget(self.button_box)
        
        layout.addLayout(button_layout)

        # Connect buttons
        self.button_box.accepted.connect(self.on_accept)
        self.button_box.rejected.connect(self.on_close)

    def keyPressEvent(self, event):
        """Handle CMD++ and CMD+- shortcuts for zooming."""
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
                self.zoom_in()
                event.accept()
                return
            elif event.key() == Qt.Key_Minus:
                self.zoom_out()
                event.accept()
                return
        super().keyPressEvent(event)

    def zoom_in(self):
        """Increase font size of diff viewer content."""
        self.diff_font_size = min(self.diff_font_size + 2, 24)  # Max font size 24
        self.update_diff_font()

    def zoom_out(self):
        """Decrease font size of diff viewer content."""
        self.diff_font_size = max(self.diff_font_size - 2, 8)  # Min font size 8
        self.update_diff_font()

    def reset_zoom(self):
        """Reset font size of diff viewer content to default."""
        self.diff_font_size = 12  # Default font size
        self.update_diff_font()

    def update_diff_font(self):
        """Update the font size of diff viewer content."""
        self.diff_viewer.setStyleSheet(f"""
            QTextEdit {{
                font-family: 'Arial';
                font-size: {self.diff_font_size}px;
            }}
        """)
        self.diff_viewer.viewport().update()

    def read_settings(self):
        """Read saved settings for geometry, splitter, and font size."""
        settings = QSettings("MyCompany", "WritingwayProject")
        self.restoreGeometry(settings.value("BackupDialog/geometry", self.saveGeometry()))
        self.splitter.restoreState(settings.value("BackupDialog/splitter", self.splitter.saveState()))
        saved_font_size = settings.value("BackupDialog/diff_font_size", 12, type=int)
        self.diff_font_size = max(8, min(24, saved_font_size))  # Ensure within valid range
        self.update_diff_font()

    def write_settings(self):
        """Save settings for geometry, splitter, and font size."""
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("BackupDialog/geometry", self.saveGeometry())
        settings.setValue("BackupDialog/splitter", self.splitter.saveState())
        settings.setValue("BackupDialog/diff_font_size", self.diff_font_size)

    def on_close(self):
        """Save settings and close the dialog."""
        self.write_settings()
        self.reject()

    def closeEvent(self, event):
        """Save settings when dialog is closed."""
        self.write_settings()
        super().closeEvent(event)

    def is_protected_backup(self, filepath: str) -> bool:
        """Check if a backup file is marked as protected."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                return "<!-- PROTECTED -->" in content.split("\n")[:2]
        except Exception:
            return False

    def populate_backup_files(self):
        """Populate the list widget with backup files sorted by creation time."""
        file_name = build_scene_identifier(self.project_name, self.hierarchy)
        # Regex for scene files: <project>-<act>-<chapter>-<scene>_<timestamp>.html
        scene_pattern = rf'^{file_name}_(\d{{14}})\.html$'
        # Regex for summary files: <project>-<act>-<chapter>-Summary_<timestamp>.html
        summary_pattern = rf'^{file_name}-Summary_(\d{{14}})\.html$'
        backup_dir = WWSettingsManager.get_project_relpath(self.project_name)
        
        self.backup_files = []
        rexpat = summary_pattern if not self.is_scene else scene_pattern
        
        if os.path.exists(backup_dir):
            for filename in os.listdir(backup_dir):
                creation_time = re.match(rexpat, filename)
                if creation_time:
                    self.backup_files.append((filename, creation_time.group(1)))
        
        # Sort by creation time, newest first
        self.backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # Populate list widget
        self.list_widget.clear()
        for filename, creation_time in self.backup_files:
            try:
                timestamp = datetime.strptime(creation_time, "%Y%m%d%H%M%S")
                formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                formatted_timestamp = creation_time
            item = self.list_widget.addItem(formatted_timestamp)
            item = self.list_widget.item(self.list_widget.count() - 1)
            item.setData(Qt.UserRole, filename)
            
            # Set icon based on protected status
            backup_path = WWSettingsManager.get_project_relpath(self.project_name, filename)
            if self.is_protected_backup(backup_path):
                item.setIcon(ThemeManager.get_tinted_icon("assets/icons/lock.svg"))
            else:
                item.setIcon(QIcon())  # No icon for unprotected
        
        # Select the top item if the list is not empty
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def get_current_content(self):
        """Get the current content of the scene or summary as plain text."""
        from project_window.project_window import ProjectWindow
        parent = self.parent()
        if not isinstance(parent, ProjectWindow):
            return ""
        
        if self.is_scene:
            # Convert scene editor's HTML content to plain text
            doc = QTextDocument()
            doc.setHtml(parent.scene_editor.editor.toHtml())
            return doc.toPlainText()
        else:
            # Convert summary content to plain text if it's HTML
            content = parent.model.load_summary(self.hierarchy)
            if content and isinstance(content, str):
                # Convert summary content to plain text if it's HTML
                if content.lstrip().startswith("<"):
                    doc = QTextDocument()
                    doc.setHtml(content)
                    return doc.toPlainText()
            return content if content else ""

    def update_diff_view(self, current, previous):
        """Update the diff viewer with inline word-level differences, preserving paragraph breaks."""
        self.delete_button.setEnabled(current is not None)
        self.update_lock_button_state()
        if not current:
            self.diff_viewer.setHtml("<p>Select a backup file to view differences.</p>")
            return
        
        backup_filename = current.data(Qt.UserRole)
        backup_dir = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name))
        backup_path = os.path.join(backup_dir, backup_filename)
        
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                backup_content = f.read()
                # Strip UUID and PROTECTED comments if present
                lines = backup_content.split("\n")
                while lines and (lines[0].startswith("<!-- UUID:") or lines[0] == "<!-- PROTECTED -->"):
                    lines.pop(0)
                backup_content = "\n".join(lines)
                
                # Convert backup content to plain text if it's HTML
                if backup_filename.endswith(".html"):
                    doc = QTextDocument()
                    doc.setHtml(backup_content)
                    backup_content = doc.toPlainText()
                
            current_content = self.get_current_content()
            
            # Split content into lines to preserve paragraphs
            backup_lines = backup_content.splitlines()
            current_lines = current_content.splitlines()
            
            # Perform line-level diff to identify changed lines
            differ = Differ()
            line_diff = list(differ.compare(backup_lines, current_lines))
            
            html_output = []
            for line in line_diff:
                code = line[0]
                line_content = line[2:]
                
                if not line_content.strip():  # Empty line
                    html_output.append("<br>")
                    continue
                
                # Split line into words and whitespace
                words = re.findall(r'\S+|\s+', line_content)
                if code == ' ':  # Unchanged line
                    html_output.append("".join(words) + "<br>")
                else:
                    # Perform word-level diff within the line
                    if code == '-':  # Deleted line
                        backup_words = words
                        current_words = []  # No corresponding current line
                    elif code == '+':  # Added line
                        backup_words = []  # No corresponding backup line
                        current_words = words
                    else:  # Changed line (shouldn't occur in line-level diff)
                        continue
                    
                    # Word-level diff
                    word_differ = Differ()
                    word_diff = list(word_differ.compare(backup_words, current_words))
                    
                    line_output = []
                    for word in word_diff:
                        w_code = word[0]
                        w_value = word[2:]
                        if w_code == '-':  # Deleted
                            line_output.append(f'<span style="color: red; text-decoration: line-through;">{w_value}</span>')
                        elif w_code == '+':  # Added
                            line_output.append(f'<span style="background-color: lightgreen;">{w_value}</span>')
                        elif w_code == ' ':  # Unchanged
                            line_output.append(w_value)
                    
                    html_output.append("".join(line_output) + "<br>")
            
            # Join lines and wrap in basic HTML
            diff_html = f"""
            <html>
            <body>
            {"".join(html_output)}
            </body>
            </html>
            """
            self.diff_viewer.setHtml(diff_html)
        except Exception as e:
            self.diff_viewer.setHtml(f"<p>Error generating diff: {str(e)}</p>")

    def update_lock_button_state(self):
        """Update the lock button's icon and tooltip based on the selected item's protected status."""
        current_item = self.list_widget.currentItem()
        is_protected = False
        if current_item:
            backup_filename = current_item.data(Qt.UserRole)
            backup_path = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name), backup_filename)
            is_protected = self.is_protected_backup(backup_path)
        
        self.lock_button.setChecked(is_protected)
        icon = ThemeManager.get_tinted_icon("assets/icons/lock.svg" if is_protected else "assets/icons/unlock.svg")
        self.lock_button.setIcon(icon)
        self.lock_button.setToolTip(_("Allow auto-delete") if is_protected else _("Prevent auto-delete"))
        self.lock_button.setEnabled(current_item is not None)

    def toggle_lock(self):
        """Toggle the protected status of the selected backup file."""
        current_item = self.list_widget.currentItem()
        if not current_item:
            return
        
        backup_filename = current_item.data(Qt.UserRole)
        backup_path = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name), backup_filename)
        
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            is_protected = "<!-- PROTECTED -->" in lines[:2]
            
            if is_protected:
                # Remove PROTECTED comment
                lines = [line for line in lines if line != "<!-- PROTECTED -->"]
            else:
                # Add PROTECTED comment after UUID
                if lines and lines[0].startswith("<!-- UUID:"):
                    lines.insert(1, "<!-- PROTECTED -->")
                else:
                    lines.insert(0, "<!-- PROTECTED -->")
            
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            
            self.update_lock_button_state()
            self.populate_backup_files()  # Refresh list to update icons
            QMessageBox.information(self, _("Backup Protection"), 
                                   _("Backup file '{}' has been {}.").format(
                                       backup_filename, _("unlocked") if is_protected else _("locked")))
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to modify backup protection: {}").format(str(e)))

    def show_context_menu(self, position):
        """Show a context menu for locking/unlocking/deleting multiple backups."""
        menu = QMenu()
        lock_action = QAction(_("Lock Selected"), self)
        unlock_action = QAction(_("Unlock Selected"), self)
        delete_action = QAction(_("Delete Selected"), self)
        
        lock_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/lock.svg"))
        unlock_action.setIcon(ThemeManager.get_tinted_icon("assets/icons/unlock.svg"))
        delete_action.setIcon(QIcon("assets/icons/trash.svg"))
        
        lock_action.triggered.connect(self.lock_selected_backups)
        unlock_action.triggered.connect(self.unlock_selected_backups)
        delete_action.triggered.connect(self.delete_selected_backup)
        
        menu.addAction(lock_action)
        menu.addAction(unlock_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        
        menu.exec_(self.list_widget.mapToGlobal(position))

    def lock_selected_backups(self):
        """Lock all selected backup files."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        
        backup_dir = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name))
        modified_files = []
        
        for item in selected_items:
            backup_filename = item.data(Qt.UserRole)
            backup_path = os.path.join(backup_dir, backup_filename)
            if not self.is_protected_backup(backup_path):
                try:
                    with open(backup_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    lines = content.split("\n")
                    if lines and lines[0].startswith("<!-- UUID:"):
                        lines.insert(1, "<!-- PROTECTED -->")
                    else:
                        lines.insert(0, "<!-- PROTECTED -->")
                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                    modified_files.append(backup_filename)
                except Exception as e:
                    QMessageBox.warning(self, _("Error"), _("Failed to lock '{}': {}").format(backup_filename, str(e)))
        
        self.populate_backup_files()  # Refresh list
        if modified_files:
            QMessageBox.information(self, _("Backup Protection"), 
                                   _("Locked {} backup(s).").format(len(modified_files)))

    def unlock_selected_backups(self):
        """Unlock all selected backup files."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        
        backup_dir = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name))
        modified_files = []
        
        for item in selected_items:
            backup_filename = item.data(Qt.UserRole)
            backup_path = os.path.join(backup_dir, backup_filename)
            if self.is_protected_backup(backup_path):
                try:
                    with open(backup_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    lines = content.split("\n")
                    lines = [line for line in lines if line != "<!-- PROTECTED -->"]
                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                    modified_files.append(backup_filename)
                except Exception as e:
                    QMessageBox.warning(self, _("Error"), _("Failed to unlock '{}': {}").format(backup_filename, str(e)))
        
        self.populate_backup_files()  # Refresh list
        if modified_files:
            QMessageBox.information(self, _("Backup Protection"), 
                                   _("Unlocked {} backup(s).").format(len(modified_files)))

    def delete_selected_backup(self):
        """Delete the selected backup files after confirmation."""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        
        backup_dir = os.path.join(os.getcwd(), "Projects", WWSettingsManager.sanitize(self.project_name))
        protected_files = []
        unprotected_files = []
        
        for item in selected_items:
            backup_filename = item.data(Qt.UserRole)
            backup_path = os.path.join(backup_dir, backup_filename)
            if self.is_protected_backup(backup_path):
                protected_files.append(backup_filename)
            else:
                unprotected_files.append(backup_filename)
        
        if protected_files:
            message = _("The following backup files are protected:\n{}\nAre you sure you want to delete them? This action cannot be undone.").format("\n".join(protected_files))
            if unprotected_files:
                message += _("\n\nThe following unprotected backup files will also be deleted:\n{}").format("\n".join(unprotected_files))
            response = QMessageBox.question(
                self, _("Confirm Delete Protected Backup"), message, QMessageBox.Yes | QMessageBox.No
            )
        elif unprotected_files:
            message = _("Are you sure you want to delete the following backup files?\n{}\nThis action cannot be undone.").format("\n".join(unprotected_files))
            response = QMessageBox.question(
                self, _("Confirm Delete"), message, QMessageBox.Yes | QMessageBox.No
            )
        else:
            return
        
        if response == QMessageBox.Yes:
            deleted_files = []
            for item in selected_items:
                backup_filename = item.data(Qt.UserRole)
                backup_path = os.path.join(backup_dir, backup_filename)
                try:
                    os.remove(backup_path)
                    deleted_files.append(backup_filename)
                except Exception as e:
                    QMessageBox.warning(self, _("Delete Error"), _("Failed to delete '{}': {}").format(backup_filename, str(e)))
            
            self.populate_backup_files()
            new_current_item = self.list_widget.currentItem()
            self.update_diff_view(new_current_item, None)
            if deleted_files:
                QMessageBox.information(self, _("Backup Deleted"), 
                                       _("Deleted {} backup(s).").format(len(deleted_files)))

    def on_accept(self):
        """Handle OK button click."""
        if self.list_widget.currentItem() is not None:
            self.selected_file = self.list_widget.currentItem().data(Qt.UserRole)
            self.write_settings()
            self.accept()

def show_backup_dialog(parent, project_name, item_name, hierarchy, is_scene=True):
    """
    Opens a dialog that lists backup files for the specified project item.
    
    Args:
        parent: The parent widget
        project_name: Name of the project
        item_name: Name of the scene or act/chapter
        hierarchy: List representing the hierarchy path
        is_scene: Boolean indicating if the item is a scene (True) or summary (False)
    
    Returns:
        The full path of the selected backup file, or None if canceled
    """
    dialog = BackupDialog(parent, project_name, item_name, hierarchy, is_scene)
    result = dialog.exec_()
    if result == QDialog.Accepted and dialog.selected_file:
        return os.path.join(
            os.getcwd(),
            "Projects",
            WWSettingsManager.sanitize(project_name),
            dialog.selected_file
        )
    return None