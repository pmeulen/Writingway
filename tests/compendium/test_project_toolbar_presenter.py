"""
Unit tests for ProjectToolbarPresenter MVP integration with WorkbenchProjectsModel.

Marked `@pytest.mark.unit` because tests exercise only pure presenter logic
with mocks (no filesystem, no Qt widgets).
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from compendium.project_toolbar_pane import IProjectToolbarView, ProjectToolbarPresenter


class _FakeCoordinator:
    """Minimal stand-in satisfying the ``CompendiumCoordinator`` Protocol."""

    def on_project_selected(self, project_name: str) -> None: ...
    def on_entry_selected(self, entry_uuid: str) -> None: ...
    def on_entry_structure_changed(self) -> None: ...


class _FakeWorkbenchProjectsModel:
    """In-memory stand-in for WorkbenchProjectsModel used by the presenter tests."""

    def __init__(self, initial_names: list[str] | None = None) -> None:
        self._names: list[str] = initial_names or []
        self._listeners: list = []

    def get_project_names(self) -> list[str]:
        return list(self._names)

    def add_projects_changed_listener(self, listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_projects_changed_listener(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def simulate_change(self, new_names: list[str]) -> None:
        """Helper for tests: notify all listeners about a project list change."""
        self._names = list(new_names)
        for listener in list(self._listeners):
            listener(new_names)


@pytest.mark.unit
def test_set_workbench_projects_model_loads_initial_list() -> None:
    """Presenter loads project names via model on injection."""
    view = Mock(spec=IProjectToolbarView)
    coordinator = _FakeCoordinator()
    presenter = ProjectToolbarPresenter(coordinator)
    presenter.set_view(view)

    model = _FakeWorkbenchProjectsModel(["Alpha", "Beta"])
    presenter.set_workbench_projects_model(model)

    view.populate_projects.assert_called_once_with(["Alpha", "Beta"], "Alpha")


@pytest.mark.unit
def test_projects_changed_preserves_existing_selection() -> None:
    """When model notifies of changes, previously selected project is kept if still present."""
    view = Mock(spec=IProjectToolbarView)
    coordinator = _FakeCoordinator()
    presenter = ProjectToolbarPresenter(coordinator)
    presenter.set_view(view)

    model = _FakeWorkbenchProjectsModel(["Alpha", "Beta"])
    presenter.set_workbench_projects_model(model)
    view.reset_mock()

    # Simulate the user selecting "Beta"
    presenter.on_project_selected("Beta")

    # Model changes – "Beta" still exists ⇒ must keep selection
    model.simulate_change(["Alpha", "Beta", "Gamma"])
    view.populate_projects.assert_called_once_with(["Alpha", "Beta", "Gamma"], "Beta")


@pytest.mark.unit
def test_projects_changed_falls_back_to_first_when_selection_gone() -> None:
    """When current selection disappears, presenter falls back to first project in list."""
    view = Mock(spec=IProjectToolbarView)
    coordinator = _FakeCoordinator()
    presenter = ProjectToolbarPresenter(coordinator)
    presenter.set_view(view)

    model = _FakeWorkbenchProjectsModel(["Alpha", "Beta"])
    presenter.set_workbench_projects_model(model)
    presenter.on_project_selected("Beta")
    view.reset_mock()

    model.simulate_change(["Gamma", "Delta"])
    view.populate_projects.assert_called_once_with(["Gamma", "Delta"], "Gamma")


@pytest.mark.unit
def test_destroy_removes_listener() -> None:
    """destroy() unregisters the listener to prevent memory leaks."""
    coordinator = _FakeCoordinator()
    presenter = ProjectToolbarPresenter(coordinator)

    model = _FakeWorkbenchProjectsModel(["One"])
    presenter.set_workbench_projects_model(model)

    # After destroy the listener should be gone
    presenter.destroy()
    assert len(model._listeners) == 0
