"""
Skeleton tests for the MVP scaffolding of the Enhanced Compendium window
(``enhanced_compendium2``).

At this stage the four presenters are empty skeletons; these tests only assert
that each presenter can be instantiated.  They are GUI-free: the presenters are
PyQt-free, so no ``qtbot``/``QApplication`` is required.

Behaviour-level tests will be added as functionality is filled in step by step.
"""
from __future__ import annotations

from compendium.compendium_tree_pane import CompendiumTreePresenter
from compendium.compendium_window_pane import CompendiumWindowPresenter
from compendium.entry_editor_pane import EntryEditorPresenter
from compendium.project_toolbar_pane import ProjectToolbarPresenter


class _FakeCoordinator:
    """Minimal stand-in satisfying the ``CompendiumCoordinator`` Protocol."""

    def on_project_selected(self, project_name: str) -> None: ...
    def on_entry_selected(self, entry_uuid: str) -> None: ...
    def on_entry_structure_changed(self) -> None: ...


def test_project_toolbar_presenter_instantiates() -> None:
    presenter = ProjectToolbarPresenter(coordinator=_FakeCoordinator())
    assert isinstance(presenter, ProjectToolbarPresenter)


def test_compendium_tree_presenter_instantiates(compendium_manager) -> None:
    presenter = CompendiumTreePresenter(compendium_manager, coordinator=_FakeCoordinator())
    assert isinstance(presenter, CompendiumTreePresenter)


def test_entry_editor_presenter_instantiates(compendium_manager) -> None:
    presenter = EntryEditorPresenter(compendium_manager, coordinator=_FakeCoordinator())
    assert isinstance(presenter, EntryEditorPresenter)


def test_compendium_window_presenter_instantiates(compendium_manager) -> None:
    presenter = CompendiumWindowPresenter(compendium_manager)
    assert isinstance(presenter, CompendiumWindowPresenter)
    # The coordinator owns its three child presenters.
    assert isinstance(presenter.toolbar_presenter, ProjectToolbarPresenter)
    assert isinstance(presenter.tree_presenter, CompendiumTreePresenter)
    assert isinstance(presenter.editor_presenter, EntryEditorPresenter)
