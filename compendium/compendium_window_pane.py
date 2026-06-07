"""
Composing pane (window) for the (MVP) Enhanced Compendium window.

The Enhanced Compendium window decomposes into three panes: project toolbar,
compendium tree, and entry editor. This module owns the *composition*:

* `Pane` - domain enum used by the composition contract (no Qt types).
* `ICompendiumWindowView` - the composition View contract (show/hide/switch).
* `CompendiumWindowWidget` - the composing Qt View; lays out the three child
  Views and implements `ICompendiumWindowView` (the only PyQt5 code here).
* `CompendiumWindowPresenter` - the coordinating presenter; owns the three
  child presenters, holds the composition View, and implements the
  `CompendiumCoordinator` cross-pane contract.
"""
from __future__ import annotations

import enum
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget

from compendium.compendium_manager import CompendiumEventBus, CompendiumManager
from compendium.compendium_tree_pane import CompendiumTreePresenter, CompendiumTreeWidget
from compendium.entry_editor_pane import EntryEditorPresenter, EntryEditorWidget
from compendium.project_toolbar_pane import ProjectToolbarPresenter, ProjectToolbarWidget
from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pane (domain enum, no Qt types)
# ---------------------------------------------------------------------------
class Pane(enum.Enum):
    TOOLBAR = enum.auto()
    TREE = enum.auto()
    EDITOR = enum.auto()


# ---------------------------------------------------------------------------
# ICompendiumWindowView (composition contract: Presenter -> View)
# ---------------------------------------------------------------------------
class ICompendiumWindowView(ABC):
    """Composition contract: show/hide/switch panes. No PyQt types appear here."""

    @abstractmethod
    def show_pane(self, pane: Pane, visible: bool) -> None: ...

    @abstractmethod
    def set_pane_enabled(self, pane: Pane, enabled: bool) -> None: ...


# ---------------------------------------------------------------------------
# CompendiumWindowPresenter (coordinating presenter, PyQt-free)
# ---------------------------------------------------------------------------
class CompendiumWindowPresenter:
    """Coordinating presenter for the Enhanced Compendium window.

    Owns the three child presenters and mediates *cross-pane* events only.  It
    also holds the composition ``ICompendiumWindowView`` it drives.  Implements
    the ``CompendiumCoordinator`` Protocol (see ``compendium_types``).  Currently
    a skeleton: cross-pane behaviour will be added in later steps.
    """

    def __init__(self, project_name: str | None) -> None:
        logger.debug(f"Initializing CompendiumWindowPresenter for project: {project_name}")
        self._project_name: str | None = None
        self._event_bus = CompendiumEventBus.get_instance()

        # Resolve project name: treat missing / non-existent names as None
        resolved_name: str | None = None
        if project_name:
            try:
                from workbench import PROJECTS
                names = [p.get("name", "") for p in PROJECTS if isinstance(p, dict)]
                if project_name in names:
                    resolved_name = project_name
            except Exception:
                # If workbench import fails we conservatively treat the supplied name as invalid
                resolved_name = None

        self._project_name = resolved_name
        if self._project_name is None:
            # Create a lightweight placeholder manager that will be replaced on first switch
            # We still need a valid object for the child presenters; using an empty name keeps it safe.
            self._compendium = CompendiumManager("", event_bus=self._event_bus)
        else:
            self._compendium = CompendiumManager(self._project_name, event_bus=self._event_bus)

        self._window_view: ICompendiumWindowView | None = None
        # The coordinator owns the three child presenters and is their coordinator.
        self._toolbar = ProjectToolbarPresenter(coordinator=self)
        self._tree = CompendiumTreePresenter(self._compendium, coordinator=self)
        self._editor = EntryEditorPresenter(self._compendium, coordinator=self)

        if self._project_name is None:
            # Drive toolbar, tree and editor into the required no-project placeholder states
            self._toolbar.load_projects([], None)
            # The child presenters expose reset_for_project; passing "" signals the empty state
            self._tree.reset_for_project("")
            self._editor.reset_for_project("")

    @property
    def toolbar_presenter(self) -> ProjectToolbarPresenter:
        return self._toolbar

    @property
    def tree_presenter(self) -> CompendiumTreePresenter:
        return self._tree

    @property
    def editor_presenter(self) -> EntryEditorPresenter:
        return self._editor

    def set_window_view(self, window_view: ICompendiumWindowView) -> None:
        """Give the coordinator the composition View it drives."""
        self._window_view = window_view

    # --- CompendiumCoordinator implementation -----------------------------
    def on_project_selected(self, project_name: str) -> None:
        """Handle a project switch from the toolbar."""
        self.switch_to_project(project_name)

    def switch_to_project(self, project_name: str | None) -> None:
        """Single public entry point for switching the active project.

        Idempotent: if the project is unchanged, the call returns early.
        Recreates the CompendiumManager and notifies child presenters.
        Accepts None to represent the "no project" state.
        """
        if project_name == self._project_name:
            return
        logger.info(f"CompendiumWindowPresenter switching to project: {project_name}")
        self._project_name = project_name
        if project_name is None:
            # Transition into the no-project empty state
            self._compendium = CompendiumManager("", event_bus=self._event_bus)
            self._toolbar.load_projects([], None)
            self._tree.reset_for_project("", compendium=self._compendium)
            self._editor.reset_for_project("")
        else:
            self._compendium = CompendiumManager(self._project_name, event_bus=self._event_bus)
            # Propagate change to children – pass the live manager so the tree can load real data
            self._toolbar.reset_for_project(self._project_name)
            self._tree.reset_for_project(self._project_name, compendium=self._compendium)
            self._editor.reset_for_project(self._project_name)
            if self._window_view is not None:
                self._window_view.set_pane_enabled(Pane.EDITOR, False)

    def on_entry_selected(self, entry_uuid: str) -> None:
        """Handle an entry selection from the tree. Skeleton."""

    def on_entry_structure_changed(self) -> None:
        """Handle add/delete/rename/move of categories or entries. Skeleton."""

    def destroy(self) -> None:
        """Explicit cleanup: propagate destroy() to child presenters (toolbar, tree, editor)."""
        for child in (self._toolbar, self._tree, self._editor):
            if hasattr(child, "destroy"):
                try:
                    child.destroy()
                except Exception:
                    logger.warning(f"destroy() on child presenter {type(child).__name__} raised an exception", exc_info=True)
        logger.debug("CompendiumWindowPresenter.destroy completed")


# ---------------------------------------------------------------------------
# CompendiumWindowWidget (composing Qt View; the only PyQt5 code in this module)
# ---------------------------------------------------------------------------
class CompendiumWindowWidget(QWidget, ICompendiumWindowView, metaclass=QtWidgetABCMeta):
    """Composing Qt View: lays out the three child Views in a splitter.

    It owns a thin composition interface (show/hide/switch) but contains no
    per-pane field logic.
    """

    def __init__(self, presenter: CompendiumWindowPresenter) -> None:
        super().__init__()
        self._presenter = presenter

        # Build the three child Views, wiring each to its presenter (events).
        self._toolbar_view = ProjectToolbarWidget(events=presenter.toolbar_presenter)
        self._tree_view = CompendiumTreeWidget(events=presenter.tree_presenter)
        self._editor_view = EntryEditorWidget(events=presenter.editor_presenter)

        # Let each child presenter learn its IView.
        presenter.toolbar_presenter.set_view(self._toolbar_view)
        presenter.tree_presenter.set_view(self._tree_view)
        presenter.editor_presenter.set_view(self._editor_view)

        self._pane_widgets: dict[Pane, QWidget] = {
            Pane.TOOLBAR: self._toolbar_view,
            Pane.TREE: self._tree_view,
            Pane.EDITOR: self._editor_view,
        }

        self._setup_widgets()

    def _setup_widgets(self) -> None:
        """Lay out the toolbar above a splitter holding the tree and editor."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The toolbar must not stretch vertically
        layout.addWidget(self._toolbar_view, 0)

        self._splitter = QSplitter()
        self._splitter.addWidget(self._tree_view)
        self._splitter.addWidget(self._editor_view)
        layout.addWidget(self._splitter, 1)

    # --- ICompendiumWindowView implementation -----------------------------
    def show_pane(self, pane: Pane, visible: bool) -> None:
        self._pane_widgets[pane].setVisible(visible)

    def set_pane_enabled(self, pane: Pane, enabled: bool) -> None:
        self._pane_widgets[pane].setEnabled(enabled)
