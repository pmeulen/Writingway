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
from typing import TYPE_CHECKING, Protocol

from PyQt5.QtWidgets import QWidget

from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    from compendium.compendium_manager import CompendiumManager
    from compendium.compendium_types import CompendiumCoordinator

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


# ---------------------------------------------------------------------------
# CompendiumTreeEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class CompendiumTreeEvents(Protocol):
    """What the compendium-tree view can tell its presenter. Implemented by the presenter."""

    # Intent methods (e.g. ``on_entry_selected``) will be added in later steps.


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

    def set_view(self, view: ICompendiumTreeView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view


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
        """Build the tree widgets. Widgets will be added in later steps."""

    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
