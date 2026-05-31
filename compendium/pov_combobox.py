from gettext import gettext as _

from PyQt5.QtWidgets import (
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


class POVComboBox(QComboBox):
    def __init__(self, project_name, initial_pov="Character", parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.selected_pov = initial_pov
        self.event_bus = CompendiumEventBus.get_instance()
        self.compendium = CompendiumManager(project_name, event_bus=self.event_bus)
        self._setup_listener()
        self.populate_combo()
        self.set_to_selected_pov()

    def _setup_listener(self):
        """Register listener and ensure cleanup on destruction."""
        self.event_bus.add_updated_listener(self.on_compendium_updated)
        self.destroyed.connect(self._cleanup_listener)

    def _cleanup_listener(self):
        """Safely remove listener when widget is destroyed."""
        try:
            self.event_bus.remove_updated_listener(self.on_compendium_updated)
        except Exception:
            pass  # Best effort cleanup

    def populate_combo(self) -> None:
        self.clear()
        chars_cat = next(
            (cat for cat in self.compendium.list_categories() if cat["name"].lower() == "characters"),
            None
        )
        if chars_cat:
            # Preserve the compendium's canonical ordering for POV choices
            character_dicts = self.compendium.list_entries(chars_cat["uuid"])
            characters = [d["name"] for d in character_dicts]
        else:
            characters = []
        characters.append(_("Custom..."))
        self.addItems(characters)
        self.currentIndexChanged.connect(self.handle_pov_character_change)

    def handle_pov_character_change(self, index=0):
        value = self.currentText()
        if value == _("New..."):
            dialog = NewCharacterDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                name, description = dialog.get_data()

                # Add to compendium triggers a signal that updates the contents of this combo box
                # unless the user tried to enter a name that already exists.
                self.selected_pov = name
                self.add_character_to_compendium(name, description)
                # No need to update dropdown - compendium update took care of it
            else:
                # Revert to previous selection if canceled
                self.set_to_selected_pov()
                return
        else:
            self.selected_pov = value

    def on_compendium_updated(self, project_name):
        """Safe handler that checks if widget still exists."""
        if not self or self.parent() is None:  # Widget is being destroyed
            return
        if project_name != self.project_name:
            return

        previous_index = self.currentIndex()
        previous_text = self.selected_pov

        self.blockSignals(True)
        try:
            self.populate_combo()  # Rebuild list
        finally:
            self.blockSignals(False)

        self.set_to_selected_pov()
        if self.currentIndex() < 0:
            index = self.findText(previous_text)
            if index >= 0:
                self.setCurrentIndex(index)
            else:
                self.setCurrentIndex(min(previous_index, self.count() - 1))

    def set_to_selected_pov(self):
        """Restore selection safely."""
        if not self:
            return
        index = self.findText(self.selected_pov)
        if index >= 0:
            self.blockSignals(True)
            self.setCurrentIndex(index)
            self.blockSignals(False)
        elif self.count() > 0:
            value = self.currentText()
            if (value and value != _("Custom...")):
                self.selected_pov = value
            else: # User Canceled custom char
                self.blockSignals(True)
                self.setCurrentIndex(0)
                self.blockSignals(False)

    def add_character_to_compendium(self, name, description):
        try:
            chars_cat = next(
                (cat for cat in self.compendium.list_categories() if cat["name"].lower() == "characters"),
                None
            )
            if not chars_cat:
                chars_cat = self.compendium.add_category("Characters")
            entries = self.compendium.list_entries(chars_cat["uuid"])
            existing = next((e for e in entries if e["name"] == name), None)
            if existing:
                self.compendium.update_entry(existing["uuid"], {"content": description})
            else:
                self.compendium.add_entry(chars_cat["uuid"], name, description)
        except Exception as e:
            print(f"Error saving compendium: {e}")
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium: {}").format(str(e)))

    def current_pov(self) -> str:
        """Public API for other classes to get current selection."""
        return self.selected_pov if self.selected_pov != _("Custom...") else self.currentText()

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

    def ok_button_pressed(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, _("Add new Character"), _("Character name cannot be empty."))
            return
        self.accept()

    def get_data(self):
        return self.name_input.text().strip(), self.description_input.toPlainText().strip()
