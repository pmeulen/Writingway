import importlib.metadata
import logging
import sys
from settings.translation_manager import TranslationManager # must import before gettext
from gettext import gettext as _

# Save the original metadata function
_orig_version = importlib.metadata.version

def _is_frozen():
    """True when running inside a PyInstaller (or similar) bundle."""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def hooked_version(distribution_name):
    """
    Wrapper around importlib.metadata.version that logs a diagnostic when a package's metadata is missing.

    For a pyinstaller build, you can fix this in the .spec file by adding a call to `_collect('<package>')`
    or at minimum `copy_metadata('<package>')`, then rebuild.
    """
    try:
        return _orig_version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        # These packages also throw PackageNotFoundError's when running for the development venv. Ignore them.
        ignore_missing_packages = ("optree", "google.protobuf")
        if distribution_name in ignore_missing_packages:
            raise # Re-raise so the original failure semantics are preserved.

        frozen = _is_frozen()
        msg = (
            "WARNING: Missing package metadata for: '{pkg}'\n"
            "         Add the package metadata to the pyinstaller .spec file using:\n"
            "            copy_metadata('{pkg}')\n"
            "         or\n"
            "            _collect)all(pkg)\n"
        ) if frozen else  (
            "WARNING: Missing package metadata for: '{pkg}'\n"
        )

        # Log message to stderr and log
        msg=msg.format(pkg=distribution_name)
        print(msg , file=sys.stderr)
        logging.error(msg)

        # Re-raise so the original failure semantics are preserved.
        raise


# Overwrite the built-in method before moviepy can call it
importlib.metadata.version = hooked_version

import whisper

from settings.settings_manager import WWSettingsManager


def exception_hook(exctype, value, traceback):
    logging.error("Unhandled exception", exc_info=(exctype, value, traceback))
    sys.__excepthook__(exctype, value, traceback)
sys.excepthook = exception_hook

def check_dependencies():
    """Check for required modules and notify the user via Tkinter if any are missing."""
    missing = []
    try:
        import PyQt5
    except ImportError:
        missing.append("PyQt5")
    try:
        import pyttsx3
    except ImportError:
        missing.append("pyttsx3")

    if missing:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                _("Missing Dependencies"),
                _("The application requires the following module(s): ") + ", ".join(missing) +
                _("\n\nPlease install them by running:\n\npip install ") + " ".join(missing) +
                _("\n\nOn Windows: Win+R to open a console, then type cmd.")
            )
        except Exception:
            print("The application requires the following module(s): " + ", ".join(missing))
            print("Please install them by running:\n\npip install " + " ".join(missing))
        sys.exit(1)

# Initialize translations
translation_manager = TranslationManager()
translation_manager.set_language(WWSettingsManager.get_general_settings().get("language", "en"))

# Run dependency check after gettext is set up
check_dependencies()

from PyQt5.QtWidgets import QApplication

from settings.theme_manager import ThemeManager
from workbench import WorkbenchWindow


def writingway_preload_settings(app):
    theme = WWSettingsManager.get_appearance_settings()["theme"]
    try:
        ThemeManager.apply_to_app(theme)
        # Connect to theme change signal to update all windows
        theme_manager = ThemeManager()  # Get the singleton instance
        theme_manager.themeChanged.connect(on_theme_changed)
    except Exception as e:
        print("Error applying theme:", e)

    fontsize = WWSettingsManager.get_appearance_settings()["text_size"]
    if fontsize:
        font = app.font()
        font.setPointSize(fontsize)
        app.setFont(font)

def on_theme_changed(theme_name):
    """Callback when theme changes to refresh all project windows."""
    # This will be called when any project window changes the theme
    # The theme manager will emit this signal and all windows should refresh

def main():
    app = QApplication(sys.argv)
    writingway_preload_settings(app)
    window = WorkbenchWindow(translation_manager)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
