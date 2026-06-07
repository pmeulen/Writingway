"""
Composing pane (window) for the (MVP) Enhanced Compendium window.

Per ``tasks/mvp.md`` §6, the Enhanced Compendium window decomposes into three
panes (project toolbar, compendium tree, entry editor).  This module owns the
*composition*:

* ``Pane`` - domain enum used by the composition contract (no Qt types).
* ``ICompendiumWindowView`` - the composition View contract (show/hide/switch).
* ``CompendiumWindowWidget`` - the composing Qt View; lays out the three child
  Views and implements ``ICompendiumWindowView`` (the only PyQt5 code here).
* ``CompendiumWindowPresenter`` - the coordinating presenter; owns the three
  child presenters, holds the composition View, and implements the
  ``CompendiumCoordinator`` cross-pane contract.

The composition is currently a skeleton: child panes are empty and the
coordinator only wires the pieces together.  Behaviour will be added in later
steps.
"""
from __future__ import annotations

import enum
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget

from compendium.compendium_tree_pane import CompendiumTreePresenter, CompendiumTreeWidget
from compendium.entry_editor_pane import EntryEditorPresenter, EntryEditorWidget
from compendium.project_toolbar_pane import ProjectToolbarPresenter, ProjectToolbarWidget
from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    from compendium.compendium_manager import CompendiumManager

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

    def __init__(self, compendium: CompendiumManager) -> None:
        logger.debug("Initializing CompendiumWindowPresenter")
        self._compendium = compendium
        self._window_view: ICompendiumWindowView | None = None
        # The coordinator owns the three child presenters and is their coordinator.
        self._toolbar = ProjectToolbarPresenter(coordinator=self)
        self._tree = CompendiumTreePresenter(compendium, coordinator=self)
        self._editor = EntryEditorPresenter(compendium, coordinator=self)

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
    # (cross-pane intents; behaviour will be added in later steps)
    def on_project_selected(self, project_name: str) -> None:
        """Handle a project switch from the toolbar. Skeleton."""

    def on_entry_selected(self, entry_uuid: str) -> None:
        """Handle an entry selection from the tree. Skeleton."""

    def on_entry_structure_changed(self) -> None:
        """Handle add/delete/rename/move of categories or entries. Skeleton."""


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
