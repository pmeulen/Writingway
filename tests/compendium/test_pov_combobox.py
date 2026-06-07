"""
Tests for compendium.pov_combobox.POVComboBox.

All tests require a QApplication instance (pytest-qt's ``qtbot`` fixture) and
filesystem isolation (``isolated_cwd``).
"""

from __future__ import annotations

import pytest
from PyQt5.QtCore import Qt

from compendium.compendium_manager import CompendiumManager
from compendium.pov_combobox import NEW_CHARACTER_UUID, NONE_CHARACTER_UUID, POVComboBox, POVItemData

# ---------------------------------------------------------------------------
# Helper to build a POVComboBox for a sandboxed project
# ---------------------------------------------------------------------------

def _make_combo(isolated_cwd, project_name: str = "POVTest", initial_uuid: str = NONE_CHARACTER_UUID) -> POVComboBox:
    project_dir = isolated_cwd / "Projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return POVComboBox(project_name, initial_uuid=initial_uuid)


def _make_manager(isolated_cwd, project_name: str = "POVTest") -> CompendiumManager:
    project_dir = isolated_cwd / "Projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return CompendiumManager(project_name=project_name, event_bus=None)


# ===========================================================================
# Structure tests (no interaction needed)
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_none_item_present_at_index_0(qtbot, isolated_cwd):
    combo = _make_combo(isolated_cwd)
    qtbot.addWidget(combo)
    data: POVItemData = combo.itemData(0, Qt.ItemDataRole.UserRole)
    assert data is not None
    assert data.kind == "none"
    assert data.uuid == NONE_CHARACTER_UUID


@pytest.mark.qt
@pytest.mark.integration
def test_new_item_always_last(qtbot, isolated_cwd):
    combo = _make_combo(isolated_cwd)
    qtbot.addWidget(combo)
    last_idx = combo.count() - 1
    data: POVItemData = combo.itemData(last_idx, Qt.ItemDataRole.UserRole)
    assert data is not None
    assert data.kind == "new"
    assert data.uuid == NEW_CHARACTER_UUID


@pytest.mark.qt
@pytest.mark.integration
def test_initial_uuid_selects_correct_item(qtbot, isolated_cwd):
    """Constructing with a valid UUID pre-selects that character."""
    mgr = _make_manager(isolated_cwd)
    entry = mgr.add_pov_character("Lyra", "The chosen one.")
    combo = _make_combo(isolated_cwd, initial_uuid=entry["uuid"])
    qtbot.addWidget(combo)
    assert combo.current_uuid() == entry["uuid"]
    assert combo.currentText() == "Lyra"


# ===========================================================================
# Signal tests
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_pov_uuid_changed_emitted_on_selection_change(qtbot, isolated_cwd):
    """Selecting a real character entry emits pov_uuid_changed with that UUID."""
    mgr = _make_manager(isolated_cwd)
    entry = mgr.add_pov_character("Elan", "A mage.")
    combo = _make_combo(isolated_cwd)
    qtbot.addWidget(combo)

    emitted: list[str] = []
    combo.pov_uuid_changed.connect(emitted.append)

    # Find index for "Elan"
    target_idx = -1
    for i in range(combo.count()):
        d: POVItemData = combo.itemData(i, Qt.ItemDataRole.UserRole)
        if d and d.uuid == entry["uuid"]:
            target_idx = i
            break
    assert target_idx >= 0, "Elan not found in combo"

    combo.setCurrentIndex(target_idx)

    assert emitted == [entry["uuid"]]


@pytest.mark.qt
@pytest.mark.integration
def test_pov_uuid_changed_not_emitted_for_new_item_cancel(qtbot, isolated_cwd):
    """Cancelling the New Character dialog should NOT emit pov_uuid_changed."""
    combo = _make_combo(isolated_cwd)
    qtbot.addWidget(combo)

    emitted: list[str] = []
    combo.pov_uuid_changed.connect(emitted.append)

    # Monkeypatch: make the NewCharacterDialog immediately reject
    from unittest.mock import MagicMock, patch
    mock_dialog = MagicMock()
    mock_dialog.exec_.return_value = 0  # QDialog.Rejected
    with patch("compendium.pov_combobox.NewCharacterDialog", return_value=mock_dialog):
        last_idx = combo.count() - 1  # "New..." is last
        combo.setCurrentIndex(last_idx)

    assert emitted == []


# ===========================================================================
# Repopulate / restore
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_compendium_update_restores_selection_by_uuid(qtbot, isolated_cwd):
    """After a compendium update the previously selected UUID is still selected."""
    mgr = _make_manager(isolated_cwd)
    first = mgr.add_pov_character("Kira", "A scout.")
    combo = _make_combo(isolated_cwd, initial_uuid=first["uuid"])
    qtbot.addWidget(combo)

    # Simulate compendium update (add another character)
    mgr.add_pov_character("Dax", "A warrior.")
    combo.on_compendium_updated("POVTest")

    # Selection should still be Kira
    assert combo.current_uuid() == first["uuid"]
    assert combo.currentText() == "Kira"


# ===========================================================================
# Legacy name → UUID migration
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_unknown_legacy_name_falls_back_to_none(qtbot, isolated_cwd):
    """An unresolvable legacy name falls back to NONE_CHARACTER_UUID."""
    combo = _make_combo(isolated_cwd, initial_uuid="NonExistentCharacter")
    qtbot.addWidget(combo)
    assert combo.current_uuid() == NONE_CHARACTER_UUID


# ===========================================================================
# currentIndexChanged stacking bug
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_currentindexchanged_not_stacked_after_repopulate(qtbot, isolated_cwd):
    """populate_combo() must NOT add an extra currentIndexChanged connection.

    If the bug exists, every repopulate would stack another connection and
    pov_uuid_changed would be emitted multiple times per selection change.
    """
    mgr = _make_manager(isolated_cwd)
    mgr.add_pov_character("Solo", "A lone wolf.")
    combo = _make_combo(isolated_cwd)
    qtbot.addWidget(combo)

    # Force several repopulations (simulating compendium updates)
    for _ in range(5):
        combo.populate_combo()
        combo.set_to_selected_pov()

    mgr.add_pov_character("Duo", "A partner.")
    combo.populate_combo()
    combo.set_to_selected_pov()

    emitted: list[str] = []
    combo.pov_uuid_changed.connect(emitted.append)

    # Select index 1 (first real character - "Solo")
    combo.setCurrentIndex(1)

    assert len(emitted) == 1, (
        f"Expected exactly 1 emission but got {len(emitted)}: {emitted}. "
        "currentIndexChanged was probably stacked."
    )


# ===========================================================================
# current_pov() returns name (not UUID)
# ===========================================================================

@pytest.mark.qt
@pytest.mark.integration
def test_current_pov_returns_name_for_selected_entry(qtbot, isolated_cwd):
    mgr = _make_manager(isolated_cwd)
    entry = mgr.add_pov_character("Rex", "A soldier.")
    combo = _make_combo(isolated_cwd, initial_uuid=entry["uuid"])
    qtbot.addWidget(combo)
    assert combo.current_pov() == "Rex"


@pytest.mark.qt
@pytest.mark.integration
def test_current_pov_returns_empty_string_for_none(qtbot, isolated_cwd):
    combo = _make_combo(isolated_cwd, initial_uuid=NONE_CHARACTER_UUID)
    qtbot.addWidget(combo)
    assert combo.current_pov() == ""

