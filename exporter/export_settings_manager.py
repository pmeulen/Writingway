import json
import logging
import os
from typing import Any

from settings.settings_manager import WWSettingsManager

logger = logging.getLogger(__name__)

class ExportSettingsManager:
    """
    Manages saving and loading of export preferences per project.
    Supports versioning for future backward compatibility.
    """

    CURRENT_VERSION = 1
    FILENAME = "export_format.json"

    def __init__(self, project_name: str):
        self.project_name = project_name
        self.file_path = self._get_file_path()

    def _get_file_path(self) -> str:
        sanitized = WWSettingsManager.sanitize(self.project_name)
        project_dir = WWSettingsManager.get_project_path(sanitized)
        os.makedirs(project_dir, exist_ok=True)
        return os.path.join(project_dir, self.FILENAME)

    def load_settings(self) -> dict[str, Any]:
        """Load settings with backward compatibility."""
        default = self._get_default_settings()

        if not os.path.exists(self.file_path):
            return default

        try:
            with open(self.file_path, encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("version", 0)

            if version == self.CURRENT_VERSION:
                settings = data.get("settings", {})
            else:
                # Future migration logic
                settings = self._migrate_settings(data, version)

            # Merge with defaults to ensure all keys exist
            merged = {**default["settings"], **settings}
            return {"version": self.CURRENT_VERSION, "settings": merged}

        except Exception:
            logger.exception("Error loading export settings:")
            return default

    def save_settings(self, settings: dict[str, Any]):
        """Save current settings with version."""
        data = {
            "version": self.CURRENT_VERSION,
            "settings": settings
        }
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception:
            logger.exception("Error saving export settings: ")

    def _get_default_settings(self) -> dict[str, Any]:
        return {
            "version": self.CURRENT_VERSION,
            "settings": {
                "title": "",
                "author": "Unknown Author",
                "format": "EPUB",
                "include_prompts": False,
                "include_summaries": False,
                "heading_text": "Chapter {number}",
                "font_family": "Georgia",
                "font_size": 14,
                "hr_index": 0,
                "hr_percent": 100,
                "last_output_path": ""
            }
        }

    def _migrate_settings(self, data: dict, old_version: int) -> dict:
        """Handle future migrations."""
        settings = data.get("settings", {})
        # Example: if old_version == 0: add new keys...
        return settings
