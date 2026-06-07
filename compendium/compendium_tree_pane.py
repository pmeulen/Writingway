"""
Compendium Tree pane for the (MVP) Enhanced Compendium window.

Per ``tasks/mvp.md`` (house rule): one module owns one pane and contains:

* ``ICompendiumTreeView`` - the View contract (Presenter -> View), an ``ABC``.
* ``CompendiumTreeEvents`` - the View -> Presenter contract, a ``Protocol``.
* ``CompendiumTreePresenter`` - PyQt-free decisions/orchestration.
* ``CompendiumTreeWidget`` - the humble Qt View (the only PyQt5 code here).

The pane is currently a skeleton: the contracts, presenter and widget are all
empty of behaviour.  Functionality (populating the tree, selection,
add/rename/move/delete, …) will be added in later steps.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from gettext import gettext as _
from typing import TYPE_CHECKING, Protocol

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    from compendium.compendium_manager import CompendiumManager
    from compendium.compendium_types import CompendiumCoordinator, CompendiumData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ICompendiumTreeView (Presenter -> View)
# ---------------------------------------------------------------------------
class ICompendiumTreeView(ABC):
    """Contract the ``CompendiumTreePresenter`` relies on. No PyQt types appear here."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
        ...

    @abstractmethod
    def populate_tree(self, data: "CompendiumData") -> None:
        """Replace the tree contents with the given CompendiumData (categories + entries)."""
        ...

    @abstractmethod
    def filter_visible(self, visible_uuids: set[str]) -> None:
        """Hide/show entries so that only those whose uuid is in *visible_uuids* remain visible."""
        ...


# ---------------------------------------------------------------------------
# CompendiumTreeEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class CompendiumTreeEvents(Protocol):
    """What the compendium-tree view can tell its presenter. Implemented by the presenter."""

    def on_search_text_changed(self, text: str) -> None:
        """Called by the search bar when its text changes (real-time filtering)."""
        ...

    def on_entry_selected(self, entry_uuid: str) -> None:
        """An entry row was clicked / selected in the tree."""
        ...

    def on_category_selected(self, category_uuid: str) -> None:
        """A category row was clicked / selected in the tree."""
        ...

    def on_new_category_requested(self) -> None:
        """User asked to create a new category via context menu or toolbar button."""
        ...

    def on_new_entry_requested(self, category_uuid: str) -> None:
        """User asked to add a new entry under the given category."""
        ...

    def on_rename_requested(self, uuid: str, item_type: str) -> None:
        """User asked to rename the given category or entry."""
        ...

    def on_delete_requested(self, uuid: str, item_type: str) -> None:
        """User asked to delete the given category or entry."""
        ...

    def on_move_requested(self, entry_uuid: str, direction: str) -> None:
        """User asked to move the entry up/down within its category."""
        ...


# ---------------------------------------------------------------------------
# CompendiumTreePresenter (PyQt-free)
# ---------------------------------------------------------------------------
class CompendiumTreePresenter:
    """PyQt-free presenter for the compendium tree pane.

    Connects to the ``CompendiumManager`` model and reports cross-pane intents
    to the coordinating presenter.  Currently a skeleton.
    """

    def __init__(self, compendium: CompendiumManager, coordinator: CompendiumCoordinator) -> None:
        logger.debug("Initializing CompendiumTreePresenter")
        self._compendium = compendium
        self._coordinator = coordinator
        self._view: ICompendiumTreeView | None = None
        self._project_name: str | None = None

    def set_view(self, view: ICompendiumTreeView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view

    def reset_for_project(self, project_name: str, *, compendium: "CompendiumManager | None" = None) -> None:
        """Load fresh data via manager and populate the view (stage-2 implementation).

        If *compendium* is supplied it replaces the stored manager, allowing
        the presenter to stay in sync after a project switch that creates a
        new CompendiumManager instance.
        """
        logger.info(f"CompendiumTreePresenter reset_for_project: {project_name}")
        self._project_name = project_name
        if compendium is not None:
            self._compendium = compendium
        if self._view is not None:
            data = self._compendium.load_data()
            self._view.populate_tree(data)

    def on_search_text_changed(self, text: str) -> None:
        """Use manager.find_entries to determine which entries should stay visible and tell the view."""
        logger.debug(f"CompendiumTreePresenter on_search_text_changed: '{text}'")
        if self._view is None:
            return
        matching = self._compendium.find_entries(text)
        visible_uuids = set(matching.keys())
        self._view.filter_visible(visible_uuids)

    def on_entry_selected(self, entry_uuid: str) -> None:
        """Forward selection of an entry to the coordinator."""
        logger.debug(f"CompendiumTreePresenter on_entry_selected: {entry_uuid}")
        if hasattr(self._coordinator, "on_entry_selected"):
            self._coordinator.on_entry_selected(entry_uuid)

    def on_category_selected(self, category_uuid: str) -> None:
        """Forward selection of a category to the coordinator."""
        logger.debug(f"CompendiumTreePresenter on_category_selected: {category_uuid}")
        if hasattr(self._coordinator, "on_category_selected"):
            self._coordinator.on_category_selected(category_uuid)

    def on_new_category_requested(self) -> None:
        """Forward 'create new category' intent to coordinator (or perform locally for tests)."""
        logger.debug("CompendiumTreePresenter on_new_category_requested")
        if hasattr(self._coordinator, "on_new_category_requested"):
            self._coordinator.on_new_category_requested()
        else:
            self._perform_new_category()

    def on_new_entry_requested(self, category_uuid: str) -> None:
        """Forward 'create new entry under category' intent."""
        logger.debug(f"CompendiumTreePresenter on_new_entry_requested: {category_uuid}")
        if hasattr(self._coordinator, "on_new_entry_requested"):
            self._coordinator.on_new_entry_requested(category_uuid)
        else:
            self._perform_new_entry(category_uuid)

    def on_rename_requested(self, uuid: str, item_type: str) -> None:
        """Forward rename intent for category or entry."""
        logger.debug(f"CompendiumTreePresenter on_rename_requested: {item_type} {uuid}")
        if hasattr(self._coordinator, "on_rename_requested"):
            self._coordinator.on_rename_requested(uuid, item_type)
        else:
            self._perform_rename(uuid, item_type)

    def on_delete_requested(self, uuid: str, item_type: str) -> None:
        """Forward delete intent for category or entry."""
        logger.debug(f"CompendiumTreePresenter on_delete_requested: {item_type} {uuid}")
        if hasattr(self._coordinator, "on_delete_requested"):
            self._coordinator.on_delete_requested(uuid, item_type)
        else:
            self._perform_delete(uuid, item_type)

    def on_move_requested(self, entry_uuid: str, direction: str) -> None:
        """Forward reorder (move up/down) intent."""
        logger.debug(f"CompendiumTreePresenter on_move_requested: {direction} {entry_uuid}")
        if hasattr(self._coordinator, "on_move_requested"):
            self._coordinator.on_move_requested(entry_uuid, direction)
        else:
            self._perform_move(entry_uuid, direction)

    # -----------------------------------------------------------------------
    # CRUD implementations (Stage 5) – these are invoked by the coordinator
    # -----------------------------------------------------------------------
    def _perform_new_category(self) -> None:
        """Ask user for name, call manager, then refresh tree."""
        if self._view is None:
            return
        name, ok = QInputDialog.getText(None, _("New Category"), _("Category name:"))
        if ok and name:
            self._compendium.add_category(name)
            data = self._compendium.load_data()
            self._view.populate_tree(data)

    def _perform_new_entry(self, category_uuid: str) -> None:
        """Prompt for entry name and add under the given category."""
        if self._view is None:
            return
        name, ok = QInputDialog.getText(None, _("New Entry"), _("Entry name:"))
        if ok and name:
            self._compendium.add_entry(category_uuid, name)
            data = self._compendium.load_data()
            self._view.populate_tree(data)

    def _perform_rename(self, uuid: str, item_type: str) -> None:
        """Rename a category or entry via input dialog."""
        if self._view is None:
            return
        # Find current name from live data
        data = self._compendium.load_data()
        current_name = ""
        if item_type == "category":
            for cat in data.get("categories", []):
                if cat.get("uuid") == uuid:
                    current_name = cat.get("name", "")
                    break
        else:
            for cat in data.get("categories", []):
                for ent in cat.get("entries", []):
                    if ent.get("uuid") == uuid:
                        current_name = ent.get("name", "")
                        break
        new_text, ok = QInputDialog.getText(None, _("Rename {}").format(item_type.capitalize()), _("New name:"), text=current_name)
        if ok and new_text:
            if item_type == "entry":
                self._compendium.rename_entry(uuid, new_text)
            else:
                self._compendium.rename_category(uuid, new_text)
            refreshed = self._compendium.load_data()
            self._view.populate_tree(refreshed)

    def _perform_delete(self, uuid: str, item_type: str) -> None:
        """Delete after confirmation."""
        if self._view is None:
            return
        confirm = QMessageBox.question(
            None,
            _("Confirm Deletion"),
            _("Are you sure you want to delete the {}?").format(item_type),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            if item_type == "entry":
                self._compendium.remove_entry(uuid)
            else:
                self._compendium.remove_category(uuid)
            refreshed = self._compendium.load_data()
            self._view.populate_tree(refreshed)

    def _perform_move(self, entry_uuid: str, direction: str) -> None:
        """Reorder entry or move to another category (MVP treats 'to_category' as no-op for now)."""
        if self._view is None or direction == "to_category":
            return
        data = self._compendium.load_data()
        for cat in data.get("categories", []):
            for idx, ent in enumerate(cat.get("entries", [])):
                if ent.get("uuid") == entry_uuid:
                    new_idx = idx - 1 if direction == "up" else idx + 1
                    if 0 <= new_idx < len(cat["entries"]):
                        cat["entries"].insert(new_idx, cat["entries"].pop(idx))
                        self._compendium.reorder_entries(cat["uuid"], [e["uuid"] for e in cat["entries"]])
                        refreshed = self._compendium.load_data()
                        self._view.populate_tree(refreshed)
                    return


# ---------------------------------------------------------------------------
# CompendiumTreeWidget (the only PyQt5 code in this module)
# ---------------------------------------------------------------------------
class CompendiumTreeWidget(QWidget, ICompendiumTreeView, metaclass=QtWidgetABCMeta):
    """Humble Qt View for the compendium tree pane. Currently a skeleton."""

    def __init__(self, events: CompendiumTreeEvents) -> None:
        super().__init__()
        self._events = events
        self._setup_widgets()

    def _setup_widgets(self) -> None:
        """Build the tree widgets. Ported from EnhancedCompendiumWindow."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # 1) Search bar
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText(_("Search entries and tags..."))
        self.search_bar.textChanged.connect(self._on_search_bar_text_changed)
        self.main_layout.addWidget(self.search_bar)

        # 2) Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_("Compendium"))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.currentItemChanged.connect(self._on_tree_current_item_changed)
        self.tree.customContextMenuRequested.connect(self._on_context_menu_requested)
        self.main_layout.addWidget(self.tree)

        # 3) Toolbar (optional, but good for completeness if porting from EnhancedCompendiumWindow's intended structure)
        self._setup_tree_toolbar()

    def _setup_tree_toolbar(self) -> None:
        """Add any tree-specific utility buttons at the bottom of the pane."""
        self.toolbar_layout = QHBoxLayout()

        self.new_category_button = QPushButton(_("New Category"))
        self.new_category_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.new_category_button.clicked.connect(self._on_new_category_button_clicked)

        self.toolbar_layout.addWidget(self.new_category_button)
        self.main_layout.addLayout(self.toolbar_layout)

    def reset(self) -> None:
        """Clear the tree (empty state)."""
        self.tree.clear()

    def populate_tree(self, data: "CompendiumData") -> None:
        """Build category and entry items from CompendiumData, storing dicts in UserRole."""
        from PyQt5.QtGui import QFont
        from PyQt5.QtWidgets import QTreeWidgetItem

        self.tree.blockSignals(True)
        self.tree.clear()
        categories = data.get("categories", [])
        for category in categories:
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, category.get("name", ""))
            cat_item.setData(0, Qt.ItemDataRole.UserRole, category)
            # Bold + optional colour for category rows
            font = QFont()
            font.setBold(True)
            cat_item.setFont(0, font)

            for entry in category.get("entries", []):
                entry_item = QTreeWidgetItem(cat_item)
                entry_item.setText(0, entry.get("name", ""))
                entry_item.setData(0, Qt.ItemDataRole.UserRole, entry)

        self.tree.expandAll()
        self.tree.blockSignals(False)

    def filter_visible(self, visible_uuids: set[str]) -> None:
        """Hide/show entries and their categories according to *visible_uuids* (empty → show all)."""
        from PyQt5.QtWidgets import QTreeWidgetItem

        self.tree.blockSignals(True)
        show_all = len(visible_uuids) == 0
        any_visible = False
        for i in range(self.tree.topLevelItemCount()):
            cat_item: QTreeWidgetItem | None = self.tree.topLevelItem(i)
            if cat_item is None:
                continue
            cat_visible = False
            for j in range(cat_item.childCount()):
                entry_item: QTreeWidgetItem | None = cat_item.child(j)
                if entry_item is None:
                    continue
                entry = entry_item.data(0, Qt.ItemDataRole.UserRole) or {}
                entry_uuid = entry.get("uuid", "")
                entry_visible = show_all or entry_uuid in visible_uuids
                entry_item.setHidden(not entry_visible)
                if entry_visible:
                    cat_visible = True
                    any_visible = True
            cat_item.setHidden(not cat_visible)
        self.tree.blockSignals(False)

    def _on_search_bar_text_changed(self, text: str) -> None:
        """Forward search text to presenter (which delegates to manager.find_entries + filter_visible)."""
        if hasattr(self._events, "on_search_text_changed"):
            self._events.on_search_text_changed(text)

    def _on_tree_current_item_changed(self, current: "QTreeWidgetItem | None", previous: "QTreeWidgetItem | None") -> None:
        """Determine whether a category or entry was selected and forward via events."""
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole) or {}
        uuid = data.get("uuid", "")
        if not uuid:
            return
        # Heuristic: top-level items are categories, children are entries
        if current.parent() is None:
            if hasattr(self._events, "on_category_selected"):
                self._events.on_category_selected(uuid)
        else:
            if hasattr(self._events, "on_entry_selected"):
                self._events.on_entry_selected(uuid)

    def _on_new_category_button_clicked(self) -> None:
        """Toolbar button 'New Category' → forward to presenter."""
        if hasattr(self._events, "on_new_category_requested"):
            self._events.on_new_category_requested()

    def _on_context_menu_requested(self, pos: "QPoint") -> None:
        """Build and show the context menu exactly as the legacy EnhancedCompendiumWindow does."""
        from PyQt5.QtCore import QPoint

        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        # The ThemeManager stylesheet is optional for MVP; skip for simplicity
        if item is not None:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            uuid = data.get("uuid", "")
            # Top-level (parentless) item → category
            if item.parent() is None:
                menu.addAction(_("New Entry"), lambda: self._request_new_entry(uuid))
                menu.addAction(_("Rename Category"), lambda: self._request_rename(uuid, "category"))
                menu.addAction(_("Delete Category"), lambda: self._request_delete(uuid, "category"))
            else:
                # Entry row
                menu.addAction(_("Rename Entry"), lambda: self._request_rename(uuid, "entry"))
                menu.addAction(_("Delete Entry"), lambda: self._request_delete(uuid, "entry"))
                # Move Up / Down (disable if at boundary)
                parent = item.parent()
                idx = parent.indexOfChild(item)
                move_up = menu.addAction(_("Move Up"), lambda: self._request_move(uuid, "up"))
                move_down = menu.addAction(_("Move Down"), lambda: self._request_move(uuid, "down"))
                if idx <= 0:
                    move_up.setEnabled(False)
                if idx >= parent.childCount() - 1:
                    move_down.setEnabled(False)
                # Move-to-Category disabled when <2 categories (mirrors legacy)
                move_cat = menu.addAction(_("Move to Category"), lambda: self._request_move_to_category(uuid))
                if self.tree.topLevelItemCount() < 2:
                    move_cat.setEnabled(False)
        else:
            # Clicked empty space → New Category only
            menu.addAction(_("New Category"), self._request_new_category)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    # --- thin forwarding helpers used by the menu actions ---
    def _request_new_category(self) -> None:
        if hasattr(self._events, "on_new_category_requested"):
            self._events.on_new_category_requested()

    def _request_new_entry(self, category_uuid: str) -> None:
        if hasattr(self._events, "on_new_entry_requested"):
            self._events.on_new_entry_requested(category_uuid)

    def _request_rename(self, uuid: str, item_type: str) -> None:
        if hasattr(self._events, "on_rename_requested"):
            self._events.on_rename_requested(uuid, item_type)

    def _request_delete(self, uuid: str, item_type: str) -> None:
        if hasattr(self._events, "on_delete_requested"):
            self._events.on_delete_requested(uuid, item_type)

    def _request_move(self, entry_uuid: str, direction: str) -> None:
        if hasattr(self._events, "on_move_requested"):
            self._events.on_move_requested(entry_uuid, direction)

    def _request_move_to_category(self, entry_uuid: str) -> None:
        # MVP scope: treat identically to the other CRUD handlers (presenter decides)
        if hasattr(self._events, "on_move_requested"):
            self._events.on_move_requested(entry_uuid, "to_category")
