import json
import logging
import os
import re
import weakref
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

logger = logging.getLogger(__name__)

from PyQt5.QtWidgets import QMessageBox

from compendium.compendium_types import (
    CategorySummary,
    CompendiumCategory,
    CompendiumData,
    CompendiumEntry,
    EntryWithContext,
    PovCharacter,
)
from settings.settings_manager import WWSettingsManager


class CompendiumEventBus:
    _instance = None

    def __init__(self):
        self.updated_listeners: list[Callable[[str], None]] = []
        self._weak_refs: weakref.WeakSet = weakref.WeakSet()

    @classmethod
    def get_instance(cls) -> "CompendiumEventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_updated_listener(self, callback: Callable[[str], None]):
        self.updated_listeners.append(callback)
        callback_self = getattr(callback, "__self__", None)
        if callback_self is not None:
            self._weak_refs.add(callback_self)

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
                logger.error(f"Error in compendium updated listener: {e}")
                self.remove_updated_listener(callback)

    def _cleanup_dead_listeners(self):
        """Remove listeners whose objects have been garbage collected."""
        to_remove = []
        for cb in self.updated_listeners:
            if getattr(cb, "__self__", object()) is None:
                to_remove.append(cb)
        for cb in to_remove:
            self.remove_updated_listener(cb)


class CompendiumManager:
    """
    Manages compendium data loading, retrieval, updating and reference parsing for a
    project's compendium.
    """

    # ---------------------------------------------------------------------------
    # Data model version 3
    # ---------------------------------------------------------------------------
    # Compendium data is stored in <project>/compendium.json as a single unified
    # section:
    #   {
    #   "version": int,               # data model version (current: 3, default: 1)
    #   "categories": [
    #       {
    #         "name": str,            # category name
    #         "uuid": str,            # category uuid
    #         "entries": [            # entries in this category
    #         {
    #           "name",               # entry name
    #           "uuid",               # entry uuid
    #           "content",            # entry content. Sent to the LLM
    #           "details",            # entry details. For the user. Not sent to the LLM
    #           "tags": [             # list of tags
    #             {
    #               "name": str,      # tag name
    #               "color": str      # tag color. Hex code, e.g. "#ff0000"
    #             }
    #           ],
    #           "relationships": [    # list of relationships to other entries.
    #             {
    #               "uuid": str       # uuid of the related entry
    #               "type": str       # relationship type with the related entry, e.g. "parent", "ally"
    #              }
    #           ],
    #           "images": [
    #             str,                # path to the image file on disk
    #           ]
    #   } ] } ]
    #
    # Legacy v2 "split" format (extensions section keyed by entry name) is
    # migrated automatically on first load; the extensions section is then
    # removed and the file is re-saved in unified format.
    # ---------------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Canonical structure factories
    # ------------------------------------------------------------------

    @staticmethod
    def make_empty_entry(name: str, content: str = "") -> CompendiumEntry:
        """Return a new, fully-initialised entry dict in the unified format.

        All callers that need to create an entry should use this factory so
        that the canonical set of fields is defined in exactly one place.
        """
        return CompendiumEntry(
            name=name,
            content=content,
            uuid=str(uuid4()),
            details="",
            tags=[],
            relationships=[],
            images=[],
        )

    @staticmethod
    def make_empty_category(name: str) -> CompendiumCategory:
        """Return a new, fully-initialised category dict."""
        return CompendiumCategory(
            name=name,
            uuid=str(uuid4()),
            entries=[],
        )

    def make_empty_compendium(self) -> CompendiumData:
        """Return a new, fully-initialised compendium dict."""
        return CompendiumData(
            version=3,
            categories=[self.make_empty_category("Characters")],
        )

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
        self._show_new_version_warning = True

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
            default_data: CompendiumData = {
                "version": 3,
                "categories": [self.make_empty_category("Characters")],
            }
            # Startup bootstrap should not broadcast update events.
            self._save_data(default_data, notify=False)

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
            raise OSError(f"Failed to backup compendium file {self._filepath} to {backup_path}: {e}") from e

        return backup_path

    def _load_data(self) -> CompendiumData:
        """
        Load compendium data from the project-specific file, converting legacy formats if needed.
        Warns the user when loading a file with a newer version than the code supports,
        but still attempts to load it with all conversion logic disabled.

        Returns:
            dict: Compendium data with a 'categories' key containing a list of category objects.
        """
        if not os.path.exists(self._filepath):
            self._ensure_file_exists()

        changed = False
        current_version = 3
        data = None

        try:
            with open(self._filepath, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {self._filepath}: {e}. Initializing a new compendium.")
            data = self.make_empty_compendium()
            changed = True
        except Exception as e:
            logger.error(f"Error loading compendium data from {self._filepath}: {e}. Initializing a new compendium.")
            data = self.make_empty_compendium()
            changed = True

        if not isinstance(data, dict):
            logger.warning(f"Invalid compendium payload in {self._filepath}. Initializing a new compendium.")
            data = self.make_empty_compendium()
            changed = True

        # Check if file version is newer than what this code understands.
        version = data.get("version", 1)
        if isinstance(version, int) and version > current_version:
            logger.warning(f"Compendium data version {version} is newer than supported version {current_version}.")
            if self._show_new_version_warning:
                msg = (
                    f"Compendium data version {version} is newer than the supported version {current_version}.\n\n"
                    "Compendium functionality may not work correctly with this application version.\n"
                    "If you continue and save the compendium, you may lose data.\n\n"
                    f"File: {self._filepath}"
                )
                QMessageBox.warning(None, "Compendium version mismatch", msg, QMessageBox.Ok)

                # Show warning only once per project session
                self._show_new_version_warning=False

            # Don't attempt convert the data, since we don't know the format. Return as-is.
            return data

        # Ensure essential keys exist with a stable shape.
        categories_raw = data.get("categories")
        if categories_raw is None or not isinstance(categories_raw, (list, dict)):
            data["categories"] = []
            changed = True

        # Convert legacy dict format (version 1) to list of categories
        categories_dict = data.get("categories")
        if isinstance(categories_dict, dict):
            logger.info("Converting compendium legacy dict format to list of categories")
            new_categories = [
                {"name": cat, "entries": [
                    {"name": name, "content": content, "uuid": str(uuid4())}
                    for name, content in entries.items()
                    if isinstance(entries, dict)
                ]} for cat, entries in categories_dict.items()
            ]
            data["categories"] = new_categories
            changed = True

        # Ensure every entry and category has an unique uuid
        seen_uuids: set[str] = set()
        categories = data.get("categories", [])
        if not isinstance(categories, list):
            categories = []
            data["categories"] = categories
            changed = True

        normalized_categories: list[dict[str, Any]] = []
        for cat in categories:
            if not isinstance(cat, dict):
                changed = True
                continue

            cat_uuid_value = cat.get("uuid")
            cat_uuid = cat_uuid_value if isinstance(cat_uuid_value, str) and cat_uuid_value else ""
            if not cat_uuid:
                logger.info("Fixing compendium category missing UUID")
                cat_uuid = str(uuid4())
                cat["uuid"] = cat_uuid
                changed = True

            # If category has no uuid, give it one
            if cat_uuid in seen_uuids:
                new_uuid = str(uuid4())
                logger.warning(f"UUID {cat_uuid} is already used by another compendium category. Assigning UUID {new_uuid}")
                cat["uuid"] = new_uuid
                cat_uuid = new_uuid
                changed = True
            seen_uuids.add(cat_uuid)

            cat_name_value = cat.get("name")
            if not isinstance(cat_name_value, str) or len(cat_name_value) == 0:
                cat["name"] = f"Category {cat_uuid}"
                changed = True

            entries_raw = cat.get("entries", [])
            if not isinstance(entries_raw, list):
                entries_raw = []
                cat["entries"] = entries_raw
                changed = True

            normalized_entries: list[dict[str, Any]] = []
            for entry in entries_raw:
                if not isinstance(entry, dict):
                    changed = True
                    continue

                # If entry has no uuid, give it one
                entry_uuid_value = entry.get("uuid")
                entry_uuid = entry_uuid_value if isinstance(entry_uuid_value, str) and entry_uuid_value else ""
                if not entry_uuid:
                    logger.info("Fixing compendium entry missing UUID")
                    entry_uuid = str(uuid4())
                    entry["uuid"] = entry_uuid
                    changed = True

                # Ensure uuid is unique across all entries. If not, give it a new one.
                if entry_uuid in seen_uuids:
                    # Duplicate uuid found
                    new_uuid = str(uuid4())
                    logger.warning(f"UUID {entry_uuid} is already used by another compendium entry. Assigning UUID {new_uuid}")
                    entry["uuid"] = new_uuid
                    entry_uuid = new_uuid
                    changed = True
                seen_uuids.add(entry_uuid)

                # If entry has no name, give it an unique name
                name_value = entry.get("name", "")
                name = name_value if isinstance(name_value, str) else ""
                if len(name) == 0:
                    entry["name"] = f"Entry {entry_uuid}"
                    changed = True

                normalized_entries.append(entry)

            cat["entries"] = normalized_entries
            normalized_categories.append(cat)

        data["categories"] = normalized_categories

        # Migrate name-based relationships to UUID-based.
        # Legacy data (written by ai_compendium_dialog) uses {"name": str, "type": str}.
        # The canonical format uses {"uuid": str, "type": str}.
        name_to_uuid: dict[str, str] = {
            entry.get("name", ""): entry.get("uuid", "")
            for cat in data.get("categories", [])
            for entry in cat.get("entries", [])
            if entry.get("name") and entry.get("uuid")
        }
        for cat in data.get("categories", []):
            for entry in cat.get("entries", []):
                for rel in entry.get("relationships", []):
                    if not isinstance(rel, dict):
                        continue
                    if "uuid" not in rel and "name" in rel:
                        rel_name = rel.get("name", "")
                        resolved_uuid = name_to_uuid.get(rel_name, "")
                        rel["uuid"] = resolved_uuid
                        del rel["name"]
                        changed = True
                        if resolved_uuid:
                            logger.info(
                                f"Migrated name-based relationship '{rel_name}' "
                                f"to UUID '{resolved_uuid}'"
                            )
                        else:
                            logger.warning(
                                f"Could not resolve relationship name "
                                f"'{rel_name}' to UUID; related entry may have been deleted"
                            )

        if "extensions" in data:
            # Migrate from format with extensions to unified format
            logger.info("Converting compendium from format with extensions to unified format")
            changed = True

            # Build lookup from extensions -> entries
            extensions_data = data.get("extensions", {})
            ext_entries = extensions_data.get("entries", {}) if isinstance(extensions_data, dict) else {}

            # Lookup each entry by name in the extensions. The name of the entry is the key in extensions
            # Name is not necessarily unique, but this is an issue in the old data format and won't cause data loss, only duplication
            for cat in data["categories"]:
                entries = cat.get("entries", []) if isinstance(cat, dict) else []
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry_name = entry.get("name")
                    if not isinstance(entry_name, str):
                        entry_name = ""

                    # Copy fields from entries, set to default otherwise
                    extension_data = ext_entries.get(entry_name) if isinstance(ext_entries, dict) else {}
                    if not isinstance(extension_data, dict):
                        extension_data = {}
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
            logger.info(f"Backed up compendium data to {backup_name}")
            # Internal migration/normalization writes should not re-enter UI listeners.
            compendium_name = self._save_data(cast(CompendiumData, data), notify=False)
            logger.info(f"Saved compendium data to {compendium_name}")

        return cast(CompendiumData, data)

    def load_data(self) -> CompendiumData:
        """Load compendium data from file.
        It is automatically converted from an older format to version 3 format.
        Newer file format versions are not converted and are loaded as-is with a warning.

        """
        # TODO: We may want to add a cache to prevent loading the data each time

        # Load data from disk, converting legacy format if necessary.
        return self._load_data()

    def _save_data(self, compendium_data: CompendiumData, notify: bool = True) -> str:
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
            if notify and self.event_bus and isinstance(self.project_name, str):
                self.event_bus.notify_updated(self.project_name)
        except Exception as e:
            logger.error(f"Error saving compendium data to {self._filepath}: {e}")

        return self._filepath


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
            names: list[str] = [entry.get("name", "") for cat in data.get("categories", [])
                     for entry in cat.get("entries", [])]
            for name in names:
                if name and re.search(r'\b' + re.escape(name) + r'\b', message, re.IGNORECASE):
                    refs.append(name)
        except Exception as e:
            logger.error(f"Error parsing compendium references: {e}")
        return refs

    def add_character(self, name: str, description: str) -> None:
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

    def upsert_data(self, compendium_data: CompendiumData) -> None:
        """Merge compendium_data with the existing compendium content.

        Both the incoming data and the stored data are expected to be in the
        unified format. The `extenstions` format is not supported and data under this key is ignored.
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

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def list_categories(self) -> list[CategorySummary]:
        """Return a summary list of all categories.

        Returns:
            list of ``CategorySummary`` dicts (in display order).
        """
        data = self._load_data()
        return [CategorySummary(name=cat.get("name", ""), uuid=cat.get("uuid", ""))
                for cat in data.get("categories", [])]

    def get_category_by_uuid(self, category_uuid: str) -> CompendiumCategory | None:
        """Return the full category dict (including its ``entries`` list) for *category_uuid*.

        Returns:
            The category dict, or ``None`` if not found.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("uuid") == category_uuid:
                return cat
        return None

    def list_entries(self, category_uuid: str) -> list[CompendiumEntry]:
        """Return all entry dicts for the category identified by *category_uuid*.

        Returns:
            List of entry dicts, or an empty list if the category is not found.
        """
        cat = self.get_category_by_uuid(category_uuid)
        return cat.get("entries", []) if cat else []

    def get_entry_by_uuid(self, entry_uuid: str) -> CompendiumEntry | None:
        """Return the entry dict whose ``uuid`` matches *entry_uuid*, or ``None``."""
        data = self._load_data()
        for cat in data.get("categories", []):
            for entry in cat.get("entries", []):
                if entry.get("uuid") == entry_uuid:
                    return entry
        return None

    def find_categories(self, search_text: str = "") -> dict[str, CategorySummary]:
        """Return categories whose name contains *search_text*, keyed by UUID.

        An empty *search_text* returns every category.

        Returns:
            ``{category_uuid: CategorySummary, ...}``
        """
        lower = search_text.lower()
        data = self._load_data()
        results: dict[str, CategorySummary] = {}
        for cat in data.get("categories", []):
            cat_name = cat.get("name", "")
            if not lower or lower in cat_name.lower():
                uuid = cat.get("uuid", "")
                results[uuid] = CategorySummary(name=cat_name, uuid=uuid)
        return results

    def find_entries(self, search_text: str = "") -> dict[str, EntryWithContext]:
        """Return entries whose name or tag names contain *search_text*, keyed by UUID.

        An empty *search_text* returns every entry.  Each value contains all
        standard entry fields plus a ``"category_uuid"`` key and a ``"category_name"``
        key for the containing category.

        Returns:
            ``{entry_uuid: EntryWithContext, ...}``
        """
        lower = search_text.lower()
        data = self._load_data()
        results: dict[str, EntryWithContext] = {}
        for cat in data.get("categories", []):
            cat_name = cat.get("name", "")
            cat_uuid = cat.get("uuid", "")
            for entry in cat.get("entries", []):
                entry_name = entry.get("name", "").lower()
                tag_names = [
                    (t.get("name", "") if isinstance(t, dict) else t).lower()
                    for t in entry.get("tags", [])
                ]
                if not lower or lower in entry_name or any(lower in t for t in tag_names):
                    entry_uuid = entry.get("uuid", "")
                    results[entry_uuid] = EntryWithContext(
                        category_uuid=cat_uuid,
                        category_name=cat_name,
                        **entry,  # type: ignore[arg-type]
                    )
        return results

    def get_summary_for_prompt(self) -> str:
        """Return a compact, LLM-friendly JSON summary of the compendium.

        Only category name, entry name, and entry content are included —
        no UUIDs, images, tags, or relationships — to keep the token
        footprint small.

        Returns:
            JSON string: ``{"categories": [{"name", "entries": [{"name", "content"}]}]}``
        """
        data = self._load_data()
        summary = {
            "categories": [
                {
                    "name": cat.get("name", ""),
                    "entries": [
                        {"name": e.get("name", ""), "content": e.get("content", "")}
                        for e in cat.get("entries", [])
                    ],
                }
                for cat in data.get("categories", [])
            ]
        }
        return json.dumps(summary, indent=2)

    # ------------------------------------------------------------------
    # Mutation (CRUD) methods
    # Targeted entities are always referenced by UUID for delete, move,
    # rename, and update operations.  Only ``add_*`` methods use names
    # (because the object does not yet have a UUID).
    # Each method loads current data, applies one atomic change, and
    # saves back.  Callers never need to see the raw data structure.
    # ------------------------------------------------------------------

    # --- Categories ---

    def add_category(self, name: str) -> CompendiumCategory:
        """Create and persist a new category.

        Returns:
            The newly created category dict (includes its generated ``uuid``).
        """
        data = self._load_data()
        new_cat = self.make_empty_category(name)
        data["categories"].append(new_cat)
        self._save_data(data)
        return new_cat

    def rename_category(self, category_uuid: str, new_name: str) -> bool:
        """Rename the category identified by *category_uuid*.

        Returns:
            ``True`` if found and renamed, ``False`` otherwise.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("uuid") == category_uuid:
                cat["name"] = new_name
                self._save_data(data)
                return True
        return False

    def remove_category(self, category_uuid: str) -> bool:
        """Remove the category identified by *category_uuid* and all its entries.

        Returns:
            ``True`` if found and removed, ``False`` otherwise.
        """
        data = self._load_data()
        before = len(data.get("categories", []))
        data["categories"] = [c for c in data.get("categories", []) if c.get("uuid") != category_uuid]
        if len(data["categories"]) == before:
            return False
        self._save_data(data)
        return True

    # --- Entries ---

    def add_entry(self, category_uuid: str, name: str, content: str = "") -> CompendiumEntry | None:
        """Add a new entry to the category identified by *category_uuid*.

        Returns:
            The new entry dict (includes its generated ``uuid``), or ``None`` if
            *category_uuid* was not found.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("uuid") == category_uuid:
                new_entry = self.make_empty_entry(name, content)
                cat["entries"].append(new_entry)
                self._save_data(data)
                return new_entry
        return None

    def rename_entry(self, entry_uuid: str, new_name: str) -> bool:
        """Rename the entry identified by *entry_uuid*.

        Returns:
            ``True`` if found and renamed, ``False`` otherwise.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            for entry in cat.get("entries", []):
                if entry.get("uuid") == entry_uuid:
                    entry["name"] = new_name
                    self._save_data(data)
                    return True
        return False

    def update_entry(self, entry_uuid: str, fields: CompendiumEntry) -> bool:
        """Merge *fields* into the entry identified by *entry_uuid*.

        The ``uuid`` field is protected and cannot be changed via this method.
        All existing fields not present in *fields* are preserved.

        Returns:
            ``True`` if the entry was found and updated, ``False`` otherwise.
        """
        safe_fields = {k: v for k, v in fields.items() if k != "uuid"}
        data = self._load_data()
        for cat in data.get("categories", []):
            for entry in cat.get("entries", []):
                if entry.get("uuid") == entry_uuid:
                    entry.update(safe_fields)
                    self._save_data(data)
                    return True
        return False

    def remove_entry(self, entry_uuid: str) -> bool:
        """Remove the entry identified by *entry_uuid*.

        Returns:
            ``True`` if removed, ``False`` if not found.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            before = len(cat.get("entries", []))
            cat["entries"] = [e for e in cat.get("entries", []) if e.get("uuid") != entry_uuid]
            if len(cat["entries"]) < before:
                self._save_data(data)
                return True
        return False

    def move_entry(self, entry_uuid: str, target_category_uuid: str) -> bool:
        """Move the entry identified by *entry_uuid* to the category identified by
        *target_category_uuid*.

        Returns:
            ``True`` on success, ``False`` if the entry or target category was not found.
        """
        data = self._load_data()
        entry_dict = None
        for cat in data.get("categories", []):
            for e in cat.get("entries", []):
                if e.get("uuid") == entry_uuid:
                    entry_dict = e
                    break
            if entry_dict is not None:
                cat["entries"] = [e for e in cat.get("entries", []) if e.get("uuid") != entry_uuid]
                break
        if entry_dict is None:
            return False
        for cat in data.get("categories", []):
            if cat.get("uuid") == target_category_uuid:
                cat["entries"].append(entry_dict)
                self._save_data(data)
                return True
        return False

    def reorder_entries(self, category_uuid: str, ordered_uuids: list[str]) -> bool:
        """Reorder the entries of the category identified by *category_uuid* to match
        *ordered_uuids*.

        Entries whose UUID is absent from *ordered_uuids* are appended at the end in
        their original relative order.

        Returns:
            ``True`` if the category was found, ``False`` otherwise.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("uuid") == category_uuid:
                uuid_to_entry = {e.get("uuid"): e for e in cat.get("entries", [])}
                ordered = [uuid_to_entry[u] for u in ordered_uuids if u in uuid_to_entry]
                ordered_set = set(ordered_uuids)
                remaining = [e for e in cat.get("entries", []) if e.get("uuid") not in ordered_set]
                cat["entries"] = ordered + remaining
                self._save_data(data)
                return True
        return False

    # ------------------------------------------------------------------
    # Legacy / convenience helpers
    # These name-based methods are kept for backward compatibility while
    # callers in other modules are updated to use UUID-based APIs.
    # ------------------------------------------------------------------

    def get_category(self, category_name: str) -> list[CompendiumEntry]:
        """[Legacy] Return entries for the first category whose name matches *category_name*.

        Prefer ``list_entries(category_uuid)`` for new code.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("name") == category_name:
                return cat.get("entries", [])
        return []

    def list_pov_characters(self) -> list[PovCharacter]:
        """Return a list of POV character summaries from the 'Characters' category.

        Returns:
            list of ``PovCharacter`` dicts in canonical compendium order.
            Empty list if the 'Characters' category does not exist or has no entries.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("name", "").lower() == "characters":
                return [
                    PovCharacter(uuid=e.get("uuid", ""), name=e.get("name", ""))
                    for e in cat.get("entries", [])
                ]
        return []

    def add_pov_character(self, name: str, description: str = "") -> CompendiumEntry:
        """Upsert a POV character into the 'Characters' category.

        If a 'Characters' category does not exist it is created. If an entry with
        *name* already exists its description is updated and the full entry dict is
        returned. Otherwise a new entry is created and returned.

        Returns:
            The full entry dict (including ``uuid``) for the upserted character.
        """
        data = self._load_data()

        # Find or create the Characters category.
        characters_cat: CompendiumCategory | None = None
        for cat in data.get("categories", []):
            if cat.get("name", "").lower() == "characters":
                characters_cat = cat
                break
        if characters_cat is None:
            characters_cat = self.make_empty_category("Characters")
            data.setdefault("categories", []).append(characters_cat)

        # Update existing entry or create a new one.
        for entry in characters_cat.get("entries", []):
            if entry.get("name") == name:
                entry["content"] = description
                entry.setdefault("uuid", str(uuid4()))
                entry.setdefault("details", "")
                entry.setdefault("tags", [])
                entry.setdefault("relationships", [])
                entry.setdefault("images", [])
                self._save_data(data)
                return entry

        new_entry = self.make_empty_entry(name, description)
        characters_cat.setdefault("entries", []).append(new_entry)
        self._save_data(data)
        return new_entry

    def get_characters(self) -> list[str]:
        """[Legacy] Return a list of character names from the 'Characters' category.

        NOTE: This returns names in the canonical order stored in the compendium
        (categories[].entries[]) rather than enforcing an alphabetical sort. Callers
        that depend on an alphabetically-sorted list should explicitly sort the
        result.
        """
        character_dicts = self.get_category("Characters")
        return [d['name'] for d in character_dicts]

    def get_text(self, category: str, entry: str) -> str:
        """[Legacy] Retrieve entry content by category name and entry name.

        Prefer ``get_entry_by_uuid`` for new code.
        """
        data = self._load_data()
        for cat in data.get("categories", []):
            if cat.get("name") == category:
                for e in cat.get("entries", []):
                    if e.get("name") == entry:
                        return e.get("content", f"[No content for {entry} in category {category}]")
        return f"[No content for {entry} in category {category}]"



