import json
import os
import re
import weakref
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from settings.settings_manager import WWSettingsManager
from PyQt5.QtWidgets import QMessageBox


class CompendiumEventBus:
    _instance = None

    def __init__(self):
        self.updated_listeners: list[Callable[[str], None]] = []
        self._weak_refs: weakref.WeakSet = weakref.WeakSet()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_updated_listener(self, callback: Callable[[str], None]):
        self.updated_listeners.append(callback)
        if hasattr(callback, '__self__'):
                self._weak_refs.add(callback.__self__)

    def remove_updated_listener(self, callback: Callable[[str], None]):
        """Safely remove a listener."""
        if callback in self.updated_listeners:
            self.updated_listeners.remove(callback)

    def notify_updated(self, project_name: str):
        self._cleanup_dead_listeners()
        for callback in self.updated_listeners:
            try:
                callback(project_name)
            except Exception as e:
                print(f"Error in compendium updated listener: {e}")
                self.remove_updated_listener(callback)

    def _cleanup_dead_listeners(self):
        """Remove listeners whose objects have been garbage collected."""
        to_remove = []
        for cb in self.updated_listeners:
            if hasattr(cb, '__self__') and cb.__self__ is None:
                to_remove.append(cb)
        for cb in to_remove:
            self.remove_updated_listener(cb)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
# Compendium data is stored in <project>/compendium.json as a single unified
# section:
#
#   "categories": [
#       {
#         "name": str,               ← category name
#         "entries": [               ← entries in this category
#         {
#           "name",
#           "content",
#           "uuid",
#           "details",
#           "tags": [],
#           "relationships": [],
#           "images": []
#   } ] } ]
#
# Legacy "split" format (extensions section keyed by entry name) is
# migrated automatically on first load; the extensions section is then
# removed and the file is re-saved in unified format.
# ---------------------------------------------------------------------------


class CompendiumManager:
    """Manages compendium data loading, retrieval, and reference parsing for a project."""

    # ------------------------------------------------------------------
    # Canonical structure factories
    # ------------------------------------------------------------------

    @staticmethod
    def make_empty_entry(name: str, content: str = "") -> Dict[str, Any]:
        """Return a new, fully-initialised entry dict in the unified format.

        All callers that need to create an entry should use this factory so
        that the canonical set of fields is defined in exactly one place.

        Returns:
            dict: ``{"name", "content", "uuid", "details", "tags", "relationships", "images"}``
        """
        return {
            "name": name,
            "content": content,
            "uuid": str(uuid4()),
            "details": "",
            "tags": [],
            "relationships": [],
            "images": [],
        }

    @staticmethod
    def make_empty_category(name: str) -> Dict[str, Any]:
        """Return a new, fully-initialised category dict.

        Returns:
            dict: ``{"name", "uuid", "entries"}``
        """
        return {
            "name": name,
            "uuid": str(uuid4()),
            "entries": [],
        }

    def __init__(self, project_name: str | None = None, event_bus: CompendiumEventBus | None = None):
        """
        Initialize the CompendiumManager with an optional project name.

        Args:
            project_name (str, optional): The name of the project. If None, uses a global compendium file.
        """
        self.project_name = project_name
        self.event_bus = event_bus
        self._filepath = self._get_filepath()
        self._ensure_file_exists()

    def _get_filepath(self) -> str:
        """
        Build the compendium file path based on the project name.

        Returns:
            str: Path to the compendium JSON file.
        """
        if self.project_name:
            return WWSettingsManager.get_project_relpath(self.project_name, "compendium.json")
        return os.path.join(os.getcwd(), "compendium.json")

    def _ensure_file_exists(self) -> None:
        """Ensure the compendium file exists, creating a default one if necessary."""
        if not os.path.exists(self._filepath):
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            default_data = {
                "version": 3,
                "categories": [self.make_empty_category("Characters")],
            }
            self._save_data(default_data)

    def _backup_compendium_data(self) -> str:
        """Create a filesystem backup copy of the current compendium file.

        The backup filename is the original filename with the current date/time
        appended (format: YYYYMMDD_HHMMSS). If the copy operation fails an
        exception is raised.

        Returns:
            str: The path to the created backup file.
        """

        # If file doesn't exist, nothing to back up.
        if not os.path.exists(self._filepath):
            raise FileNotFoundError(f"Compendium file does not exist: {self._filepath}")

        import shutil
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self._filepath}.{timestamp}"

        try:
            # copy2 preserves metadata where possible
            shutil.copy2(self._filepath, backup_path)
        except Exception as e:
            raise IOError(f"Failed to backup compendium file {self._filepath} to {backup_path}: {e}") from e

        return backup_path

    def _load_data(self) -> dict[str, Any]:
        """
        Load compendium data from the project-specific file, converting legacy formats if needed.

        Returns:
            dict: Compendium data with a 'categories' key containing a list of category objects.
        """
        if not os.path.exists(self._filepath):
            self._ensure_file_exists()

        changed = False
        current_version = 3

        default_compendium_data = {
            "categories": [
                {
                    "version": current_version,
                    "name": "Characters",
                    "uuid": str(uuid4()),
                 "entries": [
                     {
                         "name": "Alice",
                         "uuid": str(uuid4()),
                         "content": "A brave adventurer.",
                         "tags": [],
                         "relations": [],
                         "images": [],
                     }
                 ],
                 },
            ],
        }

        try:
            with open(self._filepath, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {self._filepath}: {e}. Initializing a new compendium.")
            data = default_compendium_data
            changed = True
        except Exception as e:
            print(f"Error loading compendium data from {self._filepath}: {e}. . Initializing a new compendium.")
            data = default_compendium_data
            changed = True

        # Check if file version is newer than what this code understands.
        version = data.get("version", 1)
        if version > current_version:
            print(f"Warning: Compendium data version {version} is newer than supported version {current_version}.")

            msg = (
                f"Compendium data version {version} is newer than the supported version {current_version}.\n\n"
                "Compendium functionality may not work correctly with this application version.\n"
                "If you continue and save the compendium, you may lose data.\n\n"
                f"File: {self._filepath}"
            )
            QMessageBox.warning(None, "Compendium version mismatch", msg, QMessageBox.Ok)

            # Don't attempt convert the data, since we don't know the format. Return as-is.
            return False

        # Ensure essential keys exist
        if not data["categories"]:
            data["categories"] = [  ]
            changed = True

        # Convert legacy dict format to list of categories
        if isinstance(data["categories"], dict):
            print("Converting compendium legacy dict format to list of categories")
            new_categories = [
                {"name": cat, "entries": [
                    {"name": name, "content": content, "uuid": str(uuid4())}
                    for name, content in entries.items()
                ]} for cat, entries in data["categories"].items()
            ]
            data["categories"] = new_categories
            changed = True

        # Ensure every entry and category has an unique uuid
        seen_uuids = set()
        for cat in data.get("categories", []):
            if not cat.get("uuid"):
                print("Fixing compendium category missing UUID")
                cat["uuid"] = str(uuid4())
                changed = True

            uuid = cat.get("uuid")
            # If category has no uuid, give it one
            if uuid in seen_uuids:
                new_uuid = str(uuid4())
                print(f"UUID {uuid} is already used by another compendium category. Assigning UUID {new_uuid}")
                cat["uuid"] = new_uuid
                changed = True
            seen_uuids.add(uuid)

            for entry in cat.get("entries", []):
                # If entry has no uuid, give it one
                if not entry.get("uuid"):
                    print("Fixing compendium entry missing UUID")
                    entry["uuid"] = str(uuid4())
                    changed = True

                # If category has no name, give it one
                name: str = entry.get("name", "")
                if len(name) == 0:
                    print("Fixing compendium category missing name")
                    id = cat.get("uuid")
                    cat["name"] = f"Category {id}"
                    changed = True

                # Ensure uuid is unique across all entries. If not, give it a new one.
                uuid = entry.get("uuid")
                if uuid in seen_uuids:
                    # Duplicate uuid found
                    new_uuid = str(uuid4())
                    print(f"UUID {uuid} is already used by another compendium entry. Assigning UUID {new_uuid}")
                    entry["uuid"] = new_uuid
                    changed = True

                # If entry has no name, give it an unique name
                name: str = entry.get("name", "")
                if len(name) == 0:
                    id = entry.get("uuid")
                    entry["name"] = f"Entry {id}"
                    changed = True

        if "extensions" in data:
            # Migrate from format with extensions to unified format
            print("Converting compendium from format with extensions to unified format")
            changed = True

            # Build lookup from extensions -> entries
            ext_entries = data.get("extensions", {}).get("entries", {})

            # Lookup each entry by name in the extensions. The name of the entry is the key in extensions
            # Name is not necessarily unique, but this is an issue in the old data format and won't cause data loss, only duplication
            for cat in data["categories"]:
                for entry in cat.get("entries", []):
                    entry_name = entry.get("name")

                    # Copy fields from entries, set to default otherwise
                    extension_data = ext_entries.get(entry_name) or {}
                    entry["details"] = extension_data.get("details", "")
                    entry["tags"] = extension_data.get("tags", [])
                    entry["relationships"] = extension_data.get("relationships", [])
                    entry["images"] = extension_data.get("images", [])

            # Remove the now redundant extensions section.
            if "extensions" in data:
                del data["extensions"]

            # Add version
            data["version"] = 3

        if changed:
            # Create a backup of the old file before saving the new one, to prevent of data loss because of bugs in
            # the conversion code
            backup_name = self._backup_compendium_data()
            print(f"Backed up compendium data to {backup_name}")
            compendium_name = self._save_data(data)
            print(f"Saved compendium data to {compendium_name}")

        return data

    def load_data(self) -> dict[str, Any]:
        return self._load_data()

    def _save_data(self, compendium_data: dict[str, Any]) -> str:
        """
        Save compendium data to the file.
        Return filename

        Args:
            compendium_data (dict): The compendium data to save.
        """
        try:
            os.makedirs(os.path.dirname(self._filepath), exist_ok=True)
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(compendium_data, f, indent=2)
            if self.event_bus:
                self.event_bus.notify_updated(self.project_name)
        except Exception as e:
            print(f"Error saving compendium data to {self._filepath}: {e}")

        return self._filepath

    def save_data(self, compendium_data: dict[str, Any]) -> None:
        self._save_data(compendium_data)

    def get_category(self, category: str) -> list[dict[str, str]]:
        data = self._load_data()
        categories = data.get("categories", [])
        for cat in categories:
            if cat.get("name") == category:
                return cat.get("entries", [])
        return []

    def get_characters(self) -> list[str]:
        character_dicts = self.get_category("Characters")
        characters = [d['name'] for d in character_dicts]
        characters.sort()
        return characters

    def get_text(self, category: str, entry: str) -> str:
        """
        Retrieve the text content for a given category and entry.

        Args:
            category (str): The category name.
            entry (str): The entry name within the category.

        Returns:
            str: The content of the entry, or a placeholder if not found.
        """
        data = self._load_data()
        categories = data.get("categories", [])
        for cat in categories:
            if cat.get("name") == category:
                for e in cat.get("entries", []):
                    if e.get("name") == entry:
                        return e.get("content", f"[No content for {entry} in category {category}]")
        return f"[No content for {entry} in category {category}]"

    def parse_references(self, message: str) -> list[str]:
        """
        Parse compendium references from a message by matching entry names.

        Args:
            message (str): The text to search for references.

        Returns:
            list: A list of entry names found in the message.
        """
        refs = []
        try:
            data = self._load_data()
            names = [entry.get("name", "") for cat in data.get("categories", [])
                     for entry in cat.get("entries", [])]
            for name in names:
                if name and re.search(r'\b' + re.escape(name) + r'\b', message, re.IGNORECASE):
                    refs.append(name)
        except Exception as e:
            print(f"Error parsing compendium references: {e}")
        return refs

    def add_character(self, name, description) -> None:
        """Add a new character to the compendium.json file."""
        compendium_data = self._load_data()

        # Find or create Characters category
        characters_cat = None
        for cat in compendium_data.get("categories", []):
            if cat.get("name", "").lower() == "characters":
                characters_cat = cat
                break
        if not characters_cat:
            characters_cat = self.make_empty_category("Characters")
            compendium_data["categories"].append(characters_cat)

        # Update existing entry or add a new one using the canonical unified structure.
        for entry in characters_cat.get("entries", []):
            if entry.get("name") == name:
                entry["content"] = description
                if "uuid" not in entry:
                    entry["uuid"] = str(uuid4())
                # Ensure all unified fields are present on legacy entries.
                entry.setdefault("details", "")
                entry.setdefault("tags", [])
                entry.setdefault("relationships", [])
                entry.setdefault("images", [])
                break
        else:
            # New character — create a fully-initialised unified entry.
            characters_cat["entries"].append(self.make_empty_entry(name, description))
        self._save_data(compendium_data)

    def upsert_data(self, compendium_data: dict[str, Any]) -> None:
        """Merge compendium_data with the existing compendium content.

        Both the incoming data and the stored data are expected to be in the
        unified format (all entry fields inline; no ``extensions`` section).
        Any ``extensions`` key present in the incoming data is ignored so that
        callers cannot accidentally re-introduce the legacy split format.
        """
        existing_data = self._load_data()

        # Merge categories
        existing_categories = {cat["name"]: cat for cat in existing_data.get("categories", [])}
        for new_cat in compendium_data.get("categories", []):
            if new_cat["name"] in existing_categories:
                existing_entries = {entry["name"]: entry for entry in existing_categories[new_cat["name"]].get("entries", [])}
                for new_entry in new_cat.get("entries", []):
                    # Ensure every incoming entry has the full set of unified fields
                    # before merging so that partial entries don't wipe existing data.
                    full_entry = {**self.make_empty_entry(new_entry.get("name", ""), new_entry.get("content", "")),
                                  **new_entry}
                    if full_entry["name"] in existing_entries:
                        existing_entries[full_entry["name"]].update(full_entry)
                    else:
                        existing_categories[new_cat["name"]]["entries"].append(full_entry)
            else:
                existing_data["categories"].append(new_cat)

        self._save_data(existing_data)
