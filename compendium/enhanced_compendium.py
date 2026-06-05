from __future__ import annotations

import contextlib
import logging
import re
import uuid
from enum import StrEnum
from gettext import gettext as _
from typing import TYPE_CHECKING

from PyQt5.QtCore import QPoint, QSettings, Qt, QTimer
from PyQt5.QtGui import QBrush, QCloseEvent, QColor, QCursor, QFont, QPixmap
from PyQt5.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from compendium.compendium_manager import CompendiumEventBus, CompendiumManager
from compendium.compendium_types import CompendiumData, CompendiumEntry, CompendiumRelationship, CompendiumTag
from settings.theme_manager import ThemeManager

if TYPE_CHECKING:
    from workbench import WorkbenchWindow

logger = logging.getLogger(__name__)

# Constants for tree item types used in Qt.ItemDataRole.UserRole for the compendium tree
class CompendiumEntryType(StrEnum):
    ENTRY = "entry"
    CATEGORY = "category"

# Constants for compendium entry field names used in the CompendiumEntry TypedDict and as members of the dirty_fields set.
class CompendiumField(StrEnum):
    OVERVIEW = "overview"
    DETAILS = "details"
    TAGS = "tags"
    IMAGES = "images"
    RELATIONSHIPS = "relationships"

class EnhancedCompendiumWindow(QMainWindow):
    """
    Enhanced Compendium Window - A comprehensive interface for managing compendium data
    with categories, entries, tags, relationships, details, and images.

    """

    def __init__(self, parent: WorkbenchWindow | None) -> None:
        """
        Initialize the Enhanced Compendium Window.

        Args:
            project_name (str): Name of the project
            parent: Parent widget
        """
        logger.debug("Initializing Enhanced Compendium Window. parent=%s", type(parent).__name__ if parent else "None")
        super().__init__(parent)
        from workbench import WorkbenchWindow  # avoid circular import at the top level
        if not isinstance(parent, WorkbenchWindow):
            raise TypeError("EnhancedCompendiumWindow must be initialized with a WorkbenchWindow parent")
        self.parent_window: WorkbenchWindow = parent
        # Per-field dirty tracking.  "tags" lives in the right panel (no tab), so it
        # contributes to the overall dirty state but has no tab indicator.
        self.dirty_fields: set[CompendiumField] = set()
        # Insertion order defines tab order (must stay in sync with addTab() calls below).
        self._field_tab_names: dict[CompendiumField, str] = {
            CompendiumField.OVERVIEW: _("Overview"),
            CompendiumField.DETAILS: _("Details"),
            CompendiumField.RELATIONSHIPS: _("Relationships"),
            CompendiumField.IMAGES: _("Images"),
        }
        # Guard used to avoid nested Save/Discard prompts caused by tree selection
        # changes during programmatic save/refresh flows.
        # Ideally, this is not needed, but it is the best way I've found to prevent
        # multiple Save/Discard prompts for the same click
        # TODO: Debug why this is needed
        self._suppress_unsaved_prompt = False
        # When a selection change is cancelled by the unsaved-changes guard we
        # set this flag to suppress the context menus from firing on the now-reverted selection change
        # TODO: This is a hack
        self._last_selection_cancelled = False

        # Pending image paths for the currently loaded entry. This mirrors the UI
        # state and is written to compendium_data only on explicit Save.
        self._current_images: list[str] = []
        self._rename_originals: dict[str, str] = {}
        self.project_name = "default"  # project_name is set when we become visible

        # Shared event bus: notifies all listeners (this window, project panel, POV selector, …) whenever
        # the compendium file is written.
        self.event_bus = CompendiumEventBus.get_instance()
        self.manager = CompendiumManager(self.project_name, event_bus=self.event_bus)
        self.event_bus.add_updated_listener(self.on_compendium_updated)
        self.compendium_data: CompendiumData = self.manager.make_empty_compendium()

        # The currently selected entry/category in the treeview. None if no entry or category is selected.
        self.current_entry_item: QTreeWidgetItem | None = None  # selected tree item (entry or category)

        # uuid of the selected entry or category that is currently shown in the editor
        self.current_entry_uuid: str | None = None

        # 1) Create the QToolBar at the top
        self.toolbar: QToolBar
        self.project_combo: QComboBox  # Project selection combo in the toolbar
        self._setup_toolbar()
        self.addToolBar(self.toolbar)

        # 2) Set up the central widget (which holds the main layout and splitter)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # 3) Create the main splitter for the rest of the UI
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.main_splitter)

        # 4) Create the left (tree), center (content/tabs), and right (tags) panels
        self._setup_tree_view()
        self._setup_center_panel()
        self._setup_right_panel()

        # 5) Set splitter proportions
        self.main_splitter.setStretchFactor(0, 1)  # Tree view
        self.main_splitter.setStretchFactor(1, 2)  # Content panel
        self.main_splitter.setStretchFactor(2, 1)  # Right panel

        # 6) Set up the compendium file and populate the UI
        self.populate_compendium_tree()
        self.connect_signals()

        # 7) Window title and size
        self.setWindowTitle(_("Enhanced Compendium - {}").format(self.project_name))
        self.resize(900, 700)

        # 8) Populate the project combo and connect its signal
        self.populate_project_combo()

        # 9) Read saved settings
        self.read_settings()

    def read_settings(self) -> None:
        """Read window and splitter settings from QSettings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        geometry = settings.value("compendium_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        window_state = settings.value("compendium_windowState")
        if window_state:
            self.restoreState(window_state)
        splitter_state = settings.value("compendium_mainSplitterState")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)

    def write_settings(self) -> None:
        """Write window and splitter settings to QSettings."""
        settings = QSettings("MyCompany", "WritingwayProject")
        settings.setValue("compendium_geometry", self.saveGeometry())
        settings.setValue("compendium_windowState", self.saveState())
        settings.setValue("compendium_mainSplitterState", self.main_splitter.saveState())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event to save settings and any unsaved changes."""
        if not self.maybe_commit_unsaved_changes():
            event.ignore()
            return
        self.write_settings()
        event.accept()

    def maybe_commit_unsaved_changes(self) -> bool:
        """Prompt to save/discard unsaved edits; returns False when user cancels.

        Returns:
            bool: False if user canceled, True otherwise.
        """
        if not (self.is_dirty() and self.current_entry_item is not None):
            return True

        entry_name = self.current_entry_item.text(0)
        choice = QMessageBox.question(
            self,
            _("Unsaved Changes"),
            _("You have unsaved changes for '{}'. Save before continuing?").format(entry_name),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Save:
            self._suppress_unsaved_prompt = True
            try:
                return self.save_current_entry()
            finally:
                self._suppress_unsaved_prompt = False
        if choice == QMessageBox.Discard:
            self._suppress_unsaved_prompt = True
            try:
                self._discard_current_entry_changes(reload_entry=True)
                return True
            finally:
                self._suppress_unsaved_prompt = False
        return False

    def mark_dirty(self, field: CompendiumField) -> None:
        """Mark a specific field of the current entry as having unsaved changes."""
        if field in self.dirty_fields:
            return  # already dirty, no need to update

        logger.debug(f"Marking field '{field}' as dirty")
        self.dirty_fields.add(field)
        self._update_dirty_ui()

    def is_dirty(self) -> bool:
        """Return True if any field of the current entry has unsaved changes."""
        return bool(self.dirty_fields)

    def _reset_dirty(self) -> None:
        """Reset all dirty flags and refresh the UI indicators."""
        logger.debug("Resetting dirty flags")
        self.dirty_fields.clear()
        self._update_dirty_ui()

    def _update_dirty_ui(self) -> None:
        """Update tab labels and Save/Revert button states to reflect dirty state."""
        dirty = self.is_dirty()
        self.save_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)
        for tab_index, (field, base_name) in enumerate(self._field_tab_names.items()):
            if field in self.dirty_fields:
                # Show dirty indicator on the tab
                self.tabs.setTabText(tab_index, f"● {base_name}")
            else:
                self.tabs.setTabText(tab_index, base_name)
        # Update the Tags label with dirty indicator
        tags_base_name = _("Tags")
        if CompendiumField.TAGS in self.dirty_fields:
            self.tags_form.setTitle(f"● {tags_base_name}")
        else:
            self.tags_form.setTitle(tags_base_name)

    def _discard_current_entry_changes(self, reload_entry: bool = True) -> None:
        """Discard unsaved changes for the current entry and optionally reload saved values into the UI."""
        # TODO: Can we have one place for loading an entry?

        if self.current_entry_item is None:
            self._reset_dirty()
            return
        
        current_item = self.current_entry_item
        current_entry_name = current_item.text(0)
        current_entry_uuid = self.current_entry_uuid

        logger.info(f"Discarding changes for entry '{current_entry_name}' with uuid '{current_entry_uuid}'")
        self._reset_dirty()
        # Reload authoritative state from disk so discarded changes do not linger
        # in memory when the window is reopened.
        self.compendium_data = self.manager.load_data()
        self.populate_compendium_tree()  # TODO: do we need to reload the whole compendium?

        # After repopulation, anything could have changed
        current_item = self.current_entry_item
        current_entry_name = current_item.text(0)
        current_entry_uuid = self.current_entry_uuid

        if reload_entry:
            logger.info(f"Reloading entry '{current_entry_name}' with uuid '{current_entry_uuid}'")
            if current_item is not None and current_item.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.ENTRY:
                self.load_entry(current_item.text(0), current_item)
            else:
                self.clear_entry_ui()

    def revert_current_entry(self) -> None:
        """Revert the current entry to its last saved state (from compendium_data)."""
        if not self.is_dirty() or self.current_entry_item is None:
            return
        confirm = QMessageBox.question(
            self,
            _("Revert Changes"),
            _("Discard all unsaved changes to '{}'?").format(self.current_entry_item.text(0)),
            QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm == QMessageBox.Discard:
            self._discard_current_entry_changes(reload_entry=True)

    def _setup_toolbar(self) -> None:
        """Create the project selection toolbar at the top of the window."""
        self.toolbar = QToolBar(_("Project Toolbar"), self)
        self.toolbar.setObjectName("EnhToolBar_Main")

        label = QLabel(_("<b>Project:</b>"))
        self.toolbar.addWidget(label)

        self.project_combo = QComboBox()
        self.toolbar.addWidget(self.project_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar.addWidget(spacer)

    def populate_project_combo(self, project_name: str | None = None) -> None:
        """
        Populate the project pulldown.

        Args:
            project_name (str, optional): Specific project to select
        """
        selected_project = project_name or self.project_name

        self.project_combo.blockSignals(True)
        self.project_combo.clear()

        projects = self.parent_window.get_project_list()
        if projects:
            projects.sort()
            self.project_combo.addItems(projects)
            # Match by the exact project display name
            index = self.project_combo.findText(selected_project)
            if index < 0:
                # Default to the first project in the list if none matched.
                self.project_combo.setCurrentIndex(0)
                selected_project = self.project_combo.currentText()
            else:
                self.project_combo.setCurrentIndex(index)
                selected_project = self.project_combo.currentText()
        else:
            # TODO: How to handle empty project list better?
            # This creates a dummy "default" project, but bypasses the normal project creation flow.
            logger.warning("No projects found in the project list. Using 'default' project.")
            self.project_combo.addItem("default")
            self.project_combo.setCurrentIndex(0)
            selected_project = "default"

        self.project_combo.blockSignals(False)
        with contextlib.suppress(TypeError, RuntimeError):
            self.project_combo.currentTextChanged.disconnect(self.on_project_combo_changed)
        self.project_combo.currentTextChanged.connect(self.on_project_combo_changed)

        # Load the compendium for the selected project so entries (e.g. Characters/Alice)
        # are shown immediately after the window is created.
        self.change_project(selected_project, select_default_item=True)

    def on_project_combo_changed(self, new_project: str) -> None:
        """Update the project and reload the compendium when a different project is selected."""
        if new_project == self.project_name:
            return

        if not self.maybe_commit_unsaved_changes():
            self.project_combo.blockSignals(True)
            previous_index = self.project_combo.findText(self.project_name)
            if previous_index >= 0:
                self.project_combo.setCurrentIndex(previous_index)
            self.project_combo.blockSignals(False)
            return
        self.change_project(new_project)

    def select_first_entry(self) -> None:
        """Select the first entry if present, otherwise the first category."""
        first_category: QTreeWidgetItem | None = None
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item is None:
                continue
            if first_category is None and cat_item.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.CATEGORY:
                first_category = cat_item
            if cat_item.childCount() > 0:
                entry_item = cat_item.child(0)
                if entry_item is None:
                    continue
                if entry_item.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.ENTRY:
                    self.tree.setCurrentItem(entry_item)
                    return

        if first_category is not None:
            self.tree.setCurrentItem(first_category)
        else:
            self.clear_entry_ui()

    def change_project(self, new_project: str, select_default_item: bool = True) -> None:
        """Switch to a different project and reload its compendium data."""

        # TODO: Changing project should not be different from loading a project for the first time

        logger.debug(f"Changing project to {new_project}")
        if self.project_name == new_project:
            return
        self.project_name = new_project
        self.manager = CompendiumManager(self.project_name, event_bus=self.event_bus)
        self.compendium_data = self.manager.make_empty_compendium()
        self.selected_entry_item = None
        self.current_entry_item = None
        self.setWindowTitle(_("Enhanced Compendium - {}").format(self.project_name))
        self.populate_compendium_tree()
        if select_default_item and self.tree.currentItem() is None:
            self.select_first_entry()

    def _setup_tree_view(self) -> None:
        """Create the left panel: a tree view (with a search bar) for categories and entries."""
        self.tree_widget = QWidget()
        tree_layout = QVBoxLayout(self.tree_widget)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(_("Search entries and tags..."))
        tree_layout.addWidget(self.search_bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_("Compendium"))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree_layout.addWidget(self.tree)
        self.main_splitter.addWidget(self.tree_widget)

    def _setup_center_panel(self) -> None:
        """
        Create the center panel with a header and a tabbed view for content, details,
        relationships, and images.
        """
        self.center_widget = QWidget()
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setAlignment(Qt.AlignTop)

        # Header with entry name and save button
        self.header_widget = QWidget()
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header_layout = QHBoxLayout(self.header_widget)
        self.entry_name_label = QLabel(_("No entry selected"))
        self.entry_name_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(self.entry_name_label)
        header_layout.addStretch()
        self.revert_button = QPushButton(_("Revert"))
        self.revert_button.setToolTip(_("Discard all unsaved changes to this entry"))
        self.revert_button.setEnabled(False)
        self.revert_button.hide()
        header_layout.addWidget(self.revert_button)
        self.save_button = QPushButton(_("Save Changes"))
        self.save_button.setEnabled(False)
        self.save_button.hide()
        header_layout.addWidget(self.save_button)
        center_layout.addWidget(self.header_widget)

        self.tabs = QTabWidget()

        # Overview tab - "content" field;
        self.overview_tab = QWidget()
        overview_layout = QVBoxLayout(self.overview_tab)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(_("This is the text the AI can see if you select this entry to be included in the prompt inside the context panel"))
        overview_layout.addWidget(self.editor)
        self.tabs.addTab(self.overview_tab, _("Overview"))
        self.tabs.setTabToolTip(0, _("this is the text the AI can see if you select this entry to be included in the prompt inside the context panel"))

        # Details tab - enhanced-only; never sent to the AI.
        self.details_editor = QTextEdit()
        self.details_editor.setPlaceholderText(_("Enter details about your entry here... (details about your entry the AI can't see - this info is only for you)"))
        self.tabs.addTab(self.details_editor, _("Details"))
        self.tabs.setTabToolTip(1, _("details about your entry the AI can't see - this info is only for you"))

        # Relationships tab - enhanced-only.
        self.relationships_tab = QWidget()
        relationships_layout = QVBoxLayout(self.relationships_tab)
        self.relationships_form = QGroupBox(_("Relationships"))
        form_layout = QFormLayout()
        self.relationship_combo = QComboBox()
        self.relationship_type = QLineEdit()
        self.add_relationship_button = QPushButton(_("Add Relationship"))
        form_layout.addRow(_("Related Entry:"), self.relationship_combo)
        form_layout.addRow(_("Relationship Type:"), self.relationship_type)
        form_layout.addRow(self.add_relationship_button)
        self.relationships_form.setLayout(form_layout)
        self.relationships_list = QTreeWidget()
        self.relationships_list.setHeaderLabels([_("Name"), _("Type")])
        relationships_layout.addWidget(self.relationships_form)
        relationships_layout.addWidget(self.relationships_list)
        self.tabs.addTab(self.relationships_tab, _("Relationships"))

        # Images tab - enhanced-only.
        self.images_tab = QTabWidget()
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll_content = QWidget()
        self.image_layout = QHBoxLayout(self.image_scroll_content)
        self.image_scroll.setWidget(self.image_scroll_content)
        self.images_tab.addTab(self.image_scroll, _("Images"))
        self.add_image_button = QPushButton(_("Add Image"))
        images_layout = QVBoxLayout()
        images_layout.addWidget(self.images_tab)
        images_layout.addWidget(self.add_image_button)
        self.image_widget = QWidget()
        self.image_widget.setLayout(images_layout)
        self.tabs.addTab(self.image_widget, _("Images"))

        center_layout.addWidget(self.tabs)
        center_layout.addStretch()
        self.main_splitter.addWidget(self.center_widget)

    def _setup_right_panel(self) -> None:
        """Create the right panel for tags management."""
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        self.tags_form = QGroupBox(_("Tags"))
        form_layout = QFormLayout()
        self.tag_input = QLineEdit()
        # Color selector row: color preview box on the left, button on the right
        color_row = QHBoxLayout()
        self.tag_color_preview = QFrame()
        self.tag_color_preview.setFixedSize(24, 24)
        self.tag_color_preview.setFrameShape(QFrame.Box)
        self.tag_color_preview.setStyleSheet("background-color: #000000;")
        self._current_tag_color = "#000000"
        color_row.addWidget(self.tag_color_preview)
        color_row.addStretch()
        self.tag_color_button = QPushButton(_("Set..."))
        color_row.addWidget(self.tag_color_button)
        color_row_widget = QWidget()
        color_row_widget.setLayout(color_row)
        self.add_tag_button = QPushButton(_("Add Tag"))
        self.add_tag_button.setEnabled(False)
        form_layout.addRow(_("Tag:"), self.tag_input)
        form_layout.addRow(_("Color:"), color_row_widget)
        form_layout.addRow(self.add_tag_button)
        self.tags_form.setLayout(form_layout)
        self.tags_list = QListWidget()
        self.tags_list.setContextMenuPolicy(Qt.CustomContextMenu)
        right_layout.addWidget(self.tags_form)
        right_layout.addWidget(self.tags_list)
        self.main_splitter.addWidget(self.right_widget)

    def connect_signals(self) -> None:
        """Connect all necessary signals for interactive functionality."""
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.currentItemChanged.connect(self.on_item_changed)
        # Double-click should invoke the same rename dialog as the context menu
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.search_bar.textChanged.connect(self.filter_tree)
        self.save_button.clicked.connect(self.save_current_entry)
        self.revert_button.clicked.connect(self.revert_current_entry)
        self.add_tag_button.clicked.connect(self.add_tag)
        self.tag_color_button.clicked.connect(self.choose_tag_color)
        self.tag_input.textChanged.connect(self.update_add_tag_button_state)
        self.tags_list.customContextMenuRequested.connect(self.show_tags_context_menu)
        self.add_relationship_button.clicked.connect(self.add_relationship)
        self.relationships_list.customContextMenuRequested.connect(self.show_relationships_context_menu)
        self.add_image_button.clicked.connect(self.add_image)
        self.editor.textChanged.connect(lambda: self.mark_dirty(CompendiumField.OVERVIEW))
        self.details_editor.textChanged.connect(lambda: self.mark_dirty(CompendiumField.DETAILS))

    def sanitize(self, text: str) -> str:
        """Sanitize text by removing non-word characters for safe filenames."""
        return re.sub(r'\W+', '', text)

    def _entry_uuid_from_item(self, entry_item: QTreeWidgetItem) -> str:
        """Return an entry's UUID from tree item data, creating one if missing."""
        entry_uuid = entry_item.data(2, Qt.ItemDataRole.UserRole)
        if not isinstance(entry_uuid, str) or not entry_uuid:
            entry_uuid = str(uuid.uuid4())
            entry_item.setData(2, Qt.ItemDataRole.UserRole, entry_uuid)
        return entry_uuid

    def _category_uuid_from_item(self, cat_item: QTreeWidgetItem) -> str:
        """Return a category's UUID from tree item data (stored in column 1, Qt.ItemDataRole.UserRole)."""
        category_uuid = cat_item.data(1, Qt.ItemDataRole.UserRole)
        return category_uuid if isinstance(category_uuid, str) else ""

    def _find_entry_in_data(self, entry_uuid: str) -> CompendiumEntry | None:
        """Return the entry dict for the given uuid from the manager, or None."""
        return self.manager.get_entry_by_uuid(entry_uuid)

    def _find_and_select_entry_by_uuid(self, entry_uuid: str) -> bool:
        """Find an entry in the tree by uuid and select it.

        Returns True if found, False otherwise.
        """
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item is None:
                continue
            for j in range(cat_item.childCount()):
                item = cat_item.child(j)
                if item is None:
                    continue
                if item.data(2, Qt.ItemDataRole.UserRole) == entry_uuid:
                    self.tree.setCurrentItem(item)
                    return True
        return False

    def populate_compendium_tree(self) -> None:
        """Populate the tree view with compendium data from the manager."""
        selected_item_info = self.get_selected_item_info()

        # Block signals while rebuilding the tree to avoid spurious itemChanged
        # handling when we set item texts/programmatic data.
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            bold_font = QFont()
            bold_font.setBold(True)
            # Always reload from disk so the tree reflects the authoritative file state.
            # Migration of any legacy formats is performed by CompendiumManager;
            # EnhancedCompendium should only consume the canonical unified structure.
            self.compendium_data = self.manager.load_data()
            # reset any pending rename originals
            self._rename_originals.clear()
            for cat in self.compendium_data.get("categories", []):
                cat_name = cat.get("name")
                cat_item = QTreeWidgetItem(self.tree, [cat_name])
                cat_item.setData(0, Qt.ItemDataRole.UserRole, CompendiumEntryType.CATEGORY)
                cat_item.setData(1, Qt.ItemDataRole.UserRole, cat.get("uuid", ""))
                cat_item.setBackground(0, QBrush(ThemeManager.get_category_background_color()))
                cat_item.setFont(0, bold_font)
                # Entries are sourced from categories[].entries[] — the canonical list.
                # Preserve the canonical order as authored in the compendium file
                # instead of forcing an alphabetical sort here.
                for entry in cat.get("entries", []):
                    entry_name = entry.get("name", "Unnamed Entry")
                    entry_item = QTreeWidgetItem(cat_item, [entry_name])
                    entry_item.setData(0, Qt.ItemDataRole.UserRole, CompendiumEntryType.ENTRY)
                    entry_item.setData(1, Qt.ItemDataRole.UserRole, entry.get("content", ""))
                    entry_item.setData(2, Qt.ItemDataRole.UserRole, entry.get("uuid"))
                    cat_item.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        self.restore_selection(selected_item_info)
        if self.tree.currentItem() is None:
            self.clear_entry_ui()
        self.update_relation_combo()

    def get_selected_item_info(self) -> dict[str, CompendiumEntryType | str] | None:
        """Return info about the currently selected item for preserving selection."""
        current_item = self.tree.currentItem()
        if not current_item:
            return None
        item_type = current_item.data(0, Qt.ItemDataRole.UserRole)
        item_name = current_item.text(0)
        if item_type == CompendiumEntryType.ENTRY:
            entry_uuid = current_item.data(2, Qt.ItemDataRole.UserRole)
            # Preserve uuid for robust matching even if the entry was renamed or moved to another category.
            return {"type": CompendiumEntryType.ENTRY, "name": item_name, "uuid": entry_uuid}
        return {"type": CompendiumEntryType.CATEGORY, "name": item_name}

    def restore_selection(self, selected_item_info: dict[str, CompendiumEntryType | str] | None) -> None:
        """Attempt to reselect the previously selected item after refresh."""
        if not selected_item_info:
            return
        item_type = selected_item_info["type"]
        item_name = selected_item_info["name"]
        if item_type == CompendiumEntryType.CATEGORY:
            for i in range(self.tree.topLevelItemCount()):
                cat_item = self.tree.topLevelItem(i)
                if cat_item is None:
                    continue
                if cat_item.text(0) == item_name and cat_item.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.CATEGORY:
                    self.tree.setCurrentItem(cat_item)
                    return
        elif item_type == CompendiumEntryType.ENTRY:
            # Restore selection by UUID only — CompendiumManager guarantees UUIDs.
            entry_uuid = selected_item_info.get("uuid")
            if isinstance(entry_uuid, str) and entry_uuid:
                for i in range(self.tree.topLevelItemCount()):
                    cat_item = self.tree.topLevelItem(i)
                    if cat_item is None:
                        continue
                    for j in range(cat_item.childCount()):
                        entry_item = cat_item.child(j)
                        if entry_item is None:
                            continue
                        if entry_item.data(2, Qt.ItemDataRole.UserRole) == entry_uuid:
                            self.tree.setCurrentItem(entry_item)
                            return
        self.tree.clearSelection()

    def show_context_menu(self, pos: QPoint) -> None:
        """
        Show context menu for tree items (category / entry) with appropriate actions.
        """
        # If a recent selection change was cancelled by the unsaved-changes
        # prompt, the context menu requested by the same mouse event should
        # not be shown for the target item. Consume the cancelled state here
        # and return early.
        if self._last_selection_cancelled:
            logger.debug("show_context_menu: Context menu cancelled for recent selection change. _last_selection_cancelled cleared")
            # reset the flag and do not show any menu for the cancelled click
            self._last_selection_cancelled = False
            return

        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet(ThemeManager.get_menu_stylesheet())
        if item:  # The user right-clicked on a category or entry
            item_type = item.data(0, Qt.ItemDataRole.UserRole)
            if item_type == CompendiumEntryType.CATEGORY:
                menu.addAction(_("New Entry"), lambda: self.new_entry(item))
                menu.addAction(_("Rename Category"), lambda: self.rename_item(item, CompendiumEntryType.CATEGORY))
                menu.addAction(_("Delete Category"), lambda: self.delete_category(item))
            elif item_type == CompendiumEntryType.ENTRY:
                menu.addAction(_("Rename Entry"), lambda: self.rename_item(item, CompendiumEntryType.ENTRY))
                menu.addAction(_("Delete Entry"), lambda: self.delete_entry(item))
                # Add Move Up/Down actions but disable them when at the bounds of the category
                move_up_action = menu.addAction(_("Move Up"), lambda: self.move_item(item, "up"))
                move_down_action = menu.addAction(_("Move Down"), lambda: self.move_item(item, "down"))
                # Determine position within its parent category so we can disable impossible moves
                parent = item.parent() or self.tree.invisibleRootItem()
                if parent is not None:
                    index = parent.indexOfChild(item)
                    if index <= 0:
                        move_up_action.setEnabled(False)
                    if index >= max(0, parent.childCount() - 1):
                        move_down_action.setEnabled(False)
                # Disable "Move to Category" when there are fewer than two categories
                move_action = menu.addAction(_("Move to Category"), lambda: self.move_entry(item))
                num_categories = len(self.compendium_data.get("categories", []))
                if num_categories < 2:
                    move_action.setEnabled(False)
        else:  # The user right-clicked on a blank spot in the tree
            menu.addAction(_("New Category"), self.new_category)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))


    def on_item_double_clicked(self, item: QTreeWidgetItem | None, column: int) -> None:
        """Invoke the same rename dialog used by the context menu when double-clicked."""
        if item is None:
            return
        item_type = item.data(0, Qt.ItemDataRole.UserRole)
        if item_type == CompendiumEntryType.ENTRY:
            self.rename_item(item, CompendiumEntryType.ENTRY)
        elif item_type == CompendiumEntryType.CATEGORY:
            self.rename_item(item, CompendiumEntryType.CATEGORY)

    def save_current_entry(self) -> bool:
        """Save the current entry's data to the compendium."""
        if self.current_entry_item is not None:
            logger.debug("save_current_entry: Setting _suppress_unsaved_prompt")
            self._suppress_unsaved_prompt = True
            try:
                save_ok = self.save_entry(self.current_entry_item)
                if save_ok:
                    self._reset_dirty()
                return save_ok
            finally:
                self._suppress_unsaved_prompt = False
        return True

    def save_entry(self, entry_item: QTreeWidgetItem) -> bool:
        """
        Persist the currently displayed entry back to disk via the manager.
        Updates the unified categories[].entries[] record with all fields: content,
        details, tags, relationships, and images.
        """
        entry_name = entry_item.text(0)
        entry_uuid = self._entry_uuid_from_item(entry_item)
        category_item = entry_item.parent()
        if not category_item:
            return False
        category_name = category_item.text(0)
        content = self.editor.toPlainText()
        # Keep the tree item's cached content in sync before the tree is rebuilt.
        entry_item.setData(1, Qt.ItemDataRole.UserRole, content)

        details = self.details_editor.toPlainText()
        tags: list[CompendiumTag] = []
        for i in range(self.tags_list.count()):
            tag_item = self.tags_list.item(i)
            if tag_item is None:
                continue
            tag_color = tag_item.data(Qt.ItemDataRole.UserRole)
            tags.append(
                CompendiumTag(
                    name=tag_item.text(),
                    color=tag_color if isinstance(tag_color, str) else "#000000",
                )
            )

        relationships: list[CompendiumRelationship] = []
        for i in range(self.relationships_list.topLevelItemCount()):
            relationship_item = self.relationships_list.topLevelItem(i)
            if relationship_item is None:
                continue
            relationship_uuid = relationship_item.data(0, Qt.ItemDataRole.UserRole)
            relationships.append(
                CompendiumRelationship(
                    uuid=relationship_uuid if isinstance(relationship_uuid, str) else "",
                    type=relationship_item.text(1),
                )
            )
        images: list[str] = self.get_images()

        entry = CompendiumEntry(
            uuid=entry_uuid,
            name=entry_name,
            content=content,
            details=details,
            tags=tags,
            relationships=relationships,
            images=images,
        )

        logger.info(f"Updating entry '{entry_name}' with UUID {entry_uuid}")
        ok = self.manager.update_entry(entry_uuid, entry)
        if not ok:
            # Safety fallback: entry missing from disk (e.g. corrupted state) — re-add it.
            print(f"Warning: entry uuid {entry_uuid} not found. Re-adding to category '{category_name}'.")
            category_uuid = self._category_uuid_from_item(category_item)
            new_entry = self.manager.add_entry(category_uuid, entry_name, content)
            if new_entry:
                entry_item.setData(2, Qt.ItemDataRole.UserRole, new_entry["uuid"])
                self.manager.update_entry(new_entry["uuid"], entry)
                ok = True
        return ok

    def new_category(self) -> None:
        """Create a new category in the compendium."""
        # Respect unsaved-change guard: abort if the user cancels the save prompt.
        if not self.maybe_commit_unsaved_changes():
            return

        name, ok = QInputDialog.getText(self, _("New Category"), _("Category name:"))
        if ok and name:
            self.manager.add_category(name)
            # Tree is rebuilt by the event bus; find and select the new category.
            for i in range(self.tree.topLevelItemCount()):
                top_level_item = self.tree.topLevelItem(i)
                if top_level_item is not None and top_level_item.text(0) == name:
                    self.tree.setCurrentItem(top_level_item)
                    break

    def new_entry(self, category_item: QTreeWidgetItem) -> None:
        """Create a new entry under the specified category."""
        # If there are unsaved changes on another entry, ask the user first.
        if not self.maybe_commit_unsaved_changes():
            return

        name, ok = QInputDialog.getText(self, _("New Entry"), _("Entry name:"))
        if ok and name:
            category_uuid = self._category_uuid_from_item(category_item)
            new_entry_dict = self.manager.add_entry(category_uuid, name)
            if new_entry_dict:
                # Tree is rebuilt by the event bus; find and select the new entry.
                self._find_and_select_entry_by_uuid(new_entry_dict["uuid"])

    def delete_category(self, category_item: QTreeWidgetItem) -> None:
        """Delete a category and all its entries after confirmation."""
        # Respect unsaved changes guard before destructive operations.
        if not self.maybe_commit_unsaved_changes():
            return

        confirm = QMessageBox.question(self, _("Confirm Deletion"),
            _("Are you sure you want to delete the category '{}' and all its entries?").format(category_item.text(0)),
            QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            category_uuid = self._category_uuid_from_item(category_item)
            self.manager.remove_category(category_uuid)
            # Tree is rebuilt by the event bus.

    def delete_entry(self, entry_item: QTreeWidgetItem) -> None:
        """Delete an entry after confirmation."""
        # Respect unsaved changes guard before destructive operations.
        if not self.maybe_commit_unsaved_changes():
            return

        entry_name = entry_item.text(0)
        entry_uuid = entry_item.data(2, Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(self, _("Confirm Deletion"),
            _("Are you sure you want to delete the entry '{}'?").format(entry_name),
            QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.manager.remove_entry(entry_uuid)
            # Tree is rebuilt by the event bus (which also calls clear_entry_ui if needed).

    def rename_item(self, item: QTreeWidgetItem, item_type: CompendiumEntryType) -> None:
        """Rename a category or entry."""
        # Respect unsaved changes guard before mutating data.
        if not self.maybe_commit_unsaved_changes():
            return

        current_text = item.text(0)
        new_text, ok = QInputDialog.getText(self, _("Rename {}").format(item_type.capitalize()), _("New name:"), text=current_text)
        if ok and new_text:
            if item_type == CompendiumEntryType.ENTRY:
                entry_uuid = self._entry_uuid_from_item(item)
                self.manager.rename_entry(entry_uuid, new_text)
                # Update local state if this was the displayed entry.
                if self.current_entry_item == item:
                    self.entry_name_label.setText(new_text)
            else:
                category_uuid = self._category_uuid_from_item(item)
                self.manager.rename_category(category_uuid, new_text)
            # Tree is rebuilt by the event bus.

    def move_item(self, item: QTreeWidgetItem, direction: str) -> None:
        """Move an entry up or down within its category."""
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        moved = False
        if direction == "up" and index > 0:
            parent.takeChild(index)
            parent.insertChild(index - 1, item)
            self.tree.setCurrentItem(item)
            moved = True
        elif direction == "down" and index < parent.childCount() - 1:
            parent.takeChild(index)
            parent.insertChild(index + 1, item)
            self.tree.setCurrentItem(item)
            moved = True
        if moved:
            self.update_category_data(parent)

    def update_category_data(self, parent: QTreeWidgetItem) -> None:
        """Persist the entry order of *parent*'s category to match the current tree order."""
        if parent != self.tree.invisibleRootItem():
            category_uuid = self._category_uuid_from_item(parent)
            if category_uuid:
                ordered_uuids = [parent.child(i).data(2, Qt.ItemDataRole.UserRole) for i in range(parent.childCount())]
                self.manager.reorder_entries(category_uuid, ordered_uuids)
                # Tree is rebuilt by the event bus.

    def move_entry(self, entry_item: QTreeWidgetItem) -> None:
        """Move an entry to a different category via context menu."""
        # If we have unsaved changes and the user cancels the save prompt, abort the move.
        if not self.maybe_commit_unsaved_changes():
            return

        menu = QMenu(self)
        menu.setStyleSheet(ThemeManager.get_menu_stylesheet())
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            if cat_item.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.CATEGORY:
                action = menu.addAction(cat_item.text(0))
                action.setData(cat_item)
        selected_action = menu.exec_(QCursor.pos())
        if selected_action is not None:
            target_category = selected_action.data()
            if target_category is not None:
                entry_uuid = entry_item.data(2, Qt.ItemDataRole.UserRole)
                target_category_uuid = self._category_uuid_from_item(target_category)
                moved = self.manager.move_entry(entry_uuid, target_category_uuid)
                if moved:
                    # Force local refresh from disk so this window stays in sync even
                    # if event delivery/order is delayed.
                    self.populate_compendium_tree()
                    self._find_and_select_entry_by_uuid(entry_uuid)

    def on_item_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        """Handle tree item selection changes with a Save/Discard/Cancel guard when dirty."""
        # Clear any previous cancelled marker at the start of a new selection
        # change cycle. This ensures the marker only applies to the immediate
        # mouse event that caused the cancellation.
        if self._last_selection_cancelled:
            logger.debug("on_item_changed: Clearing _last_selection_cancelled flag")
            self._last_selection_cancelled = False

        if (
            previous is not None
            and previous.data(0, Qt.ItemDataRole.UserRole) == CompendiumEntryType.ENTRY
            and self.is_dirty()
        ):
            if self._suppress_unsaved_prompt:
                logger.debug("Suppressing unsaved changes prompt for entry change")
                return
            entry_name = previous.text(0)
            choice = QMessageBox.question(
                self,
                _("Unsaved Changes"),
                _("You have unsaved changes for '{}'. Save before continuing?").format(entry_name),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if choice == QMessageBox.Save:
                self.save_current_entry()
            elif choice == QMessageBox.Discard:
                self._discard_current_entry_changes(reload_entry=False)
            else:
                # Cancel: schedule a restore of the tree selection back to the
                # dirty entry and mark that the selection was cancelled.
                # _last_selection_cancelled suppresses
                # TODO: This is hack to undo a item change by restoring previous selection
                logger.debug("on_item_changed: Setting _last_selection_cancelled and scheduling _restore_previous_selection")
                self._last_selection_cancelled = True
                QTimer.singleShot(0, lambda prev=previous: self._restore_previous_selection(prev))
                return

        # Normal selection handling (when not cancelled): load or clear UI
        if current is None:
            self.clear_entry_ui()
            return

        # The tree can be rebuilt by save/discard flows while handling the same
        # selection-change signal, which may invalidate the original *current* item.
        try:
            current_type = current.data(0, Qt.ItemDataRole.UserRole)
        except RuntimeError:
            self.clear_entry_ui()
            return

        if current_type == CompendiumEntryType.ENTRY:
            self.load_entry(current.text(0), current)
        else:
            self.clear_entry_ui()

    def _restore_previous_selection(self, previous: QTreeWidgetItem | None) -> None:
        """Restore the tree selection to *previous* while blocking signals.

        This helper is invoked via singleShot to ensure the restore happens
        after other event handlers triggered by the same user action.

        TODO: This is a hack
        """
        try:
            self.tree.blockSignals(True)
            # Only restore if the previous item is still valid.
            if previous is not None:
                logger.debug(f"Restoring previous selection to {previous.text(0)}")
                self.tree.setCurrentItem(previous)
        finally:
            self.tree.blockSignals(False)
            # Consume the cancelled marker so subsequent independent events are
            # not affected.
            if self._last_selection_cancelled:
                logger.debug("_restore_previous_selection: Clearing _last_selection_cancelled flag after restoring previous selection")
            self._last_selection_cancelled = False



    def load_entry(self, entry_name: str, entry_item: QTreeWidgetItem) -> None:
        """
        Load all data for the selected entry into the UI panels.
        Populates the Overview editor from categories[].entries[].content and the
        Details/Tags/Relationships/Images panels from the same unified entry dict.

        Args:
            entry_name (str): Name of the entry
            entry_item: The QTreeWidgetItem for this entry
        """

        if self.current_entry_item and self.is_dirty():
            if self._suppress_unsaved_prompt:
                logger.debug("load_entry: Suppressing unsaved changes prompt for entry load")
            else:
                self.save_current_entry()
        
        self.current_entry_item = entry_item
        entry_uuid = self._entry_uuid_from_item(entry_item)
        self.current_entry_uuid = entry_uuid
        logger.info(f"Loading entry '{entry_name}' with uuid '{entry_uuid}'")
        
        self.entry_name_label.setText(entry_name)
        # Entry selected: show entry-specific actions; enabled state is handled by dirty tracking.
        self.save_button.show()
        self.revert_button.show()
        self.update_add_tag_button_state()
        
        # Block signals while loading to avoid spuriously marking dirty.
        self.editor.blockSignals(True)
        
        content_data = entry_item.data(1, Qt.ItemDataRole.UserRole)
        content = content_data if isinstance(content_data, str) else ""
        self.editor.setPlainText(content)         

        # Load extended fields directly from the unified entry dict.
        entry_data: CompendiumEntry = self._find_entry_in_data(entry_uuid) or self.manager.make_empty_entry(entry_name, content)
        self.details_editor.blockSignals(True)
        self.details_editor.setPlainText(entry_data["details"])
        self.details_editor.blockSignals(False)
        self.tags_list.clear()
        for tag in entry_data["tags"]:
            # Tags can be stored as dicts {name, color} or plain strings (legacy).
            if isinstance(tag, dict):
                tag_name = tag.get("name", "")
                tag_color = tag.get("color", "#000000")
            else:
                tag_name = tag
                tag_color = "#000000"
            item = QListWidgetItem(tag_name)
            item.setData(Qt.ItemDataRole.UserRole, tag_color)
            item.setForeground(QBrush(QColor(tag_color)))
            item.setToolTip(_("right-click to move the tag within this list - this impacts the colour of your entry"))
            self.tags_list.addItem(item)
        self.relationships_list.clear()
        # Build a uuid→name lookup so we can display a human-readable name in the list.
        entry_name_by_uuid: dict[str, str] = {
            e.get("uuid", ""): e.get("name", "")
            for cat in self.compendium_data.get("categories", [])
            for e in cat.get("entries", [])
        }
        for rel in entry_data["relationships"]:
            rel_uuid = rel.get("uuid", "")
            rel_display = entry_name_by_uuid.get(rel_uuid, rel_uuid) if rel_uuid else ""
            rel_item = QTreeWidgetItem([rel_display, rel.get("type", "")])
            rel_item.setData(0, Qt.ItemDataRole.UserRole, rel_uuid)  # store uuid for save round-trip
            self.relationships_list.addTopLevelItem(rel_item)
        self.load_images(entry_data["images"])
        self.update_entry_indicator()

        self.editor.blockSignals(False)
        self._reset_dirty()
        self.tabs.show()

    def clear_entry_ui(self) -> None:
        """Clear all entry data from the UI panels."""
        self.entry_name_label.setText(_("No entry selected"))
        # No entry selected (or category selected): hide entry-specific action buttons.
        self.save_button.hide()
        self.revert_button.hide()
        self.add_tag_button.setEnabled(False)
        self.editor.clear()
        self.details_editor.clear()
        self.tags_list.clear()
        self.relationships_list.clear()
        self.clear_images()
        self._current_images = []
        self._reset_dirty()
        self.tabs.hide()
        self.current_entry_item = None
        self.current_entry_uuid = None

    def _ensure_window_visible(self) -> None:
        """Ensure this window is restored, visible, and focused for user prompts."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def open_with_entry(self, project_name: str, entry_name: str | None) -> None:
        """Make visible and raise window, then show the entry.

        Respects the dirty state of the currently selected entry: if there are
        unsaved changes the user will be prompted to Save / Discard / Cancel.
        The operation is aborted when the user chooses Cancel.
        """
        # Show the window before prompting so the dialog context is obvious.
        self._ensure_window_visible()

        if not self.maybe_commit_unsaved_changes():
            return
        if project_name != self.project_name:
            self.populate_project_combo(project_name)
            self.change_project(project_name, select_default_item=not entry_name)

        # Project switches can affect focus/state; enforce visibility again.
        self._ensure_window_visible()

        if entry_name:
            self.find_and_select_entry(entry_name)
        elif self.tree.currentItem() is None:
            self.select_first_entry()

    def find_and_select_entry(self, entry_name: str) -> None:
        """Search the tree and select an entry by name."""
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item is None:
                continue
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                if entry_item is None:
                    continue
                item_text = entry_item.text(0)
                if item_text == entry_name:
                    self.tree.setCurrentItem(entry_item)
                    return

    ## Tags

    def add_tag(self) -> None:
        """Add a new tag to the current entry."""
        tag_name = self.tag_input.text().strip()
        if tag_name and self.current_entry_item is not None:
            tag_color = self._current_tag_color
            item = QListWidgetItem(tag_name)
            item.setData(Qt.ItemDataRole.UserRole, tag_color)
            item.setForeground(QBrush(QColor(tag_color)))
            item.setToolTip(_("right-click to move the tag within this list - this impacts the colour of your entry"))
            self.tags_list.addItem(item)
            self.tag_input.clear()
            self.mark_dirty(CompendiumField.TAGS)

    def update_add_tag_button_state(self) -> None:
        """Enable the add tag button only when there is text in the tag input field."""
        has_text = bool(self.tag_input.text().strip())
        has_entry = self.current_entry_item is not None
        self.add_tag_button.setEnabled(has_text and has_entry)

    def choose_tag_color(self) -> None:
        """Open a color dialog to choose a tag color."""
        color = QColorDialog.getColor(QColor(self._current_tag_color), self)
        if color.isValid():
            self._current_tag_color = color.name()
            self.tag_color_preview.setStyleSheet(f"background-color: {color.name()};")
            self.mark_dirty(CompendiumField.TAGS)
        self.raise_()
        self.activateWindow()

    def show_tags_context_menu(self, pos: QPoint) -> None:
        """Show context menu for tags list."""
        item = self.tags_list.itemAt(pos)
        if item:
            menu = QMenu(self)
            menu.setStyleSheet(ThemeManager.get_menu_stylesheet())
            menu.addAction(_("Remove Tag"), lambda: self.remove_tag(item))
            menu.addAction(_("Move Up"), lambda: self.move_tag(item, "up"))
            menu.addAction(_("Move Down"), lambda: self.move_tag(item, "down"))
            menu.exec_(self.tags_list.viewport().mapToGlobal(pos))

    def remove_tag(self, item: QListWidgetItem) -> None:
        """Remove a tag from the tags list."""
        row = self.tags_list.row(item)
        self.tags_list.takeItem(row)
        self.mark_dirty(CompendiumField.TAGS)

    def move_tag(self, item: QListWidgetItem, direction: str) -> None:
        """Move a tag up or down in the tags list."""
        row = self.tags_list.row(item)
        if direction == "up" and row > 0:
            self.tags_list.takeItem(row)
            self.tags_list.insertItem(row - 1, item)
            self.tags_list.setCurrentItem(item)
        elif direction == "down" and row < self.tags_list.count() - 1:
            self.tags_list.takeItem(row)
            self.tags_list.insertItem(row + 1, item)
            self.tags_list.setCurrentItem(item)
        self.mark_dirty(CompendiumField.TAGS)

    #### relationships

    def update_relation_combo(self) -> None:
        """Repopulate the relationship combo from the canonical categories[].entries[] list."""
        self.relationship_combo.clear()
        for cat in self.compendium_data.get("categories", []):
            for entry in cat.get("entries", []):
                self.relationship_combo.addItem(entry.get("name", ""))
                self.relationship_combo.setItemData(
                    self.relationship_combo.count() - 1, entry.get("uuid", "")
                )

    def add_relationship(self) -> None:
        """Add a new relationship to the current entry."""
        rel_name = self.relationship_combo.currentText()
        rel_uuid = self.relationship_combo.currentData() or ""
        rel_type = self.relationship_type.text().strip()
        if rel_name and rel_type and self.current_entry_item is not None:
            rel_item = QTreeWidgetItem([rel_name, rel_type])
            rel_item.setData(0, Qt.ItemDataRole.UserRole, rel_uuid)  # uuid stored for save round-trip
            self.relationships_list.addTopLevelItem(rel_item)
            self.relationship_type.clear()
            self.mark_dirty(CompendiumField.RELATIONSHIPS)

    def show_relationships_context_menu(self, pos: QPoint) -> None:
        """Show context menu for relationships list."""
        item = self.relationships_list.itemAt(pos)
        if item:
            menu = QMenu(self)
            menu.setStyleSheet(ThemeManager.get_menu_stylesheet())
            menu.addAction(_("Remove Relationship"), lambda: self.remove_relationship(item))
            menu.exec_(self.relationships_list.viewport().mapToGlobal(pos))

    def remove_relationship(self, item: QTreeWidgetItem) -> None:
        """Remove a relationship from the relationships list."""
        index = self.relationships_list.indexOfTopLevelItem(item)
        self.relationships_list.takeTopLevelItem(index)
        self.mark_dirty(CompendiumField.RELATIONSHIPS)

    ## Images

    def clear_images(self) -> None:
        """Clear all images from the images layout."""
        while self.image_layout.count():
            child = self.image_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def add_image(self) -> None:
        """Add an image to the current entry."""
        file_name, _unused = QFileDialog.getOpenFileName(self, _("Select Image"), "",
                                                         _("Images (*.png *.jpg *.jpeg *.bmp)"))
        if file_name and self.current_entry_item is not None:
            pixmap = QPixmap(file_name)
            if not pixmap.isNull():
                label = QLabel()
                label.setPixmap(pixmap.scaled(100, 100, Qt.KeepAspectRatio))
                self.image_layout.addWidget(label)
                self._current_images.append(file_name)
                self.mark_dirty(CompendiumField.IMAGES)

    def load_images(self, images: list[str] | None) -> None:
        """Load images into the images tab."""
        self._current_images = list(images or [])
        self.clear_images()
        for image_path in self._current_images:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                label = QLabel()
                label.setPixmap(pixmap.scaled(100, 100, Qt.KeepAspectRatio))
                self.image_layout.addWidget(label)

    def get_images(self) -> list[str]:
        """Return the list of image paths for the current entry."""
        if self.current_entry_item is not None:
            return list(self._current_images)
        return []

    def update_entry_indicator(self) -> None:
        """Update the entry name label colour: green if the entry has any relationships."""
        if self.current_entry_uuid is not None:
            entry_data: CompendiumEntry = self._find_entry_in_data(self.current_entry_uuid) or self.manager.make_empty_entry("")
            relationships = entry_data["relationships"]
            if relationships:
                self.entry_name_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: green;")
            else:
                self.entry_name_label.setStyleSheet("font-size: 16pt; font-weight: bold;")

    def on_compendium_updated(self, updated_project_name: str) -> None:
        """Handle compendium update notifications from the event bus."""
        if updated_project_name == self.project_name:
            self.populate_compendium_tree()

    def filter_tree(self) -> None:
        """Filter tree items by entry name or tag name matching the search bar text."""
        search_text = self.search_bar.text()
        # One manager call loads all matching entries; avoids per-item disk reads.
        matching_uuids = set(self.manager.find_entries(search_text).keys())
        for i in range(self.tree.topLevelItemCount()):
            cat_item = self.tree.topLevelItem(i)
            if cat_item is None:
                continue
            cat_visible = False
            for j in range(cat_item.childCount()):
                entry_item = cat_item.child(j)
                if entry_item is None:
                    continue
                entry_uuid = entry_item.data(2, Qt.ItemDataRole.UserRole)
                entry_visible = not search_text or entry_uuid in matching_uuids
                entry_item.setHidden(not entry_visible)
                if entry_visible:
                    cat_visible = True
            cat_item.setHidden(not cat_visible)
