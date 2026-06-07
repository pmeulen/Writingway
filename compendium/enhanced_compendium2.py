from __future__ import annotations

import logging
from gettext import gettext as _
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QMainWindow

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

        # MVP: The CompendiumWindowPresenter is the coordinating presenter that owns the three child presenters
        # that are connected to the three panes (toolbar, tree, editor).
        self.presenter = CompendiumWindowPresenter(None)    # Create with no project selected

        from workbench import SimpleWorkbenchProjectsAdapter

        adapter = SimpleWorkbenchProjectsAdapter()

        # MVP: The CompendiumWindowWidget is the main window view that contains the three panes (toolbar, tree, editor)
        # and implements the ICompendiumWindowView contract.
        self.window_view = CompendiumWindowWidget(self.presenter)
        self.presenter.set_window_view(self.window_view)

        self.setCentralWidget(self.window_view) # QMainWindow.setCentralWidget()

        # Wire the adapter into the ProjectToolbarPresenter (replaces the old direct
        # load_projects + toolbar_presenter.load_projects path).
        toolbar_presenter = self.presenter.toolbar_presenter
        toolbar_presenter.set_workbench_projects_model(adapter)

        self.setWindowTitle(_("Enhanced Compendium 2"))
        self.resize(900, 700)

    def open_with_entry(self, project_name: str, entry_uuid: str | None) -> None:
        # TODO: Switch projects to uuid
        """Make visible and raise window. Switch to "project" if needed. Then select "entry_uuid" in that project."""

        logger.info(f"Opening Enhanced Compendium Window 2. project_uuid={project_name}, entry_uuid={entry_uuid}")

        if project_name:
            self.presenter.switch_to_project(project_name)

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

    def closeEvent(self, event) -> None:
        """Ensure presenters are cleaned up (listeners unregistered) when the window closes."""
        if hasattr(self, "presenter") and hasattr(self.presenter, "destroy"):
            try:
                self.presenter.destroy()
            except Exception:
                logger.warning("destroy() on presenter raised an exception during closeEvent", exc_info=True)
        super().closeEvent(event)
