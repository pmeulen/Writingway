"""
Unit, Qt and integration tests for the MVP compendium tree pane.

Tests are added incrementally per the delivery plan; every slice must pass
before the next behaviour is implemented.
"""
from __future__ import annotations

import pytest

from compendium.compendium_tree_pane import CompendiumTreePresenter, CompendiumTreeWidget


class _FakeCoordinator:
    """Minimal stand-in satisfying the ``CompendiumCoordinator`` Protocol."""

    def on_project_selected(self, project_name: str) -> None: ...
    def on_entry_selected(self, entry_uuid: str) -> None: ...
    def on_entry_structure_changed(self) -> None: ...
    def on_category_selected(self, category_uuid: str) -> None: ...
    def on_new_category_requested(self) -> None: ...
    def on_new_entry_requested(self, category_uuid: str) -> None: ...
    def on_rename_requested(self, uuid: str, item_type: str) -> None: ...
    def on_delete_requested(self, uuid: str, item_type: str) -> None: ...
    def on_move_requested(self, entry_uuid: str, direction: str) -> None: ...


@pytest.mark.unit
def test_compendium_tree_presenter_reset_for_project() -> None:
    """reset_for_project records the project name and calls view.populate_tree (stage-2)."""
    from unittest.mock import MagicMock

    # Provide a fake manager with load_data so the presenter can call it (stage-2 contract)
    fake_manager = MagicMock()
    fake_manager.load_data.return_value = {"version": 3, "categories": []}

    presenter = CompendiumTreePresenter(fake_manager, coordinator=_FakeCoordinator())

    # No view attached yet → still records the name
    presenter.reset_for_project("Alpha")
    assert presenter._project_name == "Alpha"

    # Attach a mock view and verify populate_tree call
    mock_view = MagicMock()
    presenter.set_view(mock_view)
    presenter.reset_for_project("Beta")

    assert presenter._project_name == "Beta"
    fake_manager.load_data.assert_called()
    mock_view.populate_tree.assert_called_once()


@pytest.mark.qt
def test_tree_widget_populate_renders_categories_and_entries(qtbot) -> None:
    """populate_tree creates one top-level item per category and stores UserRole data correctly."""
    from compendium.compendium_types import CompendiumData

    widget = CompendiumTreeWidget(events=_FakeCoordinator())  # type: ignore[arg-type]
    qtbot.addWidget(widget)

    sample: CompendiumData = {
        "version": 3,
        "categories": [
            {
                "uuid": "c1",
                "name": "Characters",
                "entries": [
                    {"uuid": "e1", "name": "Alice", "content": "", "details": "", "tags": [], "relationships": [], "images": []},
                    {"uuid": "e2", "name": "Bob", "content": "", "details": "", "tags": [], "relationships": [], "images": []},
                ],
            },
            {
                "uuid": "c2",
                "name": "Locations",
                "entries": [],
            },
        ],
    }

    widget.populate_tree(sample)

    # Two top-level (category) items
    assert widget.tree.topLevelItemCount() == 2
    from PyQt5.QtCore import Qt

    # First category stores its dict via UserRole
    cat0 = widget.tree.topLevelItem(0)
    assert cat0 is not None
    stored_cat = cat0.data(0, Qt.ItemDataRole.UserRole)
    assert stored_cat["name"] == "Characters"
    # Two child entries under Characters
    assert cat0.childCount() == 2
    first_entry = cat0.child(0)
    assert first_entry.data(0, Qt.ItemDataRole.UserRole)["name"] == "Alice"


@pytest.mark.qt
def test_tree_search_filters_entries(qtbot) -> None:
    """Typing search text ultimately ends up calling filter_visible on the widget and only matching UUIDs stay visible."""
    from compendium.compendium_types import CompendiumData

    widget = CompendiumTreeWidget(events=_FakeCoordinator())  # type: ignore[arg-type]
    qtbot.addWidget(widget)

    sample: CompendiumData = {
        "version": 3,
        "categories": [
            {
                "uuid": "c1",
                "name": "Characters",
                "entries": [
                    {"uuid": "e1", "name": "Alice", "content": "", "details": "", "tags": [], "relationships": [], "images": []},
                    {"uuid": "e2", "name": "Bob", "content": "", "details": "", "tags": [], "relationships": [], "images": []},
                ],
            }
        ],
    }

    widget.populate_tree(sample)

    cat0 = widget.tree.topLevelItem(0)
    assert cat0.child(0).isHidden() is False
    assert cat0.child(1).isHidden() is False

    # Simulate the result of manager.find_entries("Alice") → only e1 stays visible
    widget.filter_visible({"e1"})

    assert cat0.child(0).isHidden() is False
    assert cat0.child(1).isHidden() is True

    # Empty set (no search) → show everything again
    widget.filter_visible(set())
    assert cat0.child(0).isHidden() is False
    assert cat0.child(1).isHidden() is False


@pytest.mark.unit
def test_reset_for_project_accepts_live_manager() -> None:
    """reset_for_project can be given a fresh manager so the tree is populated from the live project data (regression for project-switch bug)."""
    from unittest.mock import MagicMock

    stale = MagicMock()
    stale.load_data.return_value = {"version": 3, "categories": []}

    fresh_manager = MagicMock()
    fresh_manager.load_data.return_value = {
        "version": 3,
        "categories": [
            {"uuid": "c1", "name": "Characters", "entries": [{"uuid": "e1", "name": "Alice", "content": "", "details": "", "tags": [], "relationships": [], "images": []}]}
        ],
    }

    presenter = CompendiumTreePresenter(stale, coordinator=_FakeCoordinator())
    mock_view = MagicMock()
    presenter.set_view(mock_view)

    # Supply the live manager; it must be used for load_data and populate_tree.
    presenter.reset_for_project("X", compendium=fresh_manager)

    assert presenter._compendium is fresh_manager
    fresh_manager.load_data.assert_called_once()
    mock_view.populate_tree.assert_called_once()
    # The data passed to populate_tree contains the Characters category.
    passed = mock_view.populate_tree.call_args[0][0]
    assert passed["categories"][0]["name"] == "Characters"


@pytest.mark.qt
def test_tree_selection_emits_entry_and_category_events(qtbot) -> None:
    """Selecting an entry or category forwards the UUID through the coordinator via the events protocol."""
    from compendium.compendium_types import CompendiumData
    from unittest.mock import MagicMock

    coordinator_spy = MagicMock(spec=_FakeCoordinator)
    widget = CompendiumTreeWidget(events=coordinator_spy)  # type: ignore[arg-type]
    qtbot.addWidget(widget)

    sample: CompendiumData = {
        "version": 3,
        "categories": [
            {
                "uuid": "c1",
                "name": "Characters",
                "entries": [
                    {"uuid": "e1", "name": "Alice", "content": "", "details": "", "tags": [], "relationships": [], "images": []},
                ],
            }
        ],
    }

    widget.populate_tree(sample)

    # Select the entry programmatically
    cat_item = widget.tree.topLevelItem(0)
    entry_item = cat_item.child(0)
    widget.tree.setCurrentItem(entry_item)

    coordinator_spy.on_entry_selected.assert_called_once_with("e1")

    # Select the category itself
    widget.tree.setCurrentItem(cat_item)
    coordinator_spy.on_category_selected.assert_called_once_with("c1")


@pytest.mark.integration
def test_context_menu_new_category_adds_to_manager(compendium_manager, qtbot) -> None:
    """Verify that calling manager.add_category followed by a presenter refresh updates the widget tree."""
    coordinator = _FakeCoordinator()
    presenter = CompendiumTreePresenter(compendium_manager, coordinator=coordinator)
    widget = CompendiumTreeWidget(events=presenter)  # type: ignore[arg-type]
    qtbot.addWidget(widget)
    presenter.set_view(widget)

    presenter.reset_for_project("TestProject")
    initial_count = widget.tree.topLevelItemCount()

    # This simulates the eventual action of the context-menu flow (manager mutation + tree refresh)
    compendium_manager.add_category("TestCat")
    presenter.reset_for_project("TestProject")

    assert widget.tree.topLevelItemCount() == initial_count + 1


@pytest.mark.integration
def test_open_with_entry_triggers_tree_reset_for_project(compendium_manager, qtbot) -> None:
    """Calling open_with_entry on EnhancedCompendiumWindow2 must end up calling reset_for_project on its tree presenter."""
    from PyQt5.QtWidgets import QWidget

    # A real QWidget satisfies both the relaxed isinstance guard and Qt's parent type requirement.
    class _StubWB(QWidget):
        def open_project(self, *_a, **_kw): ...

    # Temporarily replace the name that EnhancedCompendiumWindow2 imports
    import workbench as wb
    orig = wb.WorkbenchWindow
    wb.WorkbenchWindow = _StubWB  # type: ignore[attr-defined]

    try:
        from compendium.enhanced_compendium2 import EnhancedCompendiumWindow2
        dummy_parent = _StubWB()
        win = EnhancedCompendiumWindow2(dummy_parent)  # type: ignore[arg-type]
        qtbot.addWidget(win)

        tree_presenter = win.presenter.tree_presenter
        # Before the call, project_name must be None (the window was created without a selected project)
        assert tree_presenter._project_name is None

        # Execute the method under test – it must bubble down to the tree pane
        win.open_with_entry("ProjectX", None)

        # The tree presenter must now know about the switched-to project
        assert tree_presenter._project_name == "ProjectX"
        # Because the live manager was supplied, the tree view now contains whatever
        # the seeded compendium_manager holds (possibly no categories).
        assert tree_presenter._view is not None
    finally:
        wb.WorkbenchWindow = orig
