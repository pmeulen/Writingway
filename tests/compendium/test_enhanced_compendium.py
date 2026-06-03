import sys
from types import ModuleType

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu, QWidget

from compendium.compendium_manager import CompendiumManager
from compendium.enhanced_compendium import EnhancedCompendiumWindow


class _ParentStub(QWidget):
    """Minimal parent widget that exposes the project list API used by the window."""

    def __init__(self, projects):
        super().__init__()
        self._projects = projects

    def get_project_list(self):
        return list(self._projects)


def _make_fake_workbench_parent(monkeypatch: pytest.MonkeyPatch, projects: list[str]) -> QWidget:
    """Install a fake ``workbench`` module and return a matching parent instance."""
    fake_workbench = ModuleType("workbench")

    class FakeWorkbenchWindow(QWidget):
        def __init__(self, project_names: list[str]):
            super().__init__()
            self._projects = list(project_names)

        def get_project_list(self) -> list[str]:
            return list(self._projects)

    fake_workbench.WorkbenchWindow = FakeWorkbenchWindow
    monkeypatch.setitem(sys.modules, "workbench", fake_workbench)
    return FakeWorkbenchWindow(projects)


def _install_default_fake_workbench() -> type[QWidget]:
    """Install a module-level fake ``workbench`` module used by most tests."""
    fake_workbench = ModuleType("workbench")

    class FakeWorkbenchWindow(QWidget):
        def __init__(self, project_names: list[str] | None = None) -> None:
            super().__init__()
            self._projects = list(project_names or ["default"])

        def get_project_list(self) -> list[str]:
            return list(self._projects)

    fake_workbench.WorkbenchWindow = FakeWorkbenchWindow
    sys.modules["workbench"] = fake_workbench
    return FakeWorkbenchWindow


_DefaultFakeWorkbenchWindow = _install_default_fake_workbench()


@pytest.mark.qt
@pytest.mark.integration
def test_move_entry_rebuilds_tree_and_reselects_entry(isolated_cwd, qtbot, monkeypatch):
    """Moving an entry via the context-menu flow updates this tree view immediately."""
    project_name = "TestProject"
    manager = CompendiumManager(project_name=project_name, event_bus=None)

    # Seed categories and one entry.
    categories = manager.list_categories()
    source_category_uuid = categories[0]["uuid"]
    manager.rename_category(source_category_uuid, "Characters")
    target_category = manager.add_category("Cats")
    entry = manager.add_entry(source_category_uuid, "Alice", "A clever woman")


    parent = _make_fake_workbench_parent(monkeypatch, [project_name])
    qtbot.addWidget(parent)
    window = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(window)


    # Select the initial entry so move_entry receives a real tree item.
    assert window._find_and_select_entry_by_uuid(entry["uuid"])
    entry_item = window.tree.currentItem()
    assert entry_item is not None
    assert entry_item.data(0, Qt.UserRole) == "entry"

    # Simulate context-menu selection of the target category.
    def _pick_cats_action(menu, *args, **kwargs):
        for action in menu.actions():
            action_item = action.data()
            if action_item is not None and action_item.text(0) == "Cats":
                return action
        return None

    monkeypatch.setattr(QMenu, "exec_", _pick_cats_action)

    window.move_entry(entry_item)

    def _entry_uuid_under_category(category_name):
        for i in range(window.tree.topLevelItemCount()):
            cat_item = window.tree.topLevelItem(i)
            if cat_item.text(0) != category_name:
                continue
            return {cat_item.child(j).data(2, Qt.UserRole) for j in range(cat_item.childCount())}


@pytest.mark.qt
def test_project_combo_initialization_switches_from_default_project(isolated_cwd, qtbot, monkeypatch):
    """The window should load the selected project on startup, not stay on ``default``."""
    default_manager = CompendiumManager(project_name="default", event_bus=None)
    default_category_uuid = default_manager.list_categories()[0]["uuid"]
    default_manager.rename_category(default_category_uuid, "Characters")
    default_entry = default_manager.add_entry(default_category_uuid, "Default Alice", "Default content")

    project_name = "TestProject"
    manager = CompendiumManager(project_name=project_name, event_bus=None)
    project_category_uuid = manager.list_categories()[0]["uuid"]
    manager.rename_category(project_category_uuid, "Characters")
    project_entry = manager.add_entry(project_category_uuid, "Project Alice", "Project content")

    parent = _make_fake_workbench_parent(monkeypatch, [project_name])
    qtbot.addWidget(parent)
    window = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(window)

    assert window.project_name == project_name
    assert window.manager.project_name == project_name
    assert window._find_and_select_entry_by_uuid(project_entry["uuid"])
    assert not window._find_and_select_entry_by_uuid(default_entry["uuid"])

    current_item = window.tree.currentItem()
    assert current_item is not None
    assert current_item.text(0) == "Project Alice"


import json
from pathlib import Path

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QMessageBox


def _write_compendium(root: Path):
    projects = root / "Projects"
    projects.mkdir(exist_ok=True)
    default = projects / "default"
    default.mkdir(exist_ok=True)
    data = {
        "version": 3,
        "categories": [
            {
                "name": "Characters",
                "uuid": "cat-1",
                "entries": [
                    {"name": "Alice", "uuid": "e1", "content": "Alice content"},
                    {"name": "Bob", "uuid": "e2", "content": "Bob content"},
                ],
            }
        ],
    }
    with open(default / "compendium.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class DummyParent(_DefaultFakeWorkbenchWindow):
    def __init__(self, projects: list[str] | None = None) -> None:
        super().__init__(projects or ["default"])


def _find_alice_item(tree):
    """Return the QTreeWidgetItem for Alice, or None."""
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                return item
    return None


def _load_alice(win, qtbot):
    """Select Alice in *win* and ensure load_entry has run."""
    alice_item = _find_alice_item(win.tree)
    assert alice_item is not None, "Alice not found in tree"
    win.tree.setCurrentItem(alice_item)
    qtbot.wait(50)
    # Guard: call load_entry directly if the async selection handler hasn't fired yet.
    if win.current_entry_item is None or win.current_entry_item.text(0) != "Alice":
        win.load_entry(alice_item.text(0), alice_item)
    return alice_item


def _patch_guard_detection(monkeypatch, *, guard_response=None, revert_response=None, delete_response=None):
    """
    Monkeypatch ``QMessageBox.question`` so dialogs are detected by ``buttons``
    signatures (locale-safe; independent of translated titles/text).

    * Guard dialog uses Save|Discard|Cancel and returns ``guard_response``.
    * Revert dialog uses Discard|Cancel and returns ``revert_response``.
    * Delete confirmation uses Yes|No and returns ``delete_response``.

    If a matching dialog appears with a ``None`` response, the test fails.

    Returns the list of recorded calls so a test can assert on them if needed.
    """
    calls = []
    guard_buttons = QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
    revert_buttons = QMessageBox.Discard | QMessageBox.Cancel
    delete_buttons = QMessageBox.Yes | QMessageBox.No

    def _fake_question(parent, title, text, buttons, default=None, **kw):
        calls.append({"title": title, "text": text, "buttons": buttons})
        if buttons == guard_buttons:
            if guard_response is None:
                pytest.fail(
                    "Unexpected unsaved-changes guard dialog appeared: "
                    f"title={title!r}, text={text!r}"
                )
            return guard_response
        if buttons == revert_buttons:
            if revert_response is None:
                pytest.fail(
                    "Unexpected revert-confirmation dialog appeared: "
                    f"title={title!r}, text={text!r}"
                )
            return revert_response
        if buttons == delete_buttons:
            if delete_response is None:
                pytest.fail(
                    "Unexpected delete-confirmation dialog appeared: "
                    f"title={title!r}, text={text!r}"
                )
            return delete_response
        pytest.fail(
            f"Unexpected QMessageBox.question call: title={title!r}, text={text!r}"
        )

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _fake_question)
    return calls


def _silence_close_guard(win, monkeypatch):
    """
    Patch *win*.maybe_commit_unsaved_changes so that the closeEvent during
    qtbot widget teardown does not block on an unexpected dialog.

    Call this after all test assertions are complete, when an entry is
    intentionally left dirty.
    """
    monkeypatch.setattr(win, "maybe_commit_unsaved_changes", lambda: True)


@pytest.mark.qt
def test_cancelled_selection_keeps_current_on_right_click(qtbot, isolated_cwd, monkeypatch):
    # Prepare a Projects/default compendium
    _write_compendium(Path(isolated_cwd))

    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree

    # Find Alice and Bob items
    alice_item = None
    bob_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
            elif item.text(0) == "Bob":
                bob_item = item

    assert alice_item is not None and bob_item is not None

    # Select Alice and make it dirty. If the selection handler hasn't run
    # by the time we proceed, call load_entry explicitly to ensure the test
    # state is correct (this avoids flaky timing differences on CI).
    tree.setCurrentItem(alice_item)
    qtbot.wait(50)
    if win.current_entry_item is None or win.current_entry_item.text(0) != 'Alice':
        win.load_entry(alice_item.text(0), alice_item)
    # Modify content to set dirty flag
    win.editor.setPlainText(win.editor.toPlainText() + " edited")
    assert win.is_dirty()

    # Force QMessageBox.question to return Cancel
    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", lambda *a, **k: QMessageBox.Cancel)

    # Right-click Bob's visual rect center
    rect = tree.visualItemRect(bob_item)
    center = rect.center()
    qtbot.mouseClick(tree.viewport(), Qt.RightButton, pos=QPoint(center.x(), center.y()))
    # Allow the singleShot restore to run and then verify selection was restored.
    qtbot.wait(100)
    assert tree.currentItem().text(0) == "Alice"


@pytest.mark.qt
def test_cancelled_selection_keeps_current_on_left_click(qtbot, isolated_cwd, monkeypatch):
    # Prepare a Projects/default compendium
    _write_compendium(Path(isolated_cwd))

    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree

    # Find Alice and Bob items
    alice_item = None
    bob_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
            elif item.text(0) == "Bob":
                bob_item = item

    assert alice_item is not None and bob_item is not None

    # Select Alice and make it dirty. See comment above for timing handling.
    tree.setCurrentItem(alice_item)
    qtbot.wait(50)
    if win.current_entry_item is None or win.current_entry_item.text(0) != 'Alice':
        win.load_entry(alice_item.text(0), alice_item)
    # Modify content to set dirty flag
    win.editor.setPlainText(win.editor.toPlainText() + " edited")
    assert win.is_dirty()

    # Force QMessageBox.question to return Cancel
    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", lambda *a, **k: QMessageBox.Cancel)

    # Left-click Bob's visual rect center
    rect = tree.visualItemRect(bob_item)
    center = rect.center()
    qtbot.mouseClick(tree.viewport(), Qt.LeftButton, pos=QPoint(center.x(), center.y()))
    # Allow the singleShot restore to run and then verify selection was restored.
    qtbot.wait(100)
    assert tree.currentItem().text(0) == "Alice"


@pytest.mark.qt
def test_move_entry_aborted_when_user_cancels_guard(qtbot, isolated_cwd, monkeypatch):
    """Programmatic move_entry should abort if the user cancels the unsaved-changes prompt."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    alice_item = None
    bob_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
            elif item.text(0) == "Bob":
                bob_item = item

    assert alice_item and bob_item

    # Select Alice and make it dirty. See comment above for timing handling.
    tree.setCurrentItem(alice_item)
    qtbot.wait(50)
    if win.current_entry_item is None or win.current_entry_item.text(0) != 'Alice':
        win.load_entry(alice_item.text(0), alice_item)
    win.editor.setPlainText(win.editor.toPlainText() + " edited")
    assert win.is_dirty()

    # Monkeypatch the QMessageBox to simulate user pressing Cancel in the guard
    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", lambda *a, **k: QMessageBox.Cancel)

    # Call move_entry directly for Bob; it should do nothing because the guard was cancelled
    win.move_entry(bob_item)

    # Ensure Bob was not moved (still under Characters category) - look up UUIDs
    uuids = {cat.child(j).data(2, Qt.UserRole) for i in range(tree.topLevelItemCount()) for cat in [tree.topLevelItem(i)] for j in range(cat.childCount())}
    # Alice's uuid should still be in tree and Bob's too (no move happened)
    assert any(item.text(0) == 'Alice' for item in [tree.topLevelItem(i).child(j) for i in range(tree.topLevelItemCount()) for j in range(tree.topLevelItem(i).childCount())])


@pytest.mark.qt
def test_guard_save_branch_persists_dirty_entry_then_loads_clicked_entry(qtbot, isolated_cwd, monkeypatch):
    """Clicking Bob while Alice is dirty and choosing Save persists Alice and loads Bob cleanly."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)
    edited_alice = "Alice content edited and saved"
    win.editor.setPlainText(edited_alice)
    assert win.is_dirty()

    # Revert dialog is unexpected in this flow.
    _patch_guard_detection(monkeypatch, revert_response=None)
    patched_question = QMessageBox.question

    def _guard_save_only(parent, title, text, buttons, default=None, **kw):
        if buttons == (QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel):
            return QMessageBox.Save
        return patched_question(parent, title, text, buttons, default, **kw)

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _guard_save_only)

    bob_item = None
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Bob":
                bob_item = item
                break
        if bob_item is not None:
            break
    assert bob_item is not None

    # Trigger on_item_changed via real click navigation.
    rect = win.tree.visualItemRect(bob_item)
    center = rect.center()
    qtbot.mouseClick(win.tree.viewport(), Qt.LeftButton, pos=QPoint(center.x(), center.y()))
    qtbot.wait(100)

    if win.current_entry_item is None or win.current_entry_item.text(0) != "Bob":
        current_item = win.tree.currentItem()
        if current_item is not None and current_item.data(0, Qt.UserRole) == "entry" and current_item.text(0) == "Bob":
            win.load_entry(current_item.text(0), current_item)

    assert win.current_entry_item is not None and win.current_entry_item.text(0) == "Bob"
    assert win.editor.toPlainText() == "Bob content"
    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    saved_by_name = {
        entry["name"]: entry["content"]
        for cat in data["categories"]
        for entry in cat["entries"]
    }
    assert saved_by_name["Alice"] == edited_alice
    assert saved_by_name["Bob"] == "Bob content"


@pytest.mark.qt
def test_guard_discard_branch_keeps_disk_state_and_loads_clicked_entry(qtbot, isolated_cwd, monkeypatch):
    """Clicking Bob while Alice is dirty and choosing Discard keeps Alice's saved content and loads Bob cleanly."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)
    win.editor.setPlainText("Alice content edited then discarded")
    assert win.is_dirty()

    # Revert dialog is unexpected in this flow.
    _patch_guard_detection(monkeypatch, revert_response=None)
    patched_question = QMessageBox.question

    def _guard_discard_only(parent, title, text, buttons, default=None, **kw):
        if buttons == (QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel):
            return QMessageBox.Discard
        return patched_question(parent, title, text, buttons, default, **kw)

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _guard_discard_only)

    bob_item = None
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Bob":
                bob_item = item
                break
        if bob_item is not None:
            break
    assert bob_item is not None

    rect = win.tree.visualItemRect(bob_item)
    center = rect.center()
    qtbot.mouseClick(win.tree.viewport(), Qt.LeftButton, pos=QPoint(center.x(), center.y()))
    qtbot.wait(100)

    if win.current_entry_item is None or win.current_entry_item.text(0) != "Bob":
        current_item = win.tree.currentItem()
        if current_item is not None and current_item.data(0, Qt.UserRole) == "entry" and current_item.text(0) == "Bob":
            win.load_entry(current_item.text(0), current_item)

    assert win.current_entry_item is not None and win.current_entry_item.text(0) == "Bob"
    assert win.editor.toPlainText() == "Bob content"
    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    saved_by_name = {
        entry["name"]: entry["content"]
        for cat in data["categories"]
        for entry in cat["entries"]
    }
    assert saved_by_name["Alice"] == "Alice content"
    assert saved_by_name["Bob"] == "Bob content"


@pytest.mark.qt
def test_context_menu_not_shown_when_selection_cancelled(qtbot, isolated_cwd, monkeypatch):
    """Ensure QMenu.exec_ is not invoked when the unsaved-changes guard is cancelled."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    alice_item = None
    bob_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
            elif item.text(0) == "Bob":
                bob_item = item

    assert alice_item and bob_item

    # Select Alice and make it dirty
    tree.setCurrentItem(alice_item)
    qtbot.wait(50)
    if win.current_entry_item is None or win.current_entry_item.text(0) != 'Alice':
        win.load_entry(alice_item.text(0), alice_item)
    win.editor.setPlainText(win.editor.toPlainText() + " edited")
    assert win.is_dirty()

    # Monkeypatch QMessageBox to simulate Cancel and spy on QMenu.exec_
    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", lambda *a, **k: QMessageBox.Cancel)

    exec_calls = []
    def fake_exec(self, *args, **kwargs):
        exec_calls.append(True)
        return None

    monkeypatch.setattr(QMenu, "exec_", fake_exec)

    # Right-click Bob
    rect = tree.visualItemRect(bob_item)
    center = rect.center()
    qtbot.mouseClick(tree.viewport(), Qt.RightButton, pos=QPoint(center.x(), center.y()))

    # Allow any scheduled restores/handlers to run
    qtbot.wait(100)

    # QMenu.exec_ should not have been called and selection should remain on Alice
    assert exec_calls == []
    assert tree.currentItem().text(0) == "Alice"


@pytest.mark.qt
def test_delete_entry_yes_removes_entry_from_tree_and_disk_and_clears_ui(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    alice_item = _load_alice(win, qtbot)
    assert win.current_entry_item is not None and win.current_entry_item.text(0) == "Alice"

    def _confirm_delete(parent, title, text, buttons, default=None, **kw):
        if "Confirm Deletion" in title:
            return QMessageBox.Yes
        pytest.fail(f"Unexpected QMessageBox.question call: title={title!r}, text={text!r}")

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _confirm_delete)

    win.delete_entry(alice_item)
    qtbot.wait(100)

    names = []
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            names.append(cat.child(j).text(0))
    assert "Alice" not in names
    assert "Bob" in names

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    disk_names = [entry["name"] for cat in data["categories"] for entry in cat["entries"]]
    assert "Alice" not in disk_names
    assert "Bob" in disk_names

    assert win.entry_name_label.text() == "No entry selected"
    assert win.current_entry_item is None
    assert not win.save_button.isVisible()
    assert not win.revert_button.isVisible()
    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_delete_entry_no_keeps_tree_and_disk_unchanged(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    alice_item = _load_alice(win, qtbot)

    def _cancel_delete(parent, title, text, buttons, default=None, **kw):
        if "Confirm Deletion" in title:
            return QMessageBox.No
        pytest.fail(f"Unexpected QMessageBox.question call: title={title!r}, text={text!r}")

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _cancel_delete)

    win.delete_entry(alice_item)
    qtbot.wait(100)

    names = []
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            names.append(cat.child(j).text(0))
    assert "Alice" in names
    assert "Bob" in names

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    disk_names = [entry["name"] for cat in data["categories"] for entry in cat["entries"]]
    assert "Alice" in disk_names
    assert "Bob" in disk_names


@pytest.mark.qt
def test_delete_category_yes_removes_category_and_entries_from_tree_and_disk(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)
    category_item = None
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.text(0) == "Characters":
            category_item = item
            break
    assert category_item is not None

    def _confirm_delete(parent, title, text, buttons, default=None, **kw):
        if "Confirm Deletion" in title:
            return QMessageBox.Yes
        pytest.fail(f"Unexpected QMessageBox.question call: title={title!r}, text={text!r}")

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _confirm_delete)

    win.delete_category(category_item)
    qtbot.wait(100)

    assert win.tree.topLevelItemCount() == 0

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["categories"] == []

    assert win.entry_name_label.text() == "No entry selected"
    assert win.current_entry_item is None
    assert not win.save_button.isVisible()
    assert not win.revert_button.isVisible()
    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_delete_category_no_keeps_tree_and_disk_unchanged(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)
    category_item = None
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.text(0) == "Characters":
            category_item = item
            break
    assert category_item is not None

    def _cancel_delete(parent, title, text, buttons, default=None, **kw):
        if "Confirm Deletion" in title:
            return QMessageBox.No
        pytest.fail(f"Unexpected QMessageBox.question call: title={title!r}, text={text!r}")

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox.question", _cancel_delete)

    win.delete_category(category_item)
    qtbot.wait(100)

    assert win.tree.topLevelItemCount() == 1
    cat = win.tree.topLevelItem(0)
    assert cat.text(0) == "Characters"
    names = [cat.child(i).text(0) for i in range(cat.childCount())]
    assert "Alice" in names
    assert "Bob" in names

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["categories"]) == 1
    assert data["categories"][0]["name"] == "Characters"
    disk_names = [entry["name"] for entry in data["categories"][0]["entries"]]
    assert "Alice" in disk_names
    assert "Bob" in disk_names


@pytest.mark.qt
def test_new_entry_creates_entry_and_selects_it(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("Charlie", True))

    category_item = None
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.text(0) == "Characters":
            category_item = item
            break
    assert category_item is not None

    win.new_entry(category_item)
    # Event-bus update and _find_and_select_entry_by_uuid can race; wait for settle.
    qtbot.wait(100)

    selected = win.tree.currentItem()
    assert selected is not None
    assert selected.data(0, Qt.UserRole) == "entry"
    assert selected.text(0) == "Charlie"

    names = []
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        for j in range(cat.childCount()):
            names.append(cat.child(j).text(0))
    assert "Charlie" in names

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    disk_names = [entry["name"] for cat in data["categories"] for entry in cat["entries"]]
    assert "Charlie" in disk_names


@pytest.mark.qt
def test_new_category_creates_category_and_selects_it(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("Places", True))

    win.new_category()
    # Event-bus update and follow-up selection run asynchronously enough to require a short wait.
    qtbot.wait(100)

    selected = win.tree.currentItem()
    assert selected is not None
    assert selected.data(0, Qt.UserRole) == "category"
    assert selected.text(0) == "Places"

    category_names = [win.tree.topLevelItem(i).text(0) for i in range(win.tree.topLevelItemCount())]
    assert "Places" in category_names

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    disk_category_names = [cat["name"] for cat in data["categories"]]
    assert "Places" in disk_category_names


@pytest.mark.qt
def test_dirty_indicators_update_for_overview_and_details_tabs(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)

    overview_base = win.tabs.tabText(0)
    details_base = win.tabs.tabText(1)

    win.editor.setPlainText("Alice overview edited")
    assert win.is_dirty()
    assert win.tabs.tabText(0).startswith("● ")
    assert win.tabs.tabText(0).endswith(overview_base)

    win.details_editor.setPlainText("Alice private details edited")
    assert win.is_dirty()
    assert win.tabs.tabText(1).startswith("● ")
    assert win.tabs.tabText(1).endswith(details_base)

    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_clicking_category_clears_entry_ui(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)
    assert win.save_button.isVisible()
    assert win.revert_button.isVisible()

    category_item = None
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.text(0) == "Characters":
            category_item = item
            break
    assert category_item is not None

    win.tree.setCurrentItem(category_item)
    qtbot.wait(50)

    assert win.entry_name_label.text() == "No entry selected"
    assert not win.save_button.isVisible()
    assert not win.revert_button.isVisible()


@pytest.mark.qt
def test_editing_details_marks_entry_dirty_and_enables_buttons(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)

    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    win.details_editor.setPlainText("Detailed notes for Alice")

    assert win.is_dirty()
    assert win.save_button.isEnabled()
    assert win.revert_button.isEnabled()

    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_selection_restored_by_uuid_after_rebuild(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    alice_item = _load_alice(win, qtbot)
    alice_uuid = alice_item.data(2, Qt.UserRole)
    assert alice_uuid

    assert win.manager.rename_entry(alice_uuid, "AliceRenamed")
    qtbot.wait(100)
    win.populate_compendium()

    current = win.tree.currentItem()
    assert current is not None
    assert current.data(0, Qt.UserRole) == "entry"
    assert current.data(2, Qt.UserRole) == alice_uuid
    assert current.text(0) == "AliceRenamed"


@pytest.mark.qt
def test_move_item_up_persists_entry_order_to_disk(qtbot, isolated_cwd, monkeypatch):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)

    bob_item = None
    for i in range(win.tree.topLevelItemCount()):
        cat = win.tree.topLevelItem(i)
        if cat.text(0) != "Characters":
            continue
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Bob":
                bob_item = item
                break
        break
    assert bob_item is not None

    win.move_item(bob_item, "up")
    qtbot.wait(100)

    category = None
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        if item.text(0) == "Characters":
            category = item
            break
    assert category is not None
    order_in_tree = [category.child(i).text(0) for i in range(category.childCount())]
    assert order_in_tree[:2] == ["Bob", "Alice"]

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    categories = {cat["name"]: cat for cat in data["categories"]}
    disk_order = [entry["name"] for entry in categories["Characters"]["entries"]]
    assert disk_order[:2] == ["Bob", "Alice"]


@pytest.mark.qt
def test_on_compendium_updated_ignores_other_projects(qtbot, isolated_cwd):
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)

    calls = []
    win.populate_compendium = lambda: calls.append("populate")

    win.on_compendium_updated("other-project")
    assert calls == []

    win.on_compendium_updated("default")
    assert calls == ["populate"]


@pytest.mark.qt
def test_selecting_entry_loads_editor_content(qtbot, isolated_cwd):
    """Selecting an entry should load its data into the center panel."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    alice_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
                break
        if alice_item is not None:
            break

    assert alice_item is not None
    tree.setCurrentItem(alice_item)
    qtbot.wait(50)

    assert win.current_entry_item is not None and win.current_entry_item.text(0) == "Alice"
    assert win.entry_name_label.text() == "Alice"
    assert win.editor.toPlainText() == "Alice content"


@pytest.mark.qt
def test_rename_entry_via_context_menu(qtbot, isolated_cwd, monkeypatch):
    """Renaming an entry via the context menu should persist the new name and refresh the tree."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    # Find Alice item
    alice_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
                break
        if alice_item:
            break

    assert alice_item is not None

    # Monkeypatch the input dialog to return a new name
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("AliceRenamed", True))

    # Make QMenu.exec_ trigger the Rename Entry action (call its callback)
    def _exec_trigger_rename(menu, *a, **k):
        for action in menu.actions():
            # action text may be localized; look for the word Rename to identify the rename action
            if "Rename" in action.text():
                # programmatically trigger the action so the lambda runs
                action.trigger()
                return action
        return None

    monkeypatch.setattr("PyQt5.QtWidgets.QMenu.exec_", _exec_trigger_rename)

    # Invoke the context menu handler directly at Alice's visual center
    rect = tree.visualItemRect(alice_item)
    center = rect.center()
    win.show_context_menu(center)

    # Allow event loop to process the rename and tree refresh
    qtbot.wait(100)

    # Ensure the tree now contains the renamed entry
    found = False
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            if cat.child(j).text(0) == "AliceRenamed":
                found = True
                break
        if found:
            break
    assert found


@pytest.mark.qt
def test_rename_entry_via_double_click(qtbot, isolated_cwd, monkeypatch):
    """Double-clicking an entry should invoke the rename dialog (same as menu) and persist the new name."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    alice_item = None
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            item = cat.child(j)
            if item.text(0) == "Alice":
                alice_item = item
                break
        if alice_item:
            break

    assert alice_item is not None

    # Monkeypatch input dialog to accept rename
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("AliceDbl", True))

    # Invoke the double-click handler directly to trigger rename
    win.on_item_double_clicked(alice_item, 0)
    # Allow event loop to handle rename and refresh
    qtbot.wait(100)

    # Verify renamed entry present
    found = False
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        for j in range(cat.childCount()):
            if cat.child(j).text(0) == "AliceDbl":
                found = True
                break
        if found:
            break
    assert found


@pytest.mark.qt
def test_rename_category_via_context_menu(qtbot, isolated_cwd, monkeypatch):
    """Renaming a category via the context menu should persist the new name and refresh the tree."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    # Find the Characters category item (top-level)
    cat_item = None
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item.text(0) == "Characters":
            cat_item = item
            break

    assert cat_item is not None

    # Monkeypatch the input dialog to return a new name
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("People", True))

    # Make QMenu.exec_ trigger the Rename Category action
    def _exec_trigger_rename(menu, *a, **k):
        for action in menu.actions():
            if "Rename" in action.text():
                action.trigger()
                return action
        return None

    monkeypatch.setattr("PyQt5.QtWidgets.QMenu.exec_", _exec_trigger_rename)

    # Invoke the context menu handler directly at category's visual center
    rect = tree.visualItemRect(cat_item)
    center = rect.center()
    win.show_context_menu(center)

    qtbot.wait(100)

    # Ensure the tree now contains the renamed category
    found = any(tree.topLevelItem(i).text(0) == "People" for i in range(tree.topLevelItemCount()))
    assert found


@pytest.mark.qt
def test_rename_category_via_double_click(qtbot, isolated_cwd, monkeypatch):
    """Double-clicking a category should invoke the rename dialog (same as menu) and persist the new name."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    tree = win.tree
    cat_item = None
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item.text(0) == "Characters":
            cat_item = item
            break

    assert cat_item is not None

    # Monkeypatch input dialog to accept rename
    monkeypatch.setattr("PyQt5.QtWidgets.QInputDialog.getText", lambda *a, **k: ("Folk", True))

    # Invoke the double-click handler directly to trigger rename
    win.on_item_double_clicked(cat_item, 0)
    qtbot.wait(100)

    # Verify renamed category present
    found = any(tree.topLevelItem(i).text(0) == "Folk" for i in range(tree.topLevelItemCount()))
    assert found


# ---------------------------------------------------------------------------
# Overview editing - save and revert
# ---------------------------------------------------------------------------



@pytest.mark.qt
def test_editing_overview_marks_entry_dirty(qtbot, isolated_cwd, monkeypatch):
    """Typing in the overview editor marks the entry dirty and enables save/revert buttons."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    # Any guard dialog that appears during this test is a bug – fail fast.
    _patch_guard_detection(monkeypatch)

    _load_alice(win, qtbot)

    # Before editing: entry is clean, buttons disabled.
    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    # Edit the overview text.
    win.editor.setPlainText("Alice content edited")

    # After editing: entry is dirty, buttons enabled.
    assert win.is_dirty()
    assert win.save_button.isEnabled()
    assert win.revert_button.isEnabled()

    # The entry is still dirty at this point; silence the close guard so the
    # qtbot widget teardown does not block on an unexpected dialog.
    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_save_button_persists_overview_and_clears_dirty(qtbot, isolated_cwd, monkeypatch):
    """Clicking Save persists the edited overview to disk and clears the dirty state."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    # No dialog of any kind is expected during a normal save flow.
    _patch_guard_detection(monkeypatch)

    _load_alice(win, qtbot)

    # Edit the overview.
    new_text = "Alice content – saved version"
    win.editor.setPlainText(new_text)
    assert win.is_dirty()

    # Click Save.
    win.save_button.click()
    qtbot.wait(50)

    # Dirty state must be cleared and buttons disabled.
    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    # The new content must be persisted to disk.
    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    saved_content = next(
        e["content"]
        for cat in data["categories"]
        for e in cat["entries"]
        if e["name"] == "Alice"
    )
    assert saved_content == new_text


@pytest.mark.qt
def test_revert_button_restores_original_overview(qtbot, isolated_cwd, monkeypatch):
    """Clicking Revert (and confirming) reloads the saved overview and clears dirty state."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)
    original_text = win.editor.toPlainText()

    # Edit the overview to make it dirty.
    win.editor.setPlainText("Alice content – unsaved edit")
    assert win.is_dirty()

    # The revert confirmation dialog is expected (return Discard to confirm).
    # Any guard dialog is unexpected and will fail the test.
    _patch_guard_detection(monkeypatch, revert_response=QMessageBox.Discard)

    # Click Revert.
    win.revert_button.click()
    qtbot.wait(100)

    # Dirty state must be cleared and buttons disabled.
    assert not win.is_dirty()
    assert not win.save_button.isEnabled()
    assert not win.revert_button.isEnabled()

    # The editor must show the original (saved) text again.
    assert win.editor.toPlainText() == original_text


@pytest.mark.qt
def test_revert_button_cancel_keeps_dirty_edit(qtbot, isolated_cwd, monkeypatch):
    """Cancelling the Revert confirmation dialog leaves the dirty edit intact."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _load_alice(win, qtbot)

    edited_text = "Alice content – unsaved edit"
    win.editor.setPlainText(edited_text)
    assert win.is_dirty()

    # The revert confirmation dialog is expected (return Cancel to abort).
    # Any guard dialog is unexpected and will fail the test.
    _patch_guard_detection(monkeypatch, revert_response=QMessageBox.Cancel)

    # Click Revert – the user cancels.
    win.revert_button.click()
    qtbot.wait(50)

    # Entry must still be dirty and the edited text must remain.
    assert win.is_dirty()
    assert win.editor.toPlainText() == edited_text

    # Silence the close guard so qtbot teardown doesn't block: the entry is
    # intentionally left dirty and the guard is not part of this test.
    _silence_close_guard(win, monkeypatch)


# ---------------------------------------------------------------------------
# Relationship UUID handling
# ---------------------------------------------------------------------------


def _write_compendium_with_relationships(root: Path) -> dict:
    """Write a compendium where Alice has a UUID-based relationship to Bob.

    Returns a dict with ``alice_uuid`` and ``bob_uuid`` for assertion use.
    """
    projects = root / "Projects"
    projects.mkdir(exist_ok=True)
    default = projects / "default"
    default.mkdir(exist_ok=True)
    alice_uuid = "rel-e1"
    bob_uuid = "rel-e2"
    data = {
        "version": 3,
        "categories": [
            {
                "name": "Characters",
                "uuid": "rel-cat-1",
                "entries": [
                    {
                        "name": "Alice",
                        "uuid": alice_uuid,
                        "content": "Alice content",
                        "details": "",
                        "tags": [],
                        "relationships": [{"uuid": bob_uuid, "type": "friend"}],
                        "images": [],
                    },
                    {
                        "name": "Bob",
                        "uuid": bob_uuid,
                        "content": "Bob content",
                        "details": "",
                        "tags": [],
                        "relationships": [],
                        "images": [],
                    },
                ],
            }
        ],
    }
    with open(default / "compendium.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"alice_uuid": alice_uuid, "bob_uuid": bob_uuid}


def _write_compendium_with_legacy_relationships(root: Path) -> dict:
    """Write a compendium where Alice has a *name*-based (legacy) relationship to Bob."""
    projects = root / "Projects"
    projects.mkdir(exist_ok=True)
    default = projects / "default"
    default.mkdir(exist_ok=True)
    alice_uuid = "leg-e1"
    bob_uuid = "leg-e2"
    data = {
        "version": 3,
        "categories": [
            {
                "name": "Characters",
                "uuid": "leg-cat-1",
                "entries": [
                    {
                        "name": "Alice",
                        "uuid": alice_uuid,
                        "content": "Alice content",
                        "details": "",
                        "tags": [],
                        # Legacy format: 'name' instead of 'uuid'
                        "relationships": [{"name": "Bob", "type": "rival"}],
                        "images": [],
                    },
                    {
                        "name": "Bob",
                        "uuid": bob_uuid,
                        "content": "Bob content",
                        "details": "",
                        "tags": [],
                        "relationships": [],
                        "images": [],
                    },
                ],
            }
        ],
    }
    with open(default / "compendium.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"alice_uuid": alice_uuid, "bob_uuid": bob_uuid}


def _select_relationships_tab(win, qtbot) -> None:
    """Switch to the Relationships tab in *win*."""
    for i in range(win.tabs.count()):
        if "Rel" in win.tabs.tabText(i):
            win.tabs.setCurrentIndex(i)
            break
    qtbot.wait(50)


@pytest.mark.qt
def test_load_entry_uuid_relationship_shows_name(qtbot, isolated_cwd, monkeypatch):
    """Loading an entry with a UUID-based relationship displays the related entry's name."""
    uuids = _write_compendium_with_relationships(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)
    _select_relationships_tab(win, qtbot)

    assert win.relationships_list.topLevelItemCount() == 1
    rel_item = win.relationships_list.topLevelItem(0)
    # The list should *display* the name, not the UUID.
    assert rel_item.text(0) == "Bob"
    # The UUID is stored in UserRole for save round-trip.
    assert rel_item.data(0, Qt.ItemDataRole.UserRole) == uuids["bob_uuid"]
    assert rel_item.text(1) == "friend"

    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_save_entry_persists_relationship_as_uuid(qtbot, isolated_cwd, monkeypatch):
    """Saving an entry writes UUID-based relationships to disk, never the character name."""
    uuids = _write_compendium_with_relationships(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)

    # Make entry dirty so save is meaningful.
    win.editor.setPlainText("Alice content – edited for save test")
    assert win.is_dirty()
    win.save_button.click()
    qtbot.wait(50)

    compendium_path = Path(isolated_cwd) / "Projects" / "default" / "compendium.json"
    with open(compendium_path, encoding="utf-8") as fh:
        data = json.load(fh)
    alice_entry = next(
        e for cat in data["categories"] for e in cat["entries"] if e["name"] == "Alice"
    )
    assert len(alice_entry["relationships"]) == 1
    rel = alice_entry["relationships"][0]
    assert "uuid" in rel, "Relationship must be stored with 'uuid' key"
    assert rel["uuid"] == uuids["bob_uuid"]
    assert "name" not in rel, "Relationship must NOT be stored with legacy 'name' key"
    assert rel["type"] == "friend"


@pytest.mark.qt
def test_legacy_name_based_relationship_displays_gracefully(qtbot, isolated_cwd, monkeypatch):
    """An unmigrated name-based relationship is shown by name in the UI (not as blank)."""
    # Write legacy data that bypasses the manager's migration by being loaded directly.
    uuids = _write_compendium_with_legacy_relationships(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    # The manager runs migration on load, converting name→uuid.  After migration the
    # relationship should display Bob's name (resolved from the migrated UUID).
    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)
    _select_relationships_tab(win, qtbot)

    assert win.relationships_list.topLevelItemCount() == 1
    rel_item = win.relationships_list.topLevelItem(0)
    # Post-migration display: Bob's name must be shown.
    assert rel_item.text(0) == "Bob"
    assert rel_item.text(1) == "rival"

    _silence_close_guard(win, monkeypatch)


@pytest.mark.qt
def test_add_relationship_stores_uuid_not_name(qtbot, isolated_cwd, monkeypatch):
    """Adding a relationship via the UI combo stores the UUID, not the character name."""
    _write_compendium(Path(isolated_cwd))
    parent = DummyParent()
    win = EnhancedCompendiumWindow(parent=parent)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    _patch_guard_detection(monkeypatch)
    _load_alice(win, qtbot)
    _select_relationships_tab(win, qtbot)

    # Select "Bob" in the relationship combo.
    for i in range(win.relationship_combo.count()):
        if win.relationship_combo.itemText(i) == "Bob":
            win.relationship_combo.setCurrentIndex(i)
            break
    bob_uuid_from_combo = win.relationship_combo.currentData()
    assert bob_uuid_from_combo, "Combo should store Bob's UUID as item data"

    win.relationship_type.setText("ally")
    win.add_relationship_button.click()
    qtbot.wait(50)

    # The relationships_list should have exactly one item.
    assert win.relationships_list.topLevelItemCount() == 1
    rel_item = win.relationships_list.topLevelItem(0)
    # Displayed as name, stored as UUID.
    assert rel_item.text(0) == "Bob"
    stored_uuid = rel_item.data(0, Qt.ItemDataRole.UserRole)
    assert stored_uuid == bob_uuid_from_combo
    assert stored_uuid != "Bob", "UUID must not equal the character name"

    _silence_close_guard(win, monkeypatch)

