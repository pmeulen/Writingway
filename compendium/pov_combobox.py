from __future__ import annotations

import contextlib
from dataclasses import dataclass
from gettext import gettext as _
from typing import Literal

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .compendium_manager import CompendiumEventBus, CompendiumManager

# ---------------------------------------------------------------------------
# Sentinel UUIDs - fixed strings that never collide with real uuid4 entries
# ---------------------------------------------------------------------------
NONE_CHARACTER_UUID: str = "00000000-0000-0000-0000-000000000000"
NEW_CHARACTER_UUID: str = "ffffffff-ffff-ffff-ffff-ffffffffffff"

@dataclass(frozen=True)
class POVItemData:
    """Typed payload stored in Qt.ItemDataRole.UserRole for each combo item."""
    uuid: str
    kind: Literal["entry", "none", "new"]


class POVComboBox(QComboBox):
    """Combo box for selecting a POV character from the compendium.

    Emits ``pov_uuid_changed(str)`` whenever the confirmed selection changes.
    The signal carries the UUID of the selected entry, or ``NONE_CHARACTER_UUID``
    when *<none>* is selected.
    """

    pov_uuid_changed: pyqtSignal = pyqtSignal(str)

    def __init__(self, project_name: str, initial_uuid: str = NONE_CHARACTER_UUID, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.event_bus = CompendiumEventBus.get_instance()
        self.compendium = CompendiumManager(project_name, event_bus=self.event_bus)

        self.selected_uuid: str = initial_uuid

        # Connect signal exactly once here (not inside populate_combo).
        self.currentIndexChanged.connect(self.handle_pov_character_change)

        self._setup_listener()
        self.populate_combo()
        self.set_to_selected_pov()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup_listener(self) -> None:
        """Register compendium-updated listener and ensure cleanup on destruction."""
        self.event_bus.add_updated_listener(self.on_compendium_updated)
        self.destroyed.connect(self._cleanup_listener)

    def _cleanup_listener(self) -> None:
        """Safely remove listener when widget is destroyed."""
        with contextlib.suppress(Exception):
            self.event_bus.remove_updated_listener(self.on_compendium_updated)

    # ------------------------------------------------------------------
    # Populating / restoring
    # ------------------------------------------------------------------

    def populate_combo(self) -> None:
        """Rebuild combo contents from the compendium. Signal is already connected."""
        self.blockSignals(True)
        try:
            self.clear()
            # <none> first - grayed out like a disabled menu item (uses palette, not hardcoded)
            self.addItem(_("<none>"))
            self.setItemData(0, POVItemData(uuid=NONE_CHARACTER_UUID, kind="none"), Qt.ItemDataRole.UserRole)

            for i, entry in enumerate(self.compendium.list_pov_characters(), start=1):
                self.addItem(entry["name"])
                self.setItemData(i, POVItemData(uuid=entry["uuid"], kind="entry"), Qt.ItemDataRole.UserRole)

            # New... last - bold to signal it is an action, not a character name
            last = self.count()
            self.addItem(_("New..."))
            self.setItemData(last, POVItemData(uuid=NEW_CHARACTER_UUID, kind="new"), Qt.ItemDataRole.UserRole)
            bold_font = QFont(self.font())
            bold_font.setWeight(QFont.Weight.Bold)
            self.setItemData(last, bold_font, Qt.ItemDataRole.FontRole)
        finally:
            self.blockSignals(False)

    def set_to_selected_pov(self) -> None:
        """Restore combo selection to ``self.selected_uuid`` without firing signals."""
        if not self:
            return
        self.blockSignals(True)
        try:
            for i in range(self.count()):
                data: POVItemData | None = self.itemData(i, Qt.ItemDataRole.UserRole)
                if data is not None and data.uuid == self.selected_uuid:
                    self.setCurrentIndex(i)
                    return
            # UUID not found - fall back to <none>
            self.setCurrentIndex(0)
            self.selected_uuid = NONE_CHARACTER_UUID
        finally:
            self.blockSignals(False)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_pov_character_change(self, index: int = 0) -> None:
        data: POVItemData | None = self.itemData(index, Qt.ItemDataRole.UserRole)
        if data is None:
            return

        if data.kind == "new":
            dialog = NewCharacterDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                name, description = dialog.get_data()
                # add_pov_character returns the entry dict including its UUID
                entry = self.compendium.add_pov_character(name, description)
                self.selected_uuid = entry["uuid"]
                # on_compendium_updated will repopulate; emit the signal now so
                # callers get the UUID immediately (no flicker to <none>).
                self.pov_uuid_changed.emit(self.selected_uuid)
            else:
                # User cancelled - revert
                self.set_to_selected_pov()
        elif data.kind in ("entry", "none"):
            self.selected_uuid = data.uuid
            self.pov_uuid_changed.emit(self.selected_uuid)

    def on_compendium_updated(self, project_name: str) -> None:
        """Repopulate when the compendium changes, restoring current selection."""
        try:
            _ = self.count()  # Will raise RuntimeError if C++ object is deleted
        except RuntimeError:
            return
        if project_name != self.project_name:
            return
        self.populate_combo()
        self.set_to_selected_pov()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_uuid(self) -> str:
        """Return the UUID of the currently confirmed selection."""
        return self.selected_uuid

    def current_pov(self) -> str:
        """Return the display name for the current selection (empty string for <none>).

        Looks up the name via the compendium so it stays in sync with renames.
        """
        if self.selected_uuid == NONE_CHARACTER_UUID:
            return ""
        entry = self.compendium.get_entry_by_uuid(self.selected_uuid)
        return entry["name"] if entry else ""

    def add_character_to_compendium(self, name: str, description: str) -> None:
        """[Legacy] Add/update a character. Prefer ``compendium.add_pov_character`` directly."""
        try:
            self.compendium.add_pov_character(name, description)
        except Exception as e:
            print(f"Error saving compendium: {e}")
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium: {}").format(str(e)))


class NewCharacterDialog(QDialog):
    """Dialog for entering a compendium character name and description."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Add new Character"))
        self.setModal(True)
        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(_("Enter character name"))
        form_layout.addRow(_("Name:"), self.name_input)

        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText(_("(Optional) Enter details for new compendium entry..."))
        self.description_input.setMinimumHeight(100)
        form_layout.addRow(_("Description:"), self.description_input)

        layout.addLayout(form_layout)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton(_("OK"))
        self.cancel_button = QPushButton(_("Cancel"))
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.ok_button.clicked.connect(self.ok_button_pressed)
        self.cancel_button.clicked.connect(self.reject)

    def ok_button_pressed(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, _("Add new Character"), _("Character name cannot be empty."))
            return
        self.accept()

    def get_data(self) -> tuple[str, str]:
        return self.name_input.text().strip(), self.description_input.toPlainText().strip()
