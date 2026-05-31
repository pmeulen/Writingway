"""
Unit tests for settings.settings_manager.SettingsManager.

All tests that touch the filesystem use ``tmp_path`` to keep them isolated
from the real ``settings.json`` on disk.
"""

import copy
import json
from pathlib import Path

import pytest

from settings.settings_manager import SettingsManager

# ---------------------------------------------------------------------------
# Fixture: a fresh SettingsManager backed by a temp file
# ---------------------------------------------------------------------------

@pytest.fixture()
def settings_file(tmp_path) -> Path:
    """Return a path inside a temp directory; the file does not yet exist."""
    return tmp_path / "settings.json"


@pytest.fixture()
def sm(settings_file) -> SettingsManager:
    """A fresh SettingsManager instance backed by an isolated temp file."""
    return SettingsManager(file_path=settings_file)


# ===========================================================================
# Initialisation
# ===========================================================================

class TestInitialisation:
    @pytest.mark.integration
    def test_creates_settings_file_on_first_run(self, settings_file):
        SettingsManager(file_path=settings_file)
        assert settings_file.exists()

    @pytest.mark.integration
    def test_default_settings_are_written_to_file(self, settings_file):
        SettingsManager(file_path=settings_file)
        data = json.loads(settings_file.read_text())
        assert "general" in data
        assert "appearance" in data
        assert "llm_configs" in data

    @pytest.mark.integration
    def test_existing_settings_file_is_loaded(self, settings_file):
        # Pre-populate the file with a known value.
        initial = copy.deepcopy(SettingsManager.DEFAULT_SETTINGS)
        initial["general"]["language"] = "fr"
        settings_file.write_text(json.dumps(initial))

        sm = SettingsManager(file_path=settings_file)
        assert sm.get_setting("general", "language") == "fr"

    @pytest.mark.integration
    def test_corrupt_settings_file_falls_back_to_defaults(self, settings_file):
        settings_file.write_text("{ this is not valid json }")
        sm = SettingsManager(file_path=settings_file)
        # Should not crash; should have defaults loaded.
        assert sm.get_general_settings() == SettingsManager.DEFAULT_SETTINGS["general"]


# ===========================================================================
# get_* accessors
# ===========================================================================

class TestGetAccessors:
    @pytest.mark.unit
    def test_get_general_settings_returns_dict(self, sm):
        result = sm.get_general_settings()
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_get_appearance_settings_returns_dict(self, sm):
        result = sm.get_appearance_settings()
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_get_llm_configs_returns_dict(self, sm):
        result = sm.get_llm_configs()
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_get_setting_returns_known_default(self, sm):
        assert sm.get_setting("general", "language") == "en"

    @pytest.mark.unit
    def test_get_setting_returns_default_for_missing_key(self, sm):
        result = sm.get_setting("general", "nonexistent_key", default="fallback")
        assert result == "fallback"

    @pytest.mark.unit
    def test_get_setting_returns_none_for_missing_key_without_default(self, sm):
        result = sm.get_setting("general", "nonexistent_key")
        assert result is None

    @pytest.mark.unit
    def test_get_active_llm_name_returns_string(self, sm):
        name = sm.get_active_llm_name()
        assert isinstance(name, str)

    @pytest.mark.unit
    def test_get_active_llm_config_returns_dict_or_none(self, sm):
        result = sm.get_active_llm_config()
        assert result is None or isinstance(result, dict)

    @pytest.mark.unit
    def test_get_llm_config_returns_none_for_missing(self, sm):
        result = sm.get_llm_config("ThisConfigDoesNotExist")
        assert result is None


# ===========================================================================
# set_setting
# ===========================================================================

class TestSetSetting:
    @pytest.mark.integration
    def test_set_setting_updates_in_memory_value(self, sm):
        sm.set_setting("general", "language", "de")
        assert sm.get_setting("general", "language") == "de"

    @pytest.mark.integration
    def test_set_setting_persists_to_file(self, sm, settings_file):
        sm.set_setting("general", "language", "nl")
        data = json.loads(settings_file.read_text())
        assert data["general"]["language"] == "nl"

    @pytest.mark.integration
    def test_set_setting_creates_new_category_if_missing(self, sm):
        sm.set_setting("custom_section", "my_key", 42)
        assert sm.get_setting("custom_section", "my_key") == 42

    @pytest.mark.integration
    def test_set_setting_returns_true_on_success(self, sm):
        result = sm.set_setting("general", "fast_tts", True)
        assert result is True


# ===========================================================================
# LLM config helpers
# ===========================================================================

class TestLLMConfigs:
    @pytest.fixture()
    def sample_config(self):
        return {
            "provider": "TestProvider",
            "endpoint": "https://example.com/v1",
            "model": "test-model",
            "api_key": "secret",
            "timeout": 30,
        }

    @pytest.mark.integration
    def test_update_llm_config_adds_new_entry(self, sm, sample_config):
        sm.update_llm_config("MyLLM", sample_config)
        result = sm.get_llm_config("MyLLM")
        assert result is not None
        assert result["provider"] == "TestProvider"

    @pytest.mark.integration
    def test_update_llm_config_overwrites_existing_entry(self, sm, sample_config):
        sm.update_llm_config("MyLLM", sample_config)
        updated = {**sample_config, "model": "new-model"}
        sm.update_llm_config("MyLLM", updated)
        assert sm.get_llm_config("MyLLM")["model"] == "new-model"

    @pytest.mark.integration
    def test_update_llm_config_returns_true(self, sm, sample_config):
        result = sm.update_llm_config("MyLLM", sample_config)
        assert result is True

    @pytest.mark.integration
    def test_get_llm_config_returns_copy_not_reference(self, sm, sample_config):
        """Mutating the returned dict must not affect stored settings."""
        sm.update_llm_config("MyLLM", sample_config)
        cfg = sm.get_llm_config("MyLLM")
        cfg["api_key"] = "MODIFIED"
        assert sm.get_llm_config("MyLLM")["api_key"] == "secret"

    @pytest.mark.integration
    def test_update_llm_configs_sets_active_config(self, sm, sample_config):
        configs = {"LLM_A": sample_config, "LLM_B": {**sample_config, "provider": "Other"}}
        sm.update_llm_configs(configs, default="LLM_B")
        assert sm.get_active_llm_name() == "LLM_B"


# ===========================================================================
# sanitize / path helpers
# ===========================================================================

class TestPathHelpers:
    @pytest.mark.unit
    def test_sanitize_strips_non_word_characters(self, sm):
        assert sm.sanitize("My Project!") == "MyProject"

    @pytest.mark.unit
    def test_sanitize_empty_string(self, sm):
        assert sm.sanitize("") == ""

    @pytest.mark.unit
    def test_sanitize_keeps_alphanumeric_and_underscore(self, sm):
        assert sm.sanitize("hello_world123") == "hello_world123"

    @pytest.mark.unit
    def test_get_project_relpath_contains_projects_folder(self, sm):
        path = sm.get_project_relpath("MyProject", "compendium.json")
        assert "Projects" in path
        assert "compendium.json" in path

    @pytest.mark.unit
    def test_get_project_relpath_sanitizes_project_name(self, sm):
        path = sm.get_project_relpath("My Project!", "data.json")
        # Special characters should be stripped
        assert "!" not in path
        assert " " not in path

    @pytest.mark.unit
    def test_is_project_file_path_true_for_valid_path(self, sm):
        assert sm.is_project_file_path("Projects/MyProject/compendium.json") is True

    @pytest.mark.unit
    def test_is_project_file_path_false_for_non_project_path(self, sm):
        assert sm.is_project_file_path("settings.json") is False

    @pytest.mark.unit
    def test_is_project_file_path_false_for_directory_path(self, sm):
        # No file extension → should return False
        assert sm.is_project_file_path("Projects/MyProject/") is False

