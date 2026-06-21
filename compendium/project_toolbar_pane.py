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
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING, Protocol

from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from compendium.qt_mvp import QtWidgetABCMeta
from settings.theme_manager import ThemeManager

if TYPE_CHECKING:
    from compendium.compendium_types import CompendiumCoordinator
    from workbench import WorkbenchProjectsModel

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

    @abstractmethod
    def populate_projects(self, projects: list[str], current_project: str | None) -> None:
        """Replace combo contents with the given project list and optionally pre-select current_project."""
        ...


# ---------------------------------------------------------------------------
# ProjectToolbarEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class ProjectToolbarEvents(Protocol):
    """What the project-toolbar view can tell its presenter. Implemented by the presenter."""

    def on_project_selected(self, project_name: str) -> None:
        """User selected a different project in the combo box."""
        ...


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
        self._workbench_projects_model: WorkbenchProjectsModel | None = None
        self._projects_changed_listener: Callable[[list[str]], None] | None = None
        self._last_selected_project: str | None = None
        self._current_projects: list[str] = []

    def set_view(self, view: IProjectToolbarView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view

    def on_project_selected(self, project_name: str) -> None:
        """Handle project selection from the view and forward to coordinator."""
        logger.info(f"ProjectToolbarPresenter received project selection: {project_name}")
        self._last_selected_project = project_name
        self._coordinator.on_project_selected(project_name)

    def reset_for_project(self, project_name: str) -> None:
        """Update the current project selection in the toolbar view (if known)."""
        logger.info(f"ProjectToolbarPresenter reset_for_project: {project_name}")
        if project_name in self._current_projects:
            self._last_selected_project = project_name
            if self._view is not None:
                self._view.populate_projects(self._current_projects, project_name)
        else:
            logger.warning(f"reset_for_project called with unknown project: {project_name}")

    def load_projects(self, projects: list[str], current_project: str | None = None) -> None:
        """Load project list into the view (called by window or parent)."""
        if self._view is not None:
            self._view.populate_projects(projects, current_project)

    def set_workbench_projects_model(self, model: WorkbenchProjectsModel) -> None:
        """Inject the workbench projects model, register listener and perform initial load."""
        logger.debug("ProjectToolbarPresenter.set_workbench_projects_model called")
        # Unregister previous listener if any
        if self._workbench_projects_model is not None and self._projects_changed_listener is not None:
            self._workbench_projects_model.remove_projects_changed_listener(self._projects_changed_listener)

        self._workbench_projects_model = model
        self._projects_changed_listener = self._on_projects_changed
        model.add_projects_changed_listener(self._projects_changed_listener)

        # Initial load
        names = model.get_project_names()
        self._on_projects_changed(names)

    def _on_projects_changed(self, new_names: list[str]) -> None:
        """Handle project list change notification from the model; preserve selection when possible."""
        self._current_projects = list(new_names)

        # Preserve the last known good selection when possible
        preserved = None
        if self._last_selected_project and self._last_selected_project in new_names:
            preserved = self._last_selected_project
        elif new_names:
            preserved = new_names[0]

        if self._view is not None:
            self._view.populate_projects(new_names, preserved)

        # Remember what we selected for future change events
        self._last_selected_project = preserved

    def destroy(self) -> None:
        """Explicit cleanup: unregister listener to prevent memory leaks."""
        if self._workbench_projects_model is not None and self._projects_changed_listener is not None:
            self._workbench_projects_model.remove_projects_changed_listener(self._projects_changed_listener)
            self._projects_changed_listener = None
            self._workbench_projects_model = None
        logger.debug("ProjectToolbarPresenter.destroy completed")


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
        """Build the toolbar widgets. Ported from EnhancedCompendiumWindow."""
        # Note: Since this is now a QWidget pane, we use a layout instead
        # of being a QMainWindow toolBar.
        self.setStyleSheet(ThemeManager.get_menu_stylesheet())

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(10)

        # Fix vertical size to the minimum required by the combo box
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.label = QLabel(_("<b>Project:</b>"))
        self.main_layout.addWidget(self.label)

        self.project_combo = QComboBox()
        self.project_combo.currentTextChanged.connect(self._on_project_combo_changed)
        self.main_layout.addWidget(self.project_combo)

        # Spacer to push everything to the left
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.main_layout.addWidget(self.spacer)

    def _on_project_combo_changed(self, project_name: str) -> None:
        """Forward combo selection to the presenter via the events protocol."""
        if project_name:
            self._events.on_project_selected(project_name)

    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
        self.project_combo.clear()

    def populate_projects(self, projects: list[str], current_project: str | None) -> None:
        """Replace combo contents and optionally pre-select the current project."""
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems(projects)
        if current_project and current_project in projects:
            self.project_combo.setCurrentText(current_project)
        elif projects:
            self.project_combo.setCurrentIndex(0)
        self.project_combo.blockSignals(False)
