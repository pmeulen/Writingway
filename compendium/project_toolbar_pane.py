"""
Project Toolbar pane for the (MVP) Enhanced Compendium window.

Per ``tasks/mvp.md`` (house rule): one module owns one pane and contains:

* ``IProjectToolbarView`` - the View contract (Presenter -> View), an ``ABC``.
* ``ProjectToolbarEvents`` - the View -> Presenter contract, a ``Protocol``.
* ``ProjectToolbarPresenter`` - PyQt-free decisions/orchestration.
* ``ProjectToolbarWidget`` - the humble Qt View (the only PyQt5 code here).

The pane is currently a skeleton: the contracts, presenter and widget are all
empty of behaviour.  Functionality (populating the project combo, switching
projects, …) will be added in later steps.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol

from PyQt5.QtWidgets import QWidget

from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    from compendium.compendium_types import CompendiumCoordinator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IProjectToolbarView (Presenter -> View)
# ---------------------------------------------------------------------------
class IProjectToolbarView(ABC):
    """Contract the ``ProjectToolbarPresenter`` relies on. No PyQt types appear here."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
        ...


# ---------------------------------------------------------------------------
# ProjectToolbarEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class ProjectToolbarEvents(Protocol):
    """What the project-toolbar view can tell its presenter. Implemented by the presenter."""

    # Intent methods (e.g. ``on_project_selected``) will be added in later steps.


# ---------------------------------------------------------------------------
# ProjectToolbarPresenter (PyQt-free)
# ---------------------------------------------------------------------------
class ProjectToolbarPresenter:
    """PyQt-free presenter for the project toolbar pane.

    Holds the (to-be-extracted) project-list model and a reference to the
    coordinating presenter for cross-pane intents.  Currently a skeleton.
    """

    def __init__(self, coordinator: CompendiumCoordinator) -> None:
        logger.debug("Initializing ProjectToolbarPresenter")
        self._coordinator = coordinator
        self._view: IProjectToolbarView | None = None

    def set_view(self, view: IProjectToolbarView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view


# ---------------------------------------------------------------------------
# ProjectToolbarWidget (the only PyQt5 code in this module)
# ---------------------------------------------------------------------------
class ProjectToolbarWidget(QWidget, IProjectToolbarView, metaclass=QtWidgetABCMeta):
    """Humble Qt View for the project toolbar pane. Currently a skeleton."""

    def __init__(self, events: ProjectToolbarEvents) -> None:
        super().__init__()
        self._events = events
        self._setup_widgets()

    def _setup_widgets(self) -> None:
        """Build the toolbar widgets. Widgets will be added in later steps."""

    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
