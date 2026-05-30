import json
import os
import re
import uuid
from gettext import gettext as _

from langchain.prompts import PromptTemplate
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QBrush, QFont
from PyQt5.QtWidgets import QDialog, QMenu, QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from compendium.compendium_manager import CompendiumEventBus, CompendiumManager
from settings.llm_api_aggregator import WWApiAggregator
from settings.llm_settings_dialog import LLMSettingsDialog
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager
from settings.llm_settings_dialog import LLMSettingsDialog
from compendium.compendium_manager import CompendiumManager, CompendiumEventBus
from .ai_compendium_dialog import AICompendiumDialog


DEBUG = False

def sanitize(text):
    return re.sub(r'\W+', '', text)

class CompendiumPanel(QWidget):
    def __init__(self, parent=None, enhanced_window=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.project_window = parent
        self.enhanced_window = enhanced_window
        self.project_name = getattr(self.parent().model, "project_name", "default")
        self.event_bus = CompendiumEventBus.get_instance()
        self.manager = CompendiumManager(self.project_name, event_bus=self.event_bus)
        self.event_bus.add_updated_listener(self.update_compendium_tree)
        self.compendium_file = os.path.join(os.getcwd(), "Projects", sanitize(self.project_name), "compendium.json")
        if DEBUG:
            print("New compendium file path:", self.compendium_file)

        project_dir = os.path.dirname(self.compendium_file)
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)

        self.old_compendium_file = os.path.join(os.getcwd(), "compendium.json")
        if os.path.exists(self.old_compendium_file):
            if DEBUG:
                print("Old compendium file found at", self.old_compendium_file)
            try:
                with open(self.old_compendium_file, encoding="utf-8") as f:
                    old_data = json.load(f)
                self.manager.upsert_data(old_data)
                os.remove(self.old_compendium_file)
                if DEBUG:
                    print("Migrated compendium data to", self.compendium_file)
            except Exception as e:
                if DEBUG:
                    print("Error migrating old compendium file:", e)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel(_("Compendium"))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree.currentItemChanged.connect(self.on_item_changed)
        # Double-click will trigger rename via dialog (same as context menu behavior)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.tree)
        self.populate_compendium()

    def populate_compendium(self):
        selected_item_info = self.get_selected_item_info()
        # Build the tree without making items editable (renames use dialog)
        self.tree.clear()
        bold_font = QFont()
        bold_font.setBold(True)

        for cat_info in self.manager.list_categories():
            cat_uuid = cat_info["uuid"]
            cat_name = cat_info["name"]
            if DEBUG:
                print("Category:", cat_name, cat_uuid)
            cat_item = QTreeWidgetItem(self.tree, [cat_name])
            cat_item.setData(0, Qt.UserRole, "category")
            cat_item.setData(0, Qt.ItemDataRole.UserRole + 1, cat_uuid)
            cat_item.setBackground(0, QBrush(ThemeManager.get_category_background_color()))
            cat_item.setFont(0, bold_font)
            # Preserve the canonical entry order from categories[].entries[] instead
            # of forcing an alphabetical sort. The compendium's canonical list
            # should dictate display order.
            for entry in self.manager.list_entries(cat_uuid):
                entry_item = QTreeWidgetItem(cat_item, [entry.get("name", "Unnamed Entry")])
                entry_item.setData(0, Qt.UserRole, "entry")
                entry_item.setData(1, Qt.UserRole, entry.get("content", ""))
                entry_item.setData(2, Qt.UserRole, entry.get("uuid", str(uuid.uuid4())))
            cat_item.setExpanded(True)
        self.restore_selection(selected_item_info)

    def get_selected_item_info(self):
        current_item = self.tree.currentItem()
        if not current_item:
            return None
        item_type = current_item.data(0, Qt.UserRole)
        item_name = current_item.text(0)
        if item_type == "entry":
            entry_uuid = current_item.data(2, Qt.UserRole)
            # Rely on UUID for restoring selection; entries always have UUIDs.
            return {"type": "entry", "name": item_name, "uuid": entry_uuid}
        return {"type": "category", "name": item_name}

    def restore_selection(self, selected_item_info):
        if not selected_item_info:
            return
        item_type = selected_item_info["type"]
        item_name = selected_item_info["name"]
        if item_type == "category":
            for i in range(self.tree.topLevelItemCount()):
                cat_item = self.tree.topLevelItem(i)
                if cat_item.text(0) == item_name and cat_item.data(0, Qt.UserRole) == "category":
                    self.tree.setCurrentItem(cat_item)
                    return
        elif item_type == "entry":
            # Restore selection by UUID only — CompendiumManager guarantees UUIDs.
            entry_uuid = selected_item_info.get("uuid")
            if entry_uuid:
                for i in range(self.tree.topLevelItemCount()):
                    cat_item = self.tree.topLevelItem(i)
                    for j in range(cat_item.childCount()):
                        entry_item = cat_item.child(j)
                        if entry_item.data(2, Qt.UserRole) == entry_uuid:
                            self.tree.setCurrentItem(entry_item)
                            return
        self.tree.clearSelection()

    def on_item_changed(self, current, previous):
        """Display entry content in the main editor."""
        main_editor = self.project_window.compendium_editor
        if current is None:
            main_editor.clear()
            return
        if current.data(0, Qt.UserRole) == "entry":
            content = current.data(1, Qt.UserRole)
            main_editor.setPlainText(content)
        else:
            main_editor.clear()

    def on_item_double_clicked(self, item, column):
        """Open the double-clicked entry in the Enhanced Compendium."""
        if item and item.data(0, Qt.UserRole) == "entry":
            self.open_in_enhanced_compendium()




    def show_tree_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        action_open = menu.addAction(_("Open Enhanced Compendium"))
        action_analyze = menu.addAction(_("Analyze Scene with AI"))
        action = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if action == action_open:
            self.open_in_enhanced_compendium()
        elif action == action_analyze:
            self.analyze_scene_with_ai()

    def open_in_enhanced_compendium(self):
        if not self.enhanced_window:
            QMessageBox.warning(self, _("Error"), _("Enhanced Compendium window not available."))
            return
        entry_name = None
        current_item = self.tree.currentItem()
        if current_item and current_item.data(0, Qt.UserRole) == "entry":
            entry_name = current_item.text(0)
            if entry_name.startswith("* "):
                entry_name = entry_name[2:]
        self.enhanced_window.open_with_entry(self.project_name, entry_name)

    def analyze_scene_with_ai(self):
        scene_editor = self.project_window.scene_editor.editor
        if not scene_editor or not scene_editor.toPlainText():
            QMessageBox.warning(self, _("Warning"), _("No scene content available to analyze."))
            return
        scene_content = scene_editor.toPlainText()
        current_compendium = self.manager.get_summary_for_prompt()
        overrides = LLMSettingsDialog.show_dialog(
            self,
            default_provider=WWSettingsManager.get_active_llm_name(),
            default_model=WWSettingsManager.get_active_llm_config().get("model", None),
            default_timeout=60
        )
        if not overrides:
            return
        analysis_template = PromptTemplate(
            input_variables=["scene_content", "existing_compendium"],
            template="""Analyze the following scene content and existing compendium data. 
Generate or update compendium entries in JSON format for:
1. Major and minor characters (name, personality, description, relationships)
2. Locations (name, description)
3. Key objects (name, description)
4. Significant plot items (name, description)
Compendium entries apply to the entire story, so do not update existing entries for current status.
Scene Content:
{scene_content}
Existing Compendium:
{existing_compendium}
Return only the JSON result without additional commentary. The JSON should maintain the structure:
{{
  "categories": [
    {{
      "name": "category_name",
      "entries": [
        {{
          "name": "entry_name",
          "content": "description and details",
          "relationships": [{{"name": "related_entry", "type": "relationship_type"}}] (optional)
        }}
      ]
    }}
  ]
}}
"""
        )
        prompt = analysis_template.format(
            scene_content=scene_content,
            existing_compendium=current_compendium
        )
        try:
            response = WWApiAggregator.send_prompt_to_llm(prompt, overrides=overrides)
            cleaned_response = self.preprocess_json_string(response)
            repaired_response = self.repair_incomplete_json(cleaned_response)
            if repaired_response is None:
                QMessageBox.warning(self, _("Error"), _("AI returned invalid JSON that could not be repaired."))
                return
            try:
                ai_compendium = json.loads(repaired_response)
            except json.JSONDecodeError:
                QMessageBox.warning(self, _("Error"), _("AI returned invalid JSON format."))
                return
            dialog = AICompendiumDialog(ai_compendium, self.compendium_file, self)
            if dialog.exec_() == QDialog.Accepted:
                self.save_ai_analysis(dialog.get_compendium_data())
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to analyze scene: {}").format(str(e)))

    def preprocess_json_string(self, raw_string):
        cleaned = re.sub(r'^```(?:json)?\s*\n', '', raw_string, flags=re.MULTILINE)
        cleaned = re.sub(r'\n```$', '', cleaned, flags=re.MULTILINE)
        return cleaned.strip()

    def repair_incomplete_json(self, json_str):
        try:
            json.loads(json_str)
            return json_str
        except json.JSONDecodeError:
            repaired = json_str.strip()
            if repaired.endswith('"'):
                repaired += '"'
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            for _ in range(open_braces):
                repaired += '}'
            for _ in range(open_brackets):
                repaired += ']'
            try:
                json.loads(repaired)
                return repaired
            except json.JSONDecodeError:
                return None

    def save_ai_analysis(self, ai_compendium):
        try:
            # Ensure every entry coming back from the AI has the full set of unified
            # fields inline so upsert_data can merge it cleanly.
            for cat in ai_compendium.get("categories", []):
                for entry in cat.get("entries", []):
                    entry.setdefault("uuid", str(uuid.uuid4()))
                    entry.setdefault("details", "")
                    entry.setdefault("tags", [])
                    entry.setdefault("relationships", [])
                    entry.setdefault("images", [])
            # Drop any legacy extensions key that might have been returned by the AI.
            ai_compendium.pop("extensions", None)
            self.manager.upsert_data(ai_compendium)
            self.populate_compendium()
            QMessageBox.information(self, _("Success"), _("Compendium updated successfully."))
        except Exception as e:
            QMessageBox.warning(self, _("Error"), _("Failed to save compendium: {}").format(str(e)))

    def update_compendium_tree(self, project_name):
        if project_name == self.project_name:
            self.populate_compendium()
