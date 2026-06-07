"""
Entry Editor pane for the (MVP) Enhanced Compendium window.

Per ``tasks/mvp.md`` (house rule): one module owns one pane and contains:

* ``IEntryEditorView`` - the View contract (Presenter -> View), an ``ABC``.
* ``EntryEditorEvents`` - the View -> Presenter contract, a ``Protocol``.
* ``EntryEditorPresenter`` - PyQt-free decisions/orchestration.
* ``EntryEditorWidget`` - the humble Qt View (the only PyQt5 code here).

The pane is currently a skeleton: the contracts, presenter and widget are all
empty of behaviour.  Functionality (loading an entry, dirty tracking,
save/revert, tags/relationships/images, …) will be added in later steps.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from gettext import gettext as _
from typing import TYPE_CHECKING, Protocol

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from compendium.qt_mvp import QtWidgetABCMeta

if TYPE_CHECKING:
    from compendium.compendium_manager import CompendiumManager
    from compendium.compendium_types import CompendiumCoordinator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IEntryEditorView (Presenter -> View)
# ---------------------------------------------------------------------------
class IEntryEditorView(ABC):
    """Contract the ``EntryEditorPresenter`` relies on. No PyQt types appear here."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
        ...


# ---------------------------------------------------------------------------
# EntryEditorEvents (View -> Presenter)
# ---------------------------------------------------------------------------
class EntryEditorEvents(Protocol):
    """What the entry-editor view can tell its presenter. Implemented by the presenter."""

    # Intent methods (e.g. ``on_overview_changed``, ``on_save_requested``) will be added in later steps.


# ---------------------------------------------------------------------------
# EntryEditorPresenter (PyQt-free)
# ---------------------------------------------------------------------------
class EntryEditorPresenter:
    """PyQt-free presenter for the entry editor pane.

    Connects to the ``CompendiumManager`` model and reports cross-pane intents
    to the coordinating presenter.  Currently a skeleton.
    """

    def __init__(self, compendium: CompendiumManager, coordinator: CompendiumCoordinator) -> None:
        logger.debug("Initializing EntryEditorPresenter")
        self._compendium = compendium
        self._coordinator = coordinator
        self._view: IEntryEditorView | None = None

    def set_view(self, view: IEntryEditorView) -> None:
        """Give the presenter its View once both objects exist."""
        self._view = view

    def reset_for_project(self, project_name: str) -> None:
        """Skeleton: log the project switch. Real behaviour added later."""
        logger.info(f"EntryEditorPresenter reset_for_project: {project_name}")


# ---------------------------------------------------------------------------
# EntryEditorWidget (the only PyQt5 code in this module)
# ---------------------------------------------------------------------------
class EntryEditorWidget(QWidget, IEntryEditorView, metaclass=QtWidgetABCMeta):
    """Humble Qt View for the entry editor pane. Currently a skeleton."""

    def __init__(self, events: EntryEditorEvents) -> None:
        super().__init__()
        self._events = events
        self._setup_widgets()
        self._connect_signals()

    def _setup_widgets(self) -> None:
        """Build the editor widgets. Ported from EnhancedCompendiumWindow."""
        # Main layout for the entire pane
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Main splitter to mirror the EnhancedCompendiumWindow layout (Content | Tags)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(self.content_splitter)

        # 1) Center Widget (Header + Tabs)
        self.center_widget = QWidget()
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._setup_header(center_layout)
        self._setup_tabs(center_layout)

        self.content_splitter.addWidget(self.center_widget)

        # 2) Right Widget (Tags)
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._setup_tags_panel(right_layout)

        self.content_splitter.addWidget(self.right_widget)

        # Set proportions similar to EnhancedCompendiumWindow (2:1 for content:tags)
        self.content_splitter.setStretchFactor(0, 2)
        self.content_splitter.setStretchFactor(1, 1)

    def _setup_header(self, layout: QVBoxLayout) -> None:
        """Create the header with entry name and buttons."""
        self.header_widget = QWidget()
        self.header_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.entry_name_label = QLabel(_("No entry selected"))
        self.entry_name_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(self.entry_name_label)
        header_layout.addStretch()

        self.revert_button = QPushButton(_("Revert"))
        self.revert_button.setToolTip(_("Discard all unsaved changes to this entry"))
        self.revert_button.setEnabled(False)
        self.revert_button.hide()
        header_layout.addWidget(self.revert_button)

        self.save_button = QPushButton(_("Save Changes"))
        self.save_button.setEnabled(False)
        self.save_button.hide()
        header_layout.addWidget(self.save_button)

        layout.addWidget(self.header_widget)

    def _setup_tabs(self, layout: QVBoxLayout) -> None:
        """Create the tab widget with Overview, Details, Relationships, and Images."""
        self.tabs = QTabWidget()

        # Overview tab
        self.overview_tab = QWidget()
        overview_layout = QVBoxLayout(self.overview_tab)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(_("This is the text the AI can see if you select this entry to be included in the prompt inside the context panel"))
        overview_layout.addWidget(self.editor)
        self.tabs.addTab(self.overview_tab, _("Overview"))
        self.tabs.setTabToolTip(0, _("this is the text the AI can see if you select this entry to be included in the prompt inside the context panel"))

        # Details tab
        self.details_editor = QTextEdit()
        self.details_editor.setPlaceholderText(_("Enter details about your entry here... (details about your entry the AI can't see - this info is only for you)"))
        self.tabs.addTab(self.details_editor, _("Details"))
        self.tabs.setTabToolTip(1, _("details about your entry the AI can't see - this info is only for you"))

        # Relationships tab
        self.relationships_tab = QWidget()
        relationships_layout = QVBoxLayout(self.relationships_tab)
        self.relationships_form = QGroupBox(_("Relationships"))
        form_layout = QFormLayout()
        self.relationship_combo = QComboBox()
        self.relationship_type = QLineEdit()
        self.add_relationship_button = QPushButton(_("Add Relationship"))
        form_layout.addRow(_("Related Entry:"), self.relationship_combo)
        form_layout.addRow(_("Relationship Type:"), self.relationship_type)
        form_layout.addRow(self.add_relationship_button)
        self.relationships_form.setLayout(form_layout)
        self.relationships_list = QTreeWidget()
        self.relationships_list.setHeaderLabels([_("Name"), _("Type")])
        relationships_layout.addWidget(self.relationships_form)
        relationships_layout.addWidget(self.relationships_list)
        self.tabs.addTab(self.relationships_tab, _("Relationships"))

        # Images tab
        self.image_widget = QWidget()
        images_layout = QVBoxLayout(self.image_widget)
        self.images_tab_bar = QTabWidget() # Internal tab bar for images as per original code
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll_content = QWidget()
        self.image_layout = QHBoxLayout(self.image_scroll_content)
        self.image_scroll.setWidget(self.image_scroll_content)
        self.images_tab_bar.addTab(self.image_scroll, _("Images"))
        self.add_image_button = QPushButton(_("Add Image"))
        images_layout.addWidget(self.images_tab_bar)
        images_layout.addWidget(self.add_image_button)
        self.tabs.addTab(self.image_widget, _("Images"))

        layout.addWidget(self.tabs)
        layout.addStretch()

    def _setup_tags_panel(self, layout: QVBoxLayout) -> None:
        """Create the right panel for tags management."""
        self.tags_form = QGroupBox(_("Tags"))
        form_layout = QFormLayout()
        self.tag_input = QLineEdit()

        # Color selector row
        color_row = QHBoxLayout()
        self.tag_color_preview = QFrame()
        self.tag_color_preview.setFixedSize(24, 24)
        self.tag_color_preview.setFrameShape(QFrame.Shape.Box)
        self.tag_color_preview.setStyleSheet("background-color: #000000;")
        self._current_tag_color = "#000000"
        color_row.addWidget(self.tag_color_preview)
        color_row.addStretch()
        self.tag_color_button = QPushButton(_("Set..."))
        color_row.addWidget(self.tag_color_button)
        color_row_widget = QWidget()
        color_row_widget.setLayout(color_row)

        self.add_tag_button = QPushButton(_("Add Tag"))
        self.add_tag_button.setEnabled(False)

        form_layout.addRow(_("Tag:"), self.tag_input)
        form_layout.addRow(_("Color:"), color_row_widget)
        form_layout.addRow(self.add_tag_button)
        self.tags_form.setLayout(form_layout)

        self.tags_list = QListWidget()
        self.tags_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        layout.addWidget(self.tags_form)
        layout.addWidget(self.tags_list)

    def _connect_signals(self) -> None:
        """Connect UI signals to the presenter (stubbed as per existing events)."""
        # Note: Functional connection to events will be added once EntryEditorEvents is populated.

    def reset(self) -> None:
        """Reset the pane to its empty state. (Behaviour added in later steps.)"""
