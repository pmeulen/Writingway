"""
Unit tests for the MVP presenters used by EnhancedCompendiumWindow2.

These tests verify the coordinator and pane presenters logic without Qt.
They are pure unit tests: no filesystem I/O, no QApplication, fully synchronous.
"""
from __future__ import annotations

import logging
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from compendium.compendium_window_pane import CompendiumWindowPresenter
from compendium.project_toolbar_pane import ProjectToolbarPresenter

# ---------------------------------------------------------------------------
# Helpers to create isolated workbench.PROJECTS environment
# ---------------------------------------------------------------------------

def _install_fake_workbench(monkeypatch: pytest.MonkeyPatch, project_names: list[str]) -> None:
    """Install a fake workbench module exposing the minimal PROJECTS constant."""
    fake_workbench = ModuleType("workbench")
    fake_workbench.PROJECTS = [{"name": n} for n in project_names]
    monkeypatch.setitem(__import__("sys").modules, "workbench", fake_workbench)


# ---------------------------------------------------------------------------
# CompendiumWindowPresenter tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_compendium_window_presenter_init_no_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """When initialized with no or unknown project, presenter creates placeholder manager and resets children."""
    _install_fake_workbench(monkeypatch, ["Alpha", "Beta"])
    presenter = CompendiumWindowPresenter(None)

    assert presenter._project_name is None
    assert presenter._compendium is not None
    # Child presenters must exist
    assert presenter.toolbar_presenter is not None
    assert presenter.tree_presenter is not None
    assert presenter.editor_presenter is not None


@pytest.mark.unit
def test_compendium_window_presenter_init_known_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known project name resolves and creates a real CompendiumManager."""
    _install_fake_workbench(monkeypatch, ["Alpha", "Beta"])
    presenter = CompendiumWindowPresenter("Alpha")

    assert presenter._project_name == "Alpha"
    assert presenter._compendium is not None


@pytest.mark.unit
def test_compendium_window_presenter_switch_idempotent(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Calling switch_to_project with the same name is a no-op (early return, no log)."""
    _install_fake_workbench(monkeypatch, ["Alpha"])
    presenter = CompendiumWindowPresenter("Alpha")
    caplog.set_level(logging.INFO)

    presenter.switch_to_project("Alpha")

    # No INFO log produced on early return
    assert not any("switching to project" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_compendium_window_presenter_switch_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """switch_to_project(None) transitions to the empty state and recreates children with empty manager."""
    _install_fake_workbench(monkeypatch, ["Alpha"])
    presenter = CompendiumWindowPresenter("Alpha")

    presenter.switch_to_project(None)

    assert presenter._project_name is None
    assert presenter._compendium.project_name == ""  # type: ignore[attr-defined]


@pytest.mark.unit
def test_compendium_window_presenter_destroy_calls_children(monkeypatch: pytest.MonkeyPatch) -> None:
    """destroy() must propagate to toolbar, tree and editor presenters."""
    _install_fake_workbench(monkeypatch, [])
    presenter = CompendiumWindowPresenter(None)

    # Replace children with mocks that record destroy calls
    for child_name in ("_toolbar", "_tree", "_editor"):
        child = getattr(presenter, child_name)
        child.destroy = MagicMock()  # type: ignore[method-assign]

    presenter.destroy()

    for child_name in ("_toolbar", "_tree", "_editor"):
        getattr(presenter, child_name).destroy.assert_called_once()


# ---------------------------------------------------------------------------
# ProjectToolbarPresenter tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_project_toolbar_presenter_model_listener_registration() -> None:
    """set_workbench_projects_model registers listener and performs initial load."""
    mock_model = MagicMock()
    coordinator = MagicMock()
    presenter = ProjectToolbarPresenter(coordinator)

    presenter.set_workbench_projects_model(mock_model)

    mock_model.add_projects_changed_listener.assert_called_once()
    # Initial load must have called get_project_names
    mock_model.get_project_names.assert_called_once()


@pytest.mark.unit
def test_project_toolbar_presenter_selection_preserved_on_change() -> None:
    """_on_projects_changed keeps previously selected project when still present."""
    coordinator = MagicMock()
    presenter = ProjectToolbarPresenter(coordinator)
    mock_view = MagicMock()
    presenter.set_view(mock_view)
    presenter._last_selected_project = "Beta"

    presenter._on_projects_changed(["Alpha", "Beta", "Gamma"])

    # populate_projects must be called with preserved selection
    mock_view.populate_projects.assert_called_once_with(["Alpha", "Beta", "Gamma"], "Beta")
    assert presenter._last_selected_project == "Beta"


@pytest.mark.unit
def test_project_toolbar_presenter_destroy_unregisters_listener() -> None:
    """destroy() removes the listener and clears internal references."""
    mock_model = MagicMock()
    coordinator = MagicMock()
    presenter = ProjectToolbarPresenter(coordinator)
    presenter.set_workbench_projects_model(mock_model)

    presenter.destroy()

    mock_model.remove_projects_changed_listener.assert_called_once()
    assert presenter._workbench_projects_model is None
    assert presenter._projects_changed_listener is None


@pytest.mark.unit
def test_project_toolbar_presenter_on_project_selected_forwards_to_coordinator() -> None:
    """on_project_selected stores selection and forwards to coordinator.on_project_selected."""
    coordinator = MagicMock()
    presenter = ProjectToolbarPresenter(coordinator)

    presenter.on_project_selected("Gamma")

    assert presenter._last_selected_project == "Gamma"
    coordinator.on_project_selected.assert_called_once_with("Gamma")


@pytest.mark.unit
def test_switch_to_project_passes_live_manager_to_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """After switching projects the live CompendiumManager must be handed to the tree presenter (regression for empty-tree bug)."""
    _install_fake_workbench(monkeypatch, ["X", "N2"])

    presenter = CompendiumWindowPresenter("X")
    # Replace the tree child with a spy so we can assert the call signature
    tree_spy = MagicMock()
    presenter._tree = tree_spy  # type: ignore[assignment]

    # Cause a switch – the freshly created manager must travel with the reset call
    presenter.switch_to_project("N2")

    tree_spy.reset_for_project.assert_called_once()
    args, kwargs = tree_spy.reset_for_project.call_args
    assert args[0] == "N2"
    assert "compendium" in kwargs
    # The passed manager object must be exactly the one now owned by the coordinator
    assert kwargs["compendium"] is presenter._compendium
