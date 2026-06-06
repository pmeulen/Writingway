from __future__ import annotations

import logging
from gettext import gettext as _
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QMainWindow

from compendium.compendium_manager import CompendiumEventBus, CompendiumManager
from compendium.compendium_window_pane import CompendiumWindowPresenter, CompendiumWindowWidget

if TYPE_CHECKING:
    from workbench import WorkbenchWindow

logger = logging.getLogger(__name__)

class EnhancedCompendiumWindow2(QMainWindow):
    """
    Parallel MVP implementation of the Enhanced Compendium Window, intended to be a more maintainable and extensible version of the original

    Enhanced Compendium Window - A comprehensive interface for managing compendium data
    with categories, entries, tags, relationships, details, and images.
    """

    def __init__(self, parent: WorkbenchWindow | None) -> None:
        """
        Initialize the Enhanced Compendium Window.

        Args:
            project_name (str): Name of the project
            parent: Parent widget
        """
        logger.debug("Initializing Enhanced Compendium Window 2. parent=%s",
                     type(parent).__name__ if parent else "None")
        super().__init__(parent)
        from workbench import WorkbenchWindow  # avoid circular import at the top level
        if not isinstance(parent, WorkbenchWindow):
            raise TypeError("EnhancedCompendiumWindow must be initialized with a WorkbenchWindow parent")
        self.parent_window: WorkbenchWindow = parent

        # Shared event bus: notifies all listeners (this window, project panel, POV selector, …) whenever
        # the compendium file is written.
        self.event_bus = CompendiumEventBus.get_instance()

        # Model. The project is "default" until the window becomes visible / a
        # project is selected (behaviour added in later steps).
        self.project_name = "default"
        self.manager = CompendiumManager(self.project_name, event_bus=self.event_bus)

        # MVP: A coordinating presenter owns the three child presenters that lays out the three child Views.
        # The panes are currently empty skeletons.
        self.presenter = CompendiumWindowPresenter(self.manager)
        self.window_view = CompendiumWindowWidget(self.presenter)
        self.presenter.set_window_view(self.window_view)
        self.setCentralWidget(self.window_view)

        self.setWindowTitle(_("Enhanced Compendium 2"))
        self.resize(900, 700)

    def open_with_entry(self, project_name: str, entry_uuid: str | None) -> None:
        # TODO: Switch projects to uuid
        """Make visible and raise window, then show the entry.
        """

        logger.info(f"Opening Enhanced Compendium Window 2. project_uuid={project_name}, entry_uuid={entry_uuid}")
        # Show the window before prompting so the dialog context is obvious.
        self._ensure_window_visible()

    def _ensure_window_visible(self) -> None:
        """Ensure this window is restored, visible, and focused for user prompts."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
