"""
Entry Editor pane for the (MVP) Enhanced Compendium window.

Per ``tasks/mvp.md`` (house rule): one module owns one pane and contains:

* ``IEntryEditorView`` - the View contract (Presenter -> View), an ``ABC``.
* ``EntryEditorEvents`` - the View -> Presenter contract, a ``Protocol``.
* ``EntryEditorPresenter`` - PyQt-free decisions/orchestration.
* ``EntryEditorWidget`` - the humble Qt View (the only PyQt5 code here).

The pane is currently a skeleton: the contracts, presenter and widget are all
empty of behaviour.  Functionality (loading an entry, dirty tracking,
save/revert, tags/relationships/images, …) will be added in later steps.
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
# IEntryEditorView (Presenter -> View)
# ---------------------------------------------------------------------------
class IEntryEditorView(ABC):
    """Contract the ``EntryEditorPresenter`` relies on. No PyQt types appear here."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
        ...


# ---------------------------------------------------------------------------
# EntryEditorEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class EntryEditorEvents(Protocol):
    """What the entry-editor view can tell its presenter. Implemented by the presenter."""

    # Intent methods (e.g. ``on_overview_changed``, ``on_save_requested``) will be added in later steps.


# ---------------------------------------------------------------------------
# EntryEditorPresenter (PyQt-free)
# ---------------------------------------------------------------------------
class EntryEditorPresenter:
    """PyQt-free presenter for the entry editor pane.

    Connects to the ``CompendiumManager`` model and reports cross-pane intents
    to the coordinating presenter.  Currently a skeleton.
    """

    def __init__(self, compendium: CompendiumManager, coordinator: CompendiumCoordinator) -> None:
        logger.debug("Initializing EntryEditorPresenter")
        self._compendium = compendium
        self._coordinator = coordinator
        self._view: IEntryEditorView | None = None

    def set_view(self, view: IEntryEditorView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view


# ---------------------------------------------------------------------------
# EntryEditorWidget (the only PyQt5 code in this module)
# ---------------------------------------------------------------------------
class EntryEditorWidget(QWidget, IEntryEditorView, metaclass=QtWidgetABCMeta):
    """Humble Qt View for the entry editor pane. Currently a skeleton."""

    def __init__(self, events: EntryEditorEvents) -> None:
        super().__init__()
        self._events = events
        self._setup_widgets()

    def _setup_widgets(self) -> None:
        """Build the editor widgets. Widgets will be added in later steps."""

    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
