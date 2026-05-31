"""
Unit tests for compendium.compendium_manager.CompendiumManager.

These tests exercise the pure data-management logic of CompendiumManager
(CRUD, migration, search) in complete filesystem isolation so that they
never touch the real ``Projects/`` tree.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from compendium.compendium_manager import CompendiumEventBus, CompendiumManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_raw(manager: CompendiumManager) -> dict:
    """Read the compendium JSON file directly and return the raw dict."""
    with open(manager._filepath, encoding="utf-8") as f:
        return json.load(f)


# ===========================================================================
# make_empty_entry / make_empty_category factories
# ===========================================================================

class TestFactories:
    @pytest.mark.unit
    def test_make_empty_entry_has_required_fields(self):
        entry = CompendiumManager.make_empty_entry("Alice", "A brave hero.")
        assert entry["name"] == "Alice"
        assert entry["content"] == "A brave hero."
        assert entry.get("uuid")
        assert entry["details"] == ""
        assert entry["tags"] == []
        assert entry["relationships"] == []
        assert entry["images"] == []

    @pytest.mark.unit
    def test_make_empty_entry_generates_unique_uuids(self):
        e1 = CompendiumManager.make_empty_entry("A")
        e2 = CompendiumManager.make_empty_entry("B")
        assert e1["uuid"] != e2["uuid"]

    @pytest.mark.unit
    def test_make_empty_category_has_required_fields(self):
        cat = CompendiumManager.make_empty_category("Characters")
        assert cat["name"] == "Characters"
        assert cat.get("uuid")
        assert cat["entries"] == []

    @pytest.mark.unit
    def test_make_empty_category_generates_unique_uuids(self):
        c1 = CompendiumManager.make_empty_category("A")
        c2 = CompendiumManager.make_empty_category("B")
        assert c1["uuid"] != c2["uuid"]


# ===========================================================================
# Initialisation / file creation
# ===========================================================================

class TestInitialisation:
    @pytest.mark.integration
    def test_creates_compendium_file_on_first_run(self, compendium_manager):
        import os
        assert os.path.exists(compendium_manager._filepath)

    @pytest.mark.integration
    def test_default_file_has_characters_category(self, compendium_manager):
        data = _read_raw(compendium_manager)
        names = [c["name"] for c in data.get("categories", [])]
        assert "Characters" in names

    @pytest.mark.integration
    def test_load_data_returns_dict_with_categories(self, compendium_manager):
        data = compendium_manager.load_data()
        assert isinstance(data, dict)
        assert "categories" in data
        assert isinstance(data["categories"], list)


# ===========================================================================
# Category CRUD
# ===========================================================================

class TestCategoryCRUD:
    @pytest.mark.integration
    def test_add_category_returns_new_category(self, compendium_manager):
        cat = compendium_manager.add_category("Locations")
        assert cat["name"] == "Locations"
        assert "uuid" in cat

    @pytest.mark.integration
    def test_add_category_persists_to_file(self, compendium_manager):
        cat = compendium_manager.add_category("Factions")
        data = _read_raw(compendium_manager)
        names = [c["name"] for c in data["categories"]]
        assert "Factions" in names

    @pytest.mark.integration
    def test_rename_category_returns_true_on_success(self, compendium_manager):
        cat = compendium_manager.add_category("OldName")
        result = compendium_manager.rename_category(cat["uuid"], "NewName")
        assert result is True

    @pytest.mark.integration
    def test_rename_category_persists_new_name(self, compendium_manager):
        cat = compendium_manager.add_category("OldName")
        compendium_manager.rename_category(cat["uuid"], "NewName")
        data = _read_raw(compendium_manager)
        names = [c["name"] for c in data["categories"]]
        assert "NewName" in names
        assert "OldName" not in names

    @pytest.mark.integration
    def test_rename_category_returns_false_for_unknown_uuid(self, compendium_manager):
        result = compendium_manager.rename_category("nonexistent-uuid", "X")
        assert result is False

    @pytest.mark.integration
    def test_remove_category_returns_true_on_success(self, compendium_manager):
        cat = compendium_manager.add_category("ToRemove")
        result = compendium_manager.remove_category(cat["uuid"])
        assert result is True

    @pytest.mark.integration
    def test_remove_category_deletes_from_file(self, compendium_manager):
        cat = compendium_manager.add_category("ToRemove")
        compendium_manager.remove_category(cat["uuid"])
        data = _read_raw(compendium_manager)
        names = [c["name"] for c in data["categories"]]
        assert "ToRemove" not in names

    @pytest.mark.integration
    def test_remove_category_returns_false_for_unknown_uuid(self, compendium_manager):
        result = compendium_manager.remove_category("nonexistent-uuid")
        assert result is False

    @pytest.mark.integration
    def test_list_categories_includes_added_category(self, compendium_manager):
        compendium_manager.add_category("Artifacts")
        cats = compendium_manager.list_categories()
        names = [c["name"] for c in cats]
        assert "Artifacts" in names

    @pytest.mark.integration
    def test_get_category_by_uuid_returns_correct_category(self, compendium_manager):
        cat = compendium_manager.add_category("Spells")
        retrieved = compendium_manager.get_category_by_uuid(cat["uuid"])
        assert retrieved is not None
        assert retrieved["name"] == "Spells"

    @pytest.mark.integration
    def test_get_category_by_uuid_returns_none_for_unknown(self, compendium_manager):
        result = compendium_manager.get_category_by_uuid("does-not-exist")
        assert result is None


# ===========================================================================
# Entry CRUD
# ===========================================================================

class TestEntryCRUD:
    @pytest.fixture()
    def category(self, compendium_manager):
        """A pre-created category to use in entry tests."""
        return compendium_manager.add_category("Heroes")

    @pytest.mark.integration
    def test_add_entry_returns_new_entry(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Gandalf", "A wizard.")
        assert entry is not None
        assert entry["name"] == "Gandalf"
        assert entry["content"] == "A wizard."
        assert "uuid" in entry

    @pytest.mark.integration
    def test_add_entry_returns_none_for_unknown_category(self, compendium_manager):
        result = compendium_manager.add_entry("bad-uuid", "X")
        assert result is None

    @pytest.mark.integration
    def test_add_entry_persists_to_file(self, compendium_manager, category):
        compendium_manager.add_entry(category["uuid"], "Frodo")
        data = _read_raw(compendium_manager)
        cat_data = next(c for c in data["categories"] if c["uuid"] == category["uuid"])
        entry_names = [e["name"] for e in cat_data["entries"]]
        assert "Frodo" in entry_names

    @pytest.mark.integration
    def test_rename_entry_returns_true_on_success(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Samwise")
        result = compendium_manager.rename_entry(entry["uuid"], "Sam")
        assert result is True

    @pytest.mark.integration
    def test_rename_entry_persists_new_name(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Samwise")
        compendium_manager.rename_entry(entry["uuid"], "Sam")
        retrieved = compendium_manager.get_entry_by_uuid(entry["uuid"])
        assert retrieved["name"] == "Sam"

    @pytest.mark.integration
    def test_rename_entry_returns_false_for_unknown_uuid(self, compendium_manager):
        result = compendium_manager.rename_entry("no-such-uuid", "X")
        assert result is False

    @pytest.mark.integration
    def test_update_entry_merges_fields(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Aragorn")
        compendium_manager.update_entry(entry["uuid"], {"details": "King of Gondor", "tags": ["royalty"]})
        updated = compendium_manager.get_entry_by_uuid(entry["uuid"])
        assert updated["details"] == "King of Gondor"
        assert "royalty" in updated["tags"]
        # Original fields should still be present
        assert updated["name"] == "Aragorn"

    @pytest.mark.integration
    def test_update_entry_cannot_change_uuid(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Legolas")
        original_uuid = entry["uuid"]
        compendium_manager.update_entry(original_uuid, {"uuid": "hacked-uuid"})
        retrieved = compendium_manager.get_entry_by_uuid(original_uuid)
        assert retrieved is not None  # still findable by original UUID
        assert retrieved["uuid"] == original_uuid

    @pytest.mark.integration
    def test_update_entry_returns_false_for_unknown_uuid(self, compendium_manager):
        result = compendium_manager.update_entry("ghost-uuid", {"content": "nothing"})
        assert result is False

    @pytest.mark.integration
    def test_remove_entry_returns_true_on_success(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Boromir")
        result = compendium_manager.remove_entry(entry["uuid"])
        assert result is True

    @pytest.mark.integration
    def test_remove_entry_deletes_from_storage(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Boromir")
        compendium_manager.remove_entry(entry["uuid"])
        assert compendium_manager.get_entry_by_uuid(entry["uuid"]) is None

    @pytest.mark.integration
    def test_remove_entry_returns_false_for_unknown_uuid(self, compendium_manager):
        result = compendium_manager.remove_entry("unknown-uuid")
        assert result is False

    @pytest.mark.integration
    def test_list_entries_returns_entries_for_category(self, compendium_manager, category):
        compendium_manager.add_entry(category["uuid"], "Gimli")
        entries = compendium_manager.list_entries(category["uuid"])
        names = [e["name"] for e in entries]
        assert "Gimli" in names

    @pytest.mark.integration
    def test_list_entries_returns_empty_for_unknown_category(self, compendium_manager):
        result = compendium_manager.list_entries("no-such-uuid")
        assert result == []

    @pytest.mark.integration
    def test_get_entry_by_uuid_returns_correct_entry(self, compendium_manager, category):
        entry = compendium_manager.add_entry(category["uuid"], "Treebeard")
        retrieved = compendium_manager.get_entry_by_uuid(entry["uuid"])
        assert retrieved is not None
        assert retrieved["name"] == "Treebeard"

    @pytest.mark.integration
    def test_get_entry_by_uuid_returns_none_for_unknown(self, compendium_manager):
        result = compendium_manager.get_entry_by_uuid("not-a-uuid")
        assert result is None


# ===========================================================================
# Move & reorder
# ===========================================================================

class TestMoveAndReorder:
    @pytest.mark.integration
    def test_move_entry_to_another_category(self, compendium_manager):
        src = compendium_manager.add_category("Villains")
        dst = compendium_manager.add_category("Neutral")
        entry = compendium_manager.add_entry(src["uuid"], "Gollum")

        result = compendium_manager.move_entry(entry["uuid"], dst["uuid"])
        assert result is True

        # Should no longer be in source
        src_entries = compendium_manager.list_entries(src["uuid"])
        assert all(e["uuid"] != entry["uuid"] for e in src_entries)

        # Should be in destination
        dst_entries = compendium_manager.list_entries(dst["uuid"])
        assert any(e["uuid"] == entry["uuid"] for e in dst_entries)

    @pytest.mark.integration
    def test_move_entry_returns_false_for_unknown_entry(self, compendium_manager):
        cat = compendium_manager.add_category("Somewhere")
        result = compendium_manager.move_entry("ghost", cat["uuid"])
        assert result is False

    @pytest.mark.integration
    def test_move_entry_returns_false_for_unknown_target(self, compendium_manager):
        cat = compendium_manager.add_category("Source")
        entry = compendium_manager.add_entry(cat["uuid"], "X")
        result = compendium_manager.move_entry(entry["uuid"], "no-target")
        assert result is False

    @pytest.mark.integration
    def test_reorder_entries(self, compendium_manager):
        cat = compendium_manager.add_category("Ordered")
        e1 = compendium_manager.add_entry(cat["uuid"], "First")
        e2 = compendium_manager.add_entry(cat["uuid"], "Second")
        e3 = compendium_manager.add_entry(cat["uuid"], "Third")

        # Reverse the order
        new_order = [e3["uuid"], e2["uuid"], e1["uuid"]]
        result = compendium_manager.reorder_entries(cat["uuid"], new_order)
        assert result is True

        entries = compendium_manager.list_entries(cat["uuid"])
        assert [e["uuid"] for e in entries] == new_order

    @pytest.mark.integration
    def test_reorder_entries_returns_false_for_unknown_category(self, compendium_manager):
        result = compendium_manager.reorder_entries("bad-uuid", [])
        assert result is False


# ===========================================================================
# Search
# ===========================================================================

class TestSearch:
    @pytest.fixture(autouse=True)
    def _populate(self, compendium_manager):
        """Populate a small dataset used by all search tests."""
        self.cm = compendium_manager
        self.cat = compendium_manager.add_category("People")
        self.alice = compendium_manager.add_entry(self.cat["uuid"], "Alice", "Protagonist")
        self.bob = compendium_manager.add_entry(self.cat["uuid"], "Bob", "Antagonist")
        # Give Bob a tag
        compendium_manager.update_entry(self.bob["uuid"], {"tags": [{"name": "villain"}]})

    @pytest.mark.integration
    def test_find_entries_empty_search_returns_all(self):
        results = self.cm.find_entries("")
        uuids = set(results.keys())
        assert self.alice["uuid"] in uuids
        assert self.bob["uuid"] in uuids

    @pytest.mark.integration
    def test_find_entries_by_name(self):
        results = self.cm.find_entries("Alice")
        assert self.alice["uuid"] in results
        assert self.bob["uuid"] not in results

    @pytest.mark.integration
    def test_find_entries_by_tag(self):
        results = self.cm.find_entries("villain")
        assert self.bob["uuid"] in results

    @pytest.mark.integration
    def test_find_entries_case_insensitive(self):
        results = self.cm.find_entries("alice")
        assert self.alice["uuid"] in results

    @pytest.mark.integration
    def test_find_entries_result_includes_category_metadata(self):
        results = self.cm.find_entries("Alice")
        entry = results[self.alice["uuid"]]
        assert entry["category_uuid"] == self.cat["uuid"]
        assert entry["category_name"] == "People"

    @pytest.mark.integration
    def test_find_categories_empty_search_returns_all(self):
        self.cm.add_category("Places")
        results = self.cm.find_categories("")
        assert self.cat["uuid"] in results

    @pytest.mark.integration
    def test_find_categories_by_name(self):
        places = self.cm.add_category("Places")
        results = self.cm.find_categories("Plac")
        assert places["uuid"] in results
        assert self.cat["uuid"] not in results


# ===========================================================================
# Legacy helpers
# ===========================================================================

class TestLegacyHelpers:
    @pytest.mark.integration
    def test_get_characters_returns_names_in_order(self, compendium_manager):
        # The default "Characters" category already exists; add some entries.
        chars_cat = next(
            c for c in compendium_manager.load_data()["categories"]
            if c["name"] == "Characters"
        )
        compendium_manager.add_entry(chars_cat["uuid"], "Zara")
        compendium_manager.add_entry(chars_cat["uuid"], "Aaron")
        names = compendium_manager.get_characters()
        assert names == ["Zara", "Aaron"]  # order should be preserved

    @pytest.mark.integration
    def test_get_text_returns_content(self, compendium_manager):
        cat = compendium_manager.add_category("Magic")
        compendium_manager.add_entry(cat["uuid"], "Fireball", "A powerful fire spell.")
        text = compendium_manager.get_text("Magic", "Fireball")
        assert text == "A powerful fire spell."

    @pytest.mark.integration
    def test_get_text_returns_placeholder_for_missing_entry(self, compendium_manager):
        compendium_manager.add_category("Empty")
        text = compendium_manager.get_text("Empty", "NoSuchEntry")
        assert "NoSuchEntry" in text

    @pytest.mark.integration
    def test_add_character_creates_entry_in_characters_category(self, compendium_manager):
        compendium_manager.add_character("Eve", "A mysterious figure.")
        assert "Eve" in compendium_manager.get_characters()

    @pytest.mark.integration
    def test_add_character_updates_existing_entry(self, compendium_manager):
        compendium_manager.add_character("Eve", "First description.")
        compendium_manager.add_character("Eve", "Updated description.")
        text = compendium_manager.get_text("Characters", "Eve")
        assert text == "Updated description."


# ===========================================================================
# Reference parsing
# ===========================================================================

class TestParseReferences:
    @pytest.mark.integration
    def test_parse_references_finds_entry_name(self, compendium_manager):
        cat = compendium_manager.add_category("Cast")
        compendium_manager.add_entry(cat["uuid"], "Merlin")
        refs = compendium_manager.parse_references("Merlin walked into the room.")
        assert "Merlin" in refs

    @pytest.mark.integration
    def test_parse_references_is_case_insensitive(self, compendium_manager):
        cat = compendium_manager.add_category("Cast")
        compendium_manager.add_entry(cat["uuid"], "Merlin")
        refs = compendium_manager.parse_references("merlin walked into the room.")
        assert "Merlin" in refs

    @pytest.mark.integration
    def test_parse_references_returns_empty_for_no_matches(self, compendium_manager):
        refs = compendium_manager.parse_references("No names here at all.")
        assert refs == []


# ===========================================================================
# get_summary_for_prompt
# ===========================================================================

class TestGetSummaryForPrompt:
    @pytest.mark.integration
    def test_returns_valid_json(self, compendium_manager):
        summary = compendium_manager.get_summary_for_prompt()
        parsed = json.loads(summary)
        assert "categories" in parsed

    @pytest.mark.integration
    def test_summary_omits_sensitive_fields(self, compendium_manager):
        """UUIDs, images, tags, and relationships must not appear in the prompt summary."""
        cat = compendium_manager.add_category("Secrets")
        compendium_manager.add_entry(cat["uuid"], "Spy", "Hidden agent.")
        summary = compendium_manager.get_summary_for_prompt()
        # The summary should not expose internal UUIDs to the LLM
        assert cat["uuid"] not in summary
        # High-level check: only name/content per entry
        parsed = json.loads(summary)
        for category in parsed["categories"]:
            for entry in category["entries"]:
                assert set(entry.keys()) == {"name", "content"}


# ===========================================================================
# upsert_data
# ===========================================================================

class TestUpsertData:
    @pytest.mark.integration
    def test_upsert_adds_new_category(self, compendium_manager):
        compendium_manager.upsert_data({
            "categories": [{"name": "Imported", "uuid": "u1", "entries": []}]
        })
        cats = compendium_manager.list_categories()
        assert any(c["name"] == "Imported" for c in cats)

    @pytest.mark.integration
    def test_upsert_adds_entries_to_existing_category(self, compendium_manager):
        cat = compendium_manager.add_category("Merge")
        compendium_manager.upsert_data({
            "categories": [{"name": "Merge", "entries": [{"name": "NewEntry", "content": "hi"}]}]
        })
        entries = compendium_manager.list_entries(cat["uuid"])
        assert any(e["name"] == "NewEntry" for e in entries)

    @pytest.mark.integration
    def test_upsert_updates_existing_entry(self, compendium_manager):
        cat = compendium_manager.add_category("Update")
        compendium_manager.add_entry(cat["uuid"], "ExistingEntry", "old content")
        compendium_manager.upsert_data({
            "categories": [{"name": "Update", "entries": [{"name": "ExistingEntry", "content": "new content"}]}]
        })
        entries = compendium_manager.list_entries(cat["uuid"])
        entry = next(e for e in entries if e["name"] == "ExistingEntry")
        assert entry["content"] == "new content"


# ===========================================================================
# CompendiumEventBus
# ===========================================================================

class TestCompendiumEventBus:
    @pytest.mark.unit
    def test_get_instance_returns_singleton(self):
        # Reset singleton so the test is independent.
        CompendiumEventBus._instance = None
        a = CompendiumEventBus.get_instance()
        b = CompendiumEventBus.get_instance()
        assert a is b
        CompendiumEventBus._instance = None  # cleanup

    @pytest.mark.unit
    def test_add_and_notify_listener(self):
        bus = CompendiumEventBus()
        received = []
        bus.add_updated_listener(lambda name: received.append(name))
        bus.notify_updated("MyProject")
        assert received == ["MyProject"]

    @pytest.mark.unit
    def test_remove_listener_stops_notifications(self):
        bus = CompendiumEventBus()
        received = []
        cb = lambda name: received.append(name)
        bus.add_updated_listener(cb)
        bus.remove_updated_listener(cb)
        bus.notify_updated("X")
        assert received == []

    @pytest.mark.unit
    def test_remove_unknown_listener_is_safe(self):
        bus = CompendiumEventBus()
        cb = lambda name: None
        # Removing a listener that was never added should not raise.
        bus.remove_updated_listener(cb)

    @pytest.mark.unit
    def test_notify_removes_erroring_listener(self):
        bus = CompendiumEventBus()

        def bad_cb(name):
            raise RuntimeError("boom")

        bus.add_updated_listener(bad_cb)
        # Should not propagate the exception.
        bus.notify_updated("Z")
        # After failure the listener should have been removed.
        assert bad_cb not in bus.updated_listeners

    @pytest.mark.unit
    def test_notify_calls_multiple_listeners(self):
        bus = CompendiumEventBus()
        log = []
        bus.add_updated_listener(lambda n: log.append(f"a:{n}"))
        bus.add_updated_listener(lambda n: log.append(f"b:{n}"))
        bus.notify_updated("P")
        assert "a:P" in log
        assert "b:P" in log


# ===========================================================================
# _get_filepath without project_name (global compendium)
# ===========================================================================

class TestGetFilepath:
    @pytest.mark.integration
    def test_no_project_name_uses_cwd(self, isolated_cwd):
        cm = CompendiumManager(project_name=None, event_bus=None)
        expected = os.path.join(str(isolated_cwd), "compendium.json")
        assert cm._filepath == expected


# ===========================================================================
# _backup_compendium_data
# ===========================================================================

class TestBackupCompendiumData:
    @pytest.mark.integration
    def test_backup_raises_when_file_missing(self, compendium_manager):
        os.remove(compendium_manager._filepath)
        with pytest.raises(FileNotFoundError):
            compendium_manager._backup_compendium_data()

    @pytest.mark.integration
    def test_backup_creates_timestamped_file(self, compendium_manager):
        backup_path = compendium_manager._backup_compendium_data()
        assert os.path.exists(backup_path)
        assert backup_path.startswith(compendium_manager._filepath)

    @pytest.mark.integration
    def test_backup_raises_ioerror_on_copy_failure(self, compendium_manager):
        with patch("shutil.copy2", side_effect=OSError("disk full")), pytest.raises(IOError):
            compendium_manager._backup_compendium_data()


# ===========================================================================
# _load_data – error and migration paths
# ===========================================================================

class TestLoadDataEdgeCases:
    @pytest.mark.integration
    def test_corrupt_json_falls_back_to_default(self, compendium_manager):
        """A JSON-corrupt file should be replaced with a default compendium."""
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            f.write("not valid json {{{")
        data = compendium_manager._load_data()
        assert "categories" in data

    @pytest.mark.integration
    def test_missing_file_is_recreated_on_load(self, compendium_manager):
        os.remove(compendium_manager._filepath)
        data = compendium_manager._load_data()
        assert "categories" in data

    @pytest.mark.integration
    def test_empty_categories_list_is_kept_as_list(self, compendium_manager):
        """An explicit empty list in 'categories' must not cause an error."""
        raw = {"version": 3, "categories": []}
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        assert isinstance(data["categories"], list)

    @pytest.mark.integration
    def test_empty_categories_list_does_not_trigger_internal_resave(self, compendium_manager):
        """Regression: loading version-3 data with empty categories should be idempotent."""
        raw = {"version": 3, "categories": []}
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)

        compendium_manager._backup_compendium_data = MagicMock(wraps=compendium_manager._backup_compendium_data)
        compendium_manager._save_data = MagicMock(wraps=compendium_manager._save_data)

        compendium_manager._load_data()
        compendium_manager._load_data()

        compendium_manager._backup_compendium_data.assert_not_called()
        compendium_manager._save_data.assert_not_called()

    @pytest.mark.integration
    def test_legacy_dict_categories_are_converted_to_list(self, compendium_manager):
        """Old format: categories is a dict mapping name -> {entry: content}."""
        legacy = {
            "version": 1,
            "categories": {
                "Heroes": {"Arthur": "A knight.", "Merlin": "A wizard."},
            },
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        data = compendium_manager._load_data()
        assert isinstance(data["categories"], list)
        names = [c["name"] for c in data["categories"]]
        assert "Heroes" in names
        heroes = next(c for c in data["categories"] if c["name"] == "Heroes")
        entry_names = [e["name"] for e in heroes["entries"]]
        assert "Arthur" in entry_names

    @pytest.mark.integration
    def test_missing_category_uuid_is_added(self, compendium_manager):
        """Categories missing a uuid should get one assigned."""
        raw = {
            "version": 3,
            "categories": [{"name": "NeedsUUID", "entries": []}],
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        cat = next(c for c in data["categories"] if c["name"] == "NeedsUUID")
        assert cat.get("uuid")

    @pytest.mark.integration
    def test_duplicate_category_uuid_is_resolved(self, compendium_manager):
        shared_uuid = "dup-uuid-cat"
        raw = {
            "version": 3,
            "categories": [
                {"name": "Cat1", "uuid": shared_uuid, "entries": []},
                {"name": "Cat2", "uuid": shared_uuid, "entries": []},
            ],
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        uuids = [c["uuid"] for c in data["categories"]]
        assert len(uuids) == len(set(uuids)), "Duplicate category UUIDs were not resolved"

    @pytest.mark.integration
    def test_missing_entry_uuid_is_added(self, compendium_manager):
        raw = {
            "version": 3,
            "categories": [
                {"name": "C", "uuid": "c-uuid", "entries": [{"name": "E", "content": "x"}]},
            ],
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        entry = data["categories"][0]["entries"][0]
        assert entry.get("uuid")

    @pytest.mark.integration
    def test_duplicate_entry_uuid_is_resolved(self, compendium_manager):
        shared_uuid = "dup-uuid-entry"
        raw = {
            "version": 3,
            "categories": [
                {
                    "name": "C", "uuid": "c-uuid",
                    "entries": [
                        {"name": "E1", "uuid": shared_uuid, "content": ""},
                        {"name": "E2", "uuid": shared_uuid, "content": ""},
                    ],
                }
            ],
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        uuids = [e["uuid"] for e in data["categories"][0]["entries"]]
        assert len(uuids) == len(set(uuids)), "Duplicate entry UUIDs were not resolved"

    @pytest.mark.integration
    def test_entry_with_empty_name_gets_generated_name(self, compendium_manager):
        raw = {
            "version": 3,
            "categories": [
                {"name": "C", "uuid": "c-uuid", "entries": [{"name": "", "uuid": "e-uuid", "content": ""}]},
            ],
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        data = compendium_manager._load_data()
        entry = data["categories"][0]["entries"][0]
        assert entry["name"]  # not empty

    @pytest.mark.integration
    def test_extensions_section_is_migrated_to_unified_format(self, compendium_manager):
        """Legacy split format with an 'extensions' key must be merged in-place."""
        legacy = {
            "version": 2,
            "categories": [
                {
                    "name": "Heroes",
                    "uuid": "h-uuid",
                    "entries": [{"name": "Arthur", "uuid": "a-uuid", "content": "A knight."}],
                }
            ],
            "extensions": {
                "entries": {
                    "Arthur": {
                        "details": "King of Camelot",
                        "tags": ["royalty"],
                        "relationships": [],
                        "images": [],
                    }
                }
            },
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        data = compendium_manager._load_data()
        assert "extensions" not in data
        arthur = data["categories"][0]["entries"][0]
        assert arthur.get("details") == "King of Camelot"
        assert arthur.get("tags") == ["royalty"]

    @pytest.mark.integration
    def test_extensions_entry_not_in_ext_gets_defaults(self, compendium_manager):
        """Entries that have no match in the extensions dict get default fields."""
        legacy = {
            "version": 2,
            "categories": [
                {
                    "name": "Heroes",
                    "uuid": "h-uuid",
                    "entries": [{"name": "Lancelot", "uuid": "l-uuid", "content": "A knight."}],
                }
            ],
            "extensions": {"entries": {}},
        }
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        data = compendium_manager._load_data()
        lancelot = data["categories"][0]["entries"][0]
        assert lancelot.get("details") == ""
        assert lancelot.get("tags") == []


# ===========================================================================
# _save_data – event bus notification
# ===========================================================================

class TestSaveDataEventBus:
    @pytest.mark.integration
    def test_save_notifies_event_bus(self, isolated_cwd):
        bus = MagicMock(spec=CompendiumEventBus)
        project_name = "BusProject"
        project_dir = isolated_cwd / "Projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        cm = CompendiumManager(project_name=project_name, event_bus=bus)
        # Reset call count from __init__ / _ensure_file_exists.
        bus.reset_mock()
        cm.add_category("Stuff")
        bus.notify_updated.assert_called_with(project_name)


# ===========================================================================
# add_character edge cases
# ===========================================================================

class TestAddCharacterEdgeCases:
    @pytest.mark.integration
    def test_add_character_creates_characters_category_when_absent(self, compendium_manager):
        """If no 'Characters' category exists, add_character must create one."""
        # Remove the default Characters category.
        data = compendium_manager.load_data()
        chars_uuid = next(c["uuid"] for c in data["categories"] if c["name"] == "Characters")
        compendium_manager.remove_category(chars_uuid)
        # Now add a character — should re-create the category.
        compendium_manager.add_character("Neo", "The chosen one.")
        assert "Neo" in compendium_manager.get_characters()

    @pytest.mark.integration
    def test_add_character_assigns_uuid_to_legacy_entry_without_uuid(self, compendium_manager):
        """A legacy entry that lacks a uuid should receive one on update."""
        # Manually inject a uuid-less entry into the file.
        data = compendium_manager.load_data()
        chars_cat = next(c for c in data["categories"] if c["name"] == "Characters")
        chars_cat["entries"].append({"name": "LegacyChar", "content": "old"})
        with open(compendium_manager._filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # Calling add_character should update the existing entry and assign a uuid.
        compendium_manager.add_character("LegacyChar", "updated")
        entry = next(
            e
            for cat in compendium_manager.load_data()["categories"]
            for e in cat.get("entries", [])
            if e["name"] == "LegacyChar"
        )
        assert entry.get("uuid")
        assert entry["content"] == "updated"


# ===========================================================================
# get_category (legacy) – unknown category returns empty list
# ===========================================================================

class TestGetCategoryLegacy:
    @pytest.mark.integration
    def test_get_category_returns_empty_list_for_unknown_name(self, compendium_manager):
        result = compendium_manager.get_category("NoSuchCategory")
        assert result == []

    @pytest.mark.integration
    def test_get_category_returns_entries_for_known_name(self, compendium_manager):
        cat = compendium_manager.add_category("Weapons")
        compendium_manager.add_entry(cat["uuid"], "Excalibur", "A legendary sword.")
        entries = compendium_manager.get_category("Weapons")
        names = [e["name"] for e in entries]
        assert "Excalibur" in names

