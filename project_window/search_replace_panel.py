import re
from gettext import gettext as _
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QTextCursor, QTextDocument
from PyQt5.QtWidgets import (
    QAction,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from settings.theme_manager import ThemeManager

if TYPE_CHECKING:
    from .project_model import ProjectModel
    from .project_window import ProjectWindow

SEARCH_DELAY = 500
MATCH_CONTEXT_LENGTH = 20  # Number of characters to show before and after the match

# Unicode ranges for CJK characters
CJK_RANGES = [
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0xFF00, 0xFFEF),  # Full-width forms (includes CJK punctuation)
]

def is_cjk_char(char):
    """Check if a character is in CJK Unicode ranges."""
    if not char:
        return False
    codepoint = ord(char)
    return any(start <= codepoint <= end for start, end in CJK_RANGES)

def is_cjk_text(text):
    """Check if the text contains CJK characters (at least 50% of characters)."""
    if not text:
        return False
    cjk_count = sum(1 for char in text if is_cjk_char(char))
    return cjk_count / len(text) >= 0.5

def is_sentence_start(plain_content, position):
    """Check if the position is at the start of a sentence (after a period, possibly with spaces)."""
    if position == 0:
        return False
    # Look backward for the first non-space character
    i = position - 1
    while i >= 0 and plain_content[i].isspace():
        i -= 1
    return i >= 0 and plain_content[i] == "."

def find_next_non_space_char(plain_content, position):
    """Find the position of the next non-space character starting from position."""
    i = position
    while i < len(plain_content) and plain_content[i].isspace():
        i += 1
    return i if i < len(plain_content) else -1

class UndoButton(QPushButton):
    """Custom button for undo action in tree items."""
    # Emitted with (item: QTreeWidgetItem)
    clicked_with_item: pyqtSignal = pyqtSignal(QTreeWidgetItem)  # Signal to pass the associated item

    def __init__(self, item, tint_color):
        super().__init__()
        self.item = item
        self.setIcon(ThemeManager.get_tinted_icon("assets/icons/refresh-ccw.svg", tint_color))
        self.setToolTip(_("Undo replacement"))
        self.setFixedSize(20, 20)  # Compact size for icon
        self.setStyleSheet("QPushButton { border: none; }")
        self.clicked.connect(self.emit_clicked_with_item)

    def emit_clicked_with_item(self):
        self.clicked_with_item.emit(self.item)

class MatchItemWidget(QWidget):
    """Custom widget for tree items, showing context and optional undo button."""
    def __init__(self, context, item, tint_color, show_undo=False):
        super().__init__()
        self.item = item
        self.tint_color = tint_color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 20, 0) # Need margin for scrollbar in order to see undo icon
        layout.setSpacing(4)
        # Context label
        self.context_label = QLabel(context)
        self.context_label.setWordWrap(False)
        layout.addWidget(self.context_label, stretch=1)
        # Undo button (optional)
        if show_undo:
            self.undo_button = UndoButton(item, tint_color)
            layout.addWidget(self.undo_button)
        layout.addStretch()

class SearchReplacePanel(QWidget):
    """Panel for searching text across the latest scene files."""
    def __init__(self, controller: "ProjectWindow", model: "ProjectModel", tint_color: QColor = QColor("black")):
        super().__init__()
        self.controller = controller
        self.model = model
        self.tint_color = tint_color
        self.current_match = None
        self.matches = []
        self.is_regex = False
        self.search_text = ""  # Track current search term
        self.extra_selections = []  # Store extra selections for highlighting
        self._programmatic_change = False  # Flag for programmatic changes
        self.init_ui()
        # Connect to editor's textChanged signal to refresh results after edits
        self.controller.scene_editor.editor.textChanged.connect(self.schedule_search_refresh)
        # Connect to search input to clear highlights and trigger search
        self.search_input.textChanged.connect(self.on_search_input_changed)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        search_layout = QHBoxLayout()

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_("Search in scenes..."))
        search_layout.addWidget(self.search_input)

        # Menu button
        self.menu_button = QToolButton()
        self.menu_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/more-vertical.svg", self.tint_color))
        self.menu_button.setToolTip(_("Search options"))
        self.menu = QMenu(self)

        # Regex toggle action
        self.regex_action = QAction(_("Regex Search"), self)
        self.regex_action.setCheckable(True)
        self.regex_action.toggled.connect(self.on_regex_toggled)
        self.menu.addAction(self.regex_action)

        # Replace toggle action
        self.replace_action = QAction(_("Show Replace"), self)
        self.replace_action.setCheckable(True)
        self.replace_action.toggled.connect(self.toggle_replace)
        self.menu.addAction(self.replace_action)

        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        search_layout.addWidget(self.menu_button)

        # Replace section (collapsed by default)
        self.replace_container = QWidget()
        self.replace_layout = QHBoxLayout(self.replace_container)
        self.replace_layout.setContentsMargins(0, 0, 0, 0)
        self.replace_layout.setSpacing(2)
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText(_("Replace with..."))
        self.replace_button = QPushButton()
        self.replace_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/edit.svg", self.tint_color))
        self.replace_button.setToolTip(_("Replace current match"))
        self.replace_button.clicked.connect(self.replace_current)
        self.replace_all_button = QPushButton()
        self.replace_all_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/repeat.svg", self.tint_color))
        self.replace_all_button.setToolTip(_("Replace all matches"))
        self.replace_all_button.clicked.connect(self.replace_all)
        self.replace_layout.addWidget(self.replace_input, stretch=1)
        self.replace_layout.addWidget(self.replace_button)
        self.replace_layout.addWidget(self.replace_all_button)
        self.replace_container.setVisible(False)

        # Navigation buttons
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton()
        self.prev_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-up.svg", self.tint_color))
        self.prev_button.setToolTip(_("Previous match"))
        self.prev_button.clicked.connect(self.goto_previous_match)
        self.next_button = QPushButton()
        self.next_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-down.svg", self.tint_color))
        self.next_button.setToolTip(_("Next match"))
        self.next_button.clicked.connect(self.goto_next_match)
        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)

        # Results tree
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels([_("Search Results")])
        self.results_tree.itemClicked.connect(self.on_result_clicked)
        self.results_tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.results_tree.keyPressEvent = self.keyPressEvent
        self.results_tree.setIndentation(2)  # Reduced indentation for left-justified appearance

        layout.addLayout(search_layout)
        layout.addWidget(self.replace_container)
        layout.addLayout(nav_layout)
        layout.addWidget(self.results_tree)

        # Timer for delayed search refresh after edits
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.on_search)

    def keyPressEvent(self, event):
        """Handle keyboard navigation for the results tree."""
        if event.key() == Qt.Key.Key_Up:
            current_item = self.results_tree.currentItem()
            if current_item:
                current_index = self.results_tree.indexOfTopLevelItem(current_item) if current_item.parent() is None else current_item.parent().indexOfChild(current_item)
                parent = current_item.parent()
                if parent:
                    if current_index > 0:
                        prev_item = parent.child(current_index - 1)
                    else:
                        prev_item = parent
                else:
                    if current_index > 0:
                        prev_item = self.results_tree.topLevelItem(current_index - 1)
                    else:
                        prev_item = None
                if prev_item and prev_item.childCount() > 0:
                    prev_item = prev_item.child(prev_item.childCount() - 1)
                if prev_item and prev_item.data(0, Qt.ItemDataRole.UserRole):
                    self.results_tree.setCurrentItem(prev_item)
                    self.on_result_clicked(prev_item, 0)
        elif event.key() == Qt.Key.Key_Down:
            current_item = self.results_tree.currentItem()
            if current_item:
                if current_item.childCount() > 0:
                    next_item = current_item.child(0)
                else:
                    current_index = self.results_tree.indexOfTopLevelItem(current_item) if current_item.parent() is None else current_item.parent().indexOfChild(current_item)
                    parent = current_item.parent()
                    if parent:
                        if current_index < parent.childCount() - 1:
                            next_item = parent.child(current_index + 1)
                        else:
                            next_parent_index = self.results_tree.indexOfTopLevelItem(parent) + 1
                            next_item = self.results_tree.topLevelItem(next_parent_index) if next_parent_index < self.results_tree.topLevelItemCount() else None
                    else:
                        next_index = current_index + 1
                        next_item = self.results_tree.topLevelItem(next_index) if next_index < self.results_tree.topLevelItemCount() else None
                if next_item and next_item.data(0, Qt.ItemDataRole.UserRole):
                    self.results_tree.setCurrentItem(next_item)
                    self.on_result_clicked(next_item, 0)
        else:
            super().keyPressEvent(event)

    def schedule_search_refresh(self):
        """Schedule a refresh of search results after a delay."""
        if self.search_input.text().strip() and not self._programmatic_change:
            self.matches = []  # Clear matches on manual edit to avoid stale replacements
            self.current_match = None
            self.refresh_timer.start(SEARCH_DELAY)  # Delay to avoid excessive refreshes

    def clear_extra_selections(self):
        """Clear all extra selections in the editor."""
        editor = self.controller.scene_editor.editor
        self.extra_selections = []
        editor.setExtraSelections(self.extra_selections)

    def on_search_input_changed(self):
        """Handle search input changes, triggering search or clearing results."""
        search_text = self.search_input.text().strip()
        if len(search_text) < 3:
            self.clear_extra_selections()
            self.results_tree.clear()
            self.matches = []
            self.current_match = None  # Reset current_match to avoid stale references
            self.search_text = ""
            return
        self.clear_extra_selections()
        self.matches = []  # Clear matches to ensure new search
        self.current_match = None
        self.refresh_timer.start(SEARCH_DELAY)  # Schedule search with delay

    def get_single_line_context(self, text, pos, match_length):
        """Extract context around a match, stopping at newlines."""
        # Find the start of the line (up to MATCH_CONTEXT_LENGTH characters before)
        start_pos = max(0, pos - MATCH_CONTEXT_LENGTH)
        prev_newline = text.rfind('\n', 0, pos)
        if prev_newline != -1 and prev_newline >= start_pos:
            start_pos = prev_newline + 1
        # Find the end of the line (up to MATCH_CONTEXT_LENGTH characters after)
        end_pos = min(len(text), pos + match_length + MATCH_CONTEXT_LENGTH)
        next_newline = text.find('\n', pos + match_length)
        if next_newline != -1 and next_newline <= end_pos:
            end_pos = next_newline
        # Extract context
        context = text[start_pos:end_pos]
        # Add ellipses if truncated
        if start_pos > 0 and text[start_pos - 1] != '\n':
            context = "..." + context
        if end_pos < len(text) and text[end_pos] != '\n':
            context += "..."
        return context

    def on_search(self):
        """Perform search across the latest scene content."""
        self.controller.check_unsaved_changes()
        self.clear_extra_selections()  # Clear highlights on new search
        self.results_tree.clear()
        self.matches = []
        self.current_match = None  # Reset current_match to avoid stale references
        self.search_text = self.search_input.text().strip()
        if len(self.search_text) < 3:
            return

        try:
            pattern = re.compile(self.search_text, re.IGNORECASE) if self.is_regex else None
        except re.error:
            self.controller.statusBar().showMessage(_("Invalid regex pattern"), 5000)
            return

        # Get theme-appropriate background color for parent rows
        parent_bg_color = ThemeManager.get_category_background_color()

        # Create bold font for Act/Chapter/Scene names
        bold_font = QFont()
        bold_font.setBold(True)

        # Iterate through the project structure to find scenes
        structure = self.model.structure
        for act in structure.get("acts", []):
            act_has_matches = False
            act_item = None
            for chapter in act.get("chapters", []):
                chapter_has_matches = False
                chapter_item = None
                for scene in chapter.get("scenes", []):
                    hierarchy = [act["name"], chapter["name"], scene["name"]]
                    content = self.model.load_scene_content(hierarchy)
                    if content is None:
                        continue
                    # Strip UUID comment if present
                    if content.startswith("<!-- UUID:"):
                        content = "\n".join(content.split("\n")[1:])
                    # Convert HTML to plain text for searching
                    doc = QTextDocument()
                    doc.setHtml(content)
                    plain_content = doc.toPlainText()

                    matches = []
                    if self.is_regex:
                        matches = [(m.start(), m.group()) for m in pattern.finditer(plain_content)]
                    else:
                        start = 0
                        while True:
                            idx = plain_content.lower().find(self.search_text.lower(), start)
                            if idx == -1:
                                break
                            matches.append((idx, plain_content[idx:idx+len(self.search_text)]))
                            start = idx + 1

                    if matches:
                        if not act_has_matches:
                            act_item = QTreeWidgetItem(self.results_tree, [act["name"]])
                            act_item.setBackground(0, QBrush(parent_bg_color))
                            act_item.setFont(0, bold_font)
                            act_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
                            act_has_matches = True
                        if not chapter_has_matches:
                            chapter_item = QTreeWidgetItem(act_item, [chapter["name"]])
                            chapter_item.setBackground(0, QBrush(parent_bg_color))
                            chapter_item.setFont(0, bold_font)
                            chapter_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
                            chapter_has_matches = True
                        scene_item = QTreeWidgetItem(chapter_item, [scene["name"]])
                        scene_item.setBackground(0, QBrush(parent_bg_color))
                        scene_item.setFont(0, bold_font)
                        scene_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
                        for pos, match in matches:
                            # Get single-line context around the match
                            context = self.get_single_line_context(plain_content, pos, len(match))
                            match_item = QTreeWidgetItem(scene_item, [""])  # Empty text; widget will set content
                            match_item.setData(0, Qt.ItemDataRole.UserRole, {
                                "hierarchy": hierarchy,
                                "position": pos,
                                "match_text": match,
                                "original_match_text": match  # Store original for undo
                            })
                            # Set widget with context only (no undo button yet)
                            match_widget = MatchItemWidget(context, match_item, self.tint_color, show_undo=False)
                            self.results_tree.setItemWidget(match_item, 0, match_widget)
                            self.matches.append((scene_item, match_item))
        self.results_tree.expandAll()

    def toggle_replace(self, checked):
        """Show/hide replace input and buttons."""
        self.replace_container.setVisible(checked)
        self.replace_button.setEnabled(checked)
        self.replace_all_button.setEnabled(checked)

    def on_regex_toggled(self, checked):
        """Handle regex toggle."""
        self.is_regex = checked
        self.on_search()

    def goto_previous_match(self):
        """Navigate to the previous match."""
        if not self.matches:
            return
        # Sync current_match with the selected tree item
        current_item = self.results_tree.currentItem()
        if current_item and current_item.data(0, Qt.ItemDataRole.UserRole):
            for i, (scene_item, match_item) in enumerate(self.matches):
                if match_item == current_item:
                    self.current_match = (scene_item, match_item)
                    break
        idx = self.matches.index(self.current_match) if self.current_match in self.matches else 0
        idx = (idx - 1) % len(self.matches)
        self.select_match(idx)

    def goto_next_match(self):
        """Navigate to the next match."""
        if not self.matches:
            return
        # Sync current_match with the selected tree item
        current_item = self.results_tree.currentItem()
        if current_item and current_item.data(0, Qt.ItemDataRole.UserRole):
            for i, (scene_item, match_item) in enumerate(self.matches):
                if match_item == current_item:
                    self.current_match = (scene_item, match_item)
                    break
        idx = self.matches.index(self.current_match) if self.current_match in self.matches else -1
        idx = (idx + 1) % len(self.matches)
        self.select_match(idx)

    def select_match(self, index):
        """Select a match, save current changes, and load its scene with highlighting."""
        # Save unsaved changes before switching scenes
        self.controller.check_unsaved_changes()

        self.current_match = self.matches[index]
        scene_item, match_item = self.current_match
        self.results_tree.setCurrentItem(match_item)
        hierarchy = match_item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"]
        position = match_item.data(0, Qt.ItemDataRole.UserRole)["position"]
        stored_match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["match_text"]
        self._programmatic_change = True

        try:
            self.controller.load_scene_from_hierarchy(hierarchy)
            editor = self.controller.scene_editor.editor
            # Clear previous extra selections
            self.clear_extra_selections()
            # Convert HTML content to plain text to validate position
            doc = QTextDocument()
            doc.setHtml(editor.toHtml())
            plain_text = doc.toPlainText()
            # Validate position
            if position >= len(plain_text):
                position = len(plain_text) - 1 if plain_text else 0
            # Check if the stored match text still exists at the position
            match_length = len(stored_match_text)
            current_text = plain_text[position:position + match_length] if position + match_length <= len(plain_text) else ""
            if current_text != stored_match_text and self.search_text:
                # Re-search for the current search term starting from the stored position
                start = max(0, position - 50)  # Look back a bit to catch nearby matches
                matches = []
                if self.is_regex:
                    try:
                        pattern = re.compile(self.search_text, re.IGNORECASE)
                        matches = [(m.start(), m.group()) for m in pattern.finditer(plain_text, start)]
                    except re.error:
                        pass
                else:
                    idx = plain_text.lower().find(self.search_text.lower(), start)
                    if idx != -1:
                        matches = [(idx, plain_text[idx:idx+len(self.search_text)])]
                # Find the closest match after the stored position
                closest_pos = None
                closest_match = None
                for pos, match in matches:
                    if pos >= position:
                        if closest_pos is None or pos < closest_pos:
                            closest_pos = pos
                            closest_match = match
                if closest_pos is not None:
                    position = closest_pos
                    match_length = len(closest_match)
                    is_replaced = self.results_tree.itemWidget(match_item, 0).findChild(UndoButton) is not None
                    # Update context in widget
                    context = self.get_single_line_context(plain_text, closest_pos, len(closest_match))
                    match_widget = MatchItemWidget(context, match_item, self.tint_color, show_undo=is_replaced)
                    self.results_tree.setItemWidget(match_item, 0, match_widget)
                    match_item.setData(0, Qt.ItemDataRole.UserRole, {
                        "hierarchy": hierarchy,
                        "position": closest_pos,
                        "match_text": closest_match,
                        "original_match_text": match_item.data(0, Qt.ItemDataRole.UserRole).get("original_match_text", closest_match)
                    })
                else:
                    # No match found, use stored position with zero-length highlight
                    match_length = 0
                    self.controller.statusBar().showMessage(_("Match not found; content may have changed"), 5000)

            cursor = editor.textCursor()
            cursor.setPosition(position)
            # Apply highlight using ExtraSelection
            if match_length > 0:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(cursor)
                selection.cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, match_length)
                selection.format.setBackground(QColor("yellow"))
                self.extra_selections.append(selection)
                editor.setExtraSelections(self.extra_selections)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()
        finally:
            self._programmatic_change = False

    def replace_current(self):
        """Replace the current match while preserving formatting and handling spaces/punctuation."""
        if self.current_match is None or not self.replace_container.isVisible():
            self.controller.statusBar().showMessage(_("Please select a match to replace"), 5000)
            return
        scene_item, match_item = self.current_match
        hierarchy = match_item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"]
        position = match_item.data(0, Qt.ItemDataRole.UserRole)["position"]
        match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["match_text"]
        original_match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["original_match_text"]
        content = self.model.load_scene_content(hierarchy)
        if content is None:
            return
        # Strip UUID comment if present
        if content.startswith("<!-- UUID:"):
            content = "\n".join(content.split("\n")[1:])

        # Load content into QTextDocument
        doc = QTextDocument()
        doc.setHtml(content)
        plain_content = doc.toPlainText()

        # Validate position
        if position + len(match_text) > len(plain_content):
            self.controller.statusBar().showMessage(_("Match position is invalid; content may have changed"), 5000)
            return

        # Verify the match text at the position
        if plain_content[position:position + len(match_text)] != match_text:
            self.controller.statusBar().showMessage(_("Match text does not match; content may have changed"), 5000)
            return

        replace_text = self.replace_input.text()
        cursor = QTextCursor(doc)
        cursor.setPosition(position)
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, len(match_text))

        # Check if the match is in CJK text
        is_cjk = is_cjk_text(match_text)

        space_removed = False
        punctuation_removed = False
        before_char = plain_content[position - 1] if position > 0 else ""
        after_char = plain_content[position + len(match_text)] if position + len(match_text) < len(plain_content) else ""
        space_after = after_char.isspace()  # Check if there's a space after the match

        if replace_text == "" and not is_cjk:
            # Handle empty string replacement for non-CJK text
            is_start_of_sentence = is_sentence_start(plain_content, position)

            # Remove the matched text
            cursor.removeSelectedText()

            # Clean up spaces and punctuation
            if before_char.isspace() and after_char.isspace():
                # Remove one space to avoid double spaces
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                cursor.removeSelectedText()
                space_removed = True
            elif after_char in ",.!?;" and before_char.isspace():
                # Remove space before punctuation
                cursor.setPosition(position - 1 if position > 0 else position)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                if cursor.selectedText().isspace():
                    cursor.removeSelectedText()
                    space_removed = True
                    position -= 1  # Adjust position for removed space

            # Handle sentence start: capitalize next word
            if is_start_of_sentence:
                next_char_pos = find_next_non_space_char(plain_content, position + len(match_text))
                if next_char_pos != -1 and plain_content[next_char_pos].isalpha():
                    cursor.setPosition(next_char_pos)
                    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                    next_char = cursor.selectedText()
                    cursor.removeSelectedText()
                    cursor.insertText(next_char.upper())
                # Remove trailing punctuation if present
                if after_char in ",.!?;" and position + len(match_text) < len(plain_content):
                    cursor.setPosition(position)
                    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                    if cursor.selectedText() in ",.!?;":
                        cursor.removeSelectedText()
                        punctuation_removed = True
        else:
            # Normal replacement (including CJK or non-empty replace_text)
            cursor.insertText(replace_text)  # Insert replacement text, preserving formatting

        # Get updated content
        new_content = doc.toHtml()

        # Save the modified content
        filepath = self.model.save_scene(hierarchy, new_content)
        if filepath:
            self._programmatic_change = True
            try:
                self.controller.load_scene_from_hierarchy(hierarchy)
                # Update match item to show replaced text with undo button
                new_plain_content = doc.toPlainText()
                new_position = position
                if replace_text == "" and not is_cjk:
                    if before_char.isspace() and after_char.isspace():
                        new_position -= 1  # Adjust for removed space
                    elif after_char in ",.!?;" and before_char.isspace():
                        new_position -= 1  # Adjust for removed space before punctuation
                context = self.get_single_line_context(new_plain_content, new_position, len(replace_text))
                match_widget = MatchItemWidget(context, match_item, self.tint_color, show_undo=True)
                self.results_tree.setItemWidget(match_item, 0, match_widget)
                match_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "hierarchy": hierarchy,
                    "position": new_position,
                    "match_text": replace_text,
                    "original_match_text": original_match_text,
                    "space_removed": space_removed,
                    "punctuation_removed": punctuation_removed,
                    "before_char": before_char,
                    "after_char": after_char,
                    "space_after": space_after
                })
                # Connect undo button
                match_widget.undo_button.clicked_with_item.connect(self.undo_replacement)
                # Update self.matches
                for i, (s_item, m_item) in enumerate(self.matches):
                    if m_item == match_item:
                        self.matches[i] = (s_item, m_item)
                        break
                self.controller.statusBar().showMessage(_("Replaced 1 match"), 5000)
            finally:
                self._programmatic_change = False

    def replace_all(self):
        """Replace all matches while preserving formatting and handling spaces/punctuation."""
        if not self.replace_container.isVisible():
            return
        replace_text = self.replace_input.text()
        # Group matches by hierarchy to process each scene once
        scenes_to_update = {}
        modified_hierarchies = set()  # Track modified scenes
        for scene_item, match_item in self.matches:
            hierarchy = match_item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"]
            position = match_item.data(0, Qt.ItemDataRole.UserRole)["position"]
            match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["match_text"]
            original_match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["original_match_text"]
            hierarchy_key = tuple(hierarchy)  # Convert to tuple for hashable dictionary key
            if hierarchy_key not in scenes_to_update:
                scenes_to_update[hierarchy_key] = []
            scenes_to_update[hierarchy_key].append((position, match_text, original_match_text))

        replacement_count = 0
        from PyQt5.QtGui import QTextCursor, QTextDocument
        for hierarchy_key, replacements in scenes_to_update.items():
            hierarchy = list(hierarchy_key)  # Convert back to list for model methods
            modified_hierarchies.add(tuple(hierarchy))
            content = self.model.load_scene_content(hierarchy)
            if content is None:
                continue
            # Strip UUID comment if present
            if content.startswith("<!-- UUID:"):
                content = "\n".join(content.split("\n")[1:])

            # Load content into QTextDocument
            doc = QTextDocument()
            doc.setHtml(content)
            plain_content = doc.toPlainText()

            # Sort replacements in reverse order to avoid position shifts
            replacements.sort(reverse=True)
            cursor = QTextCursor(doc)
            position_adjustments = {}  # Track position shifts for match updates
            match_contexts = {}  # Store context for each match

            for pos, match_text, original_match_text in replacements:
                if pos + len(match_text) > len(plain_content):
                    continue
                # Verify the match text at the position
                if plain_content[pos:pos + len(match_text)] != match_text:
                    continue

                # Check if the match is in CJK text
                is_cjk = is_cjk_text(match_text)
                cursor.setPosition(pos)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, len(match_text))

                space_removed = False
                punctuation_removed = False
                before_char = plain_content[pos - 1] if pos > 0 else ""
                after_char = plain_content[pos + len(match_text)] if pos + len(match_text) < len(plain_content) else ""
                space_after = after_char.isspace()  # Check if there's a space after the match
                position_adjustment = 0

                if replace_text == "" and not is_cjk:
                    # Handle empty string replacement for non-CJK text
                    is_start_of_sentence = is_sentence_start(plain_content, pos)

                    # Remove the matched text
                    cursor.removeSelectedText()

                    # Clean up spaces and punctuation
                    if before_char.isspace() and after_char.isspace():
                        # Remove one space to avoid double spaces
                        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                        cursor.removeSelectedText()
                        space_removed = True
                        position_adjustment = -1
                    elif after_char in ",.!?;" and before_char.isspace():
                        # Remove space before punctuation
                        cursor.setPosition(pos - 1 if pos > 0 else pos)
                        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                        if cursor.selectedText().isspace():
                            cursor.removeSelectedText()
                            space_removed = True
                            position_adjustment = -1
                            pos -= 1

                    # Handle sentence start: capitalize next word
                    if is_start_of_sentence:
                        next_char_pos = find_next_non_space_char(plain_content, pos + len(match_text))
                        if next_char_pos != -1 and plain_content[next_char_pos].isalpha():
                            cursor.setPosition(next_char_pos)
                            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                            next_char = cursor.selectedText()
                            cursor.removeSelectedText()
                            cursor.insertText(next_char.upper())
                        # Remove trailing punctuation if present
                        if after_char in ",.!?;" and pos + len(match_text) < len(plain_content):
                            cursor.setPosition(pos)
                            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                            if cursor.selectedText() in ",.!?;":
                                cursor.removeSelectedText()
                                punctuation_removed = True
                                position_adjustment -= 1
                else:
                    # Normal replacement (including CJK or non-empty replace_text)
                    cursor.insertText(replace_text)
                    position_adjustment = len(replace_text) - len(match_text)

                position_adjustments[pos] = position_adjustment
                match_contexts[pos] = {
                    "space_removed": space_removed,
                    "punctuation_removed": punctuation_removed,
                    "before_char": before_char,
                    "after_char": after_char,
                    "space_after": space_after
                }
                replacement_count += 1

            # Get updated content
            new_content = doc.toHtml()

            # Save the modified content
            filepath = self.model.save_scene(hierarchy, new_content)
            if filepath:
                # Update match items for this scene
                new_plain_content = doc.toPlainText()
                for scene_item, match_item in self.matches:
                    if match_item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"] == hierarchy:
                        pos = match_item.data(0, Qt.ItemDataRole.UserRole)["position"]
                        original_match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["original_match_text"]
                        # Adjust position based on cumulative shifts
                        new_pos = pos
                        for orig_pos, adj in position_adjustments.items():
                            if orig_pos < pos:
                                new_pos += adj
                        context = self.get_single_line_context(new_plain_content, new_pos, len(replace_text))
                        match_widget = MatchItemWidget(context, match_item, self.tint_color, show_undo=True)
                        self.results_tree.setItemWidget(match_item, 0, match_widget)
                        match_widget.undo_button.clicked_with_item.connect(self.undo_replacement)
                        match_item.setData(0, Qt.ItemDataRole.UserRole, {
                            "hierarchy": hierarchy,
                            "position": new_pos,
                            "match_text": replace_text,
                            "original_match_text": original_match_text,
                            "space_removed": match_contexts.get(pos, {}).get("space_removed", False),
                            "punctuation_removed": match_contexts.get(pos, {}).get("punctuation_removed", False),
                            "before_char": match_contexts.get(pos, {}).get("before_char", ""),
                            "after_char": match_contexts.get(pos, {}).get("after_char", ""),
                            "space_after": match_contexts.get(pos, {}).get("space_after", False)
                        })

        # Update self.matches to reflect replacements
        self.matches = [(s, m) for s, m in self.matches]
        self.results_tree.expandAll()
        # Reload current scene if it was modified
        current_scene_hierarchy = self.controller.get_current_scene_hierarchy()
        if current_scene_hierarchy and tuple(current_scene_hierarchy) in modified_hierarchies:
            self._programmatic_change = True
            try:
                self.controller.load_scene_from_hierarchy(current_scene_hierarchy)
            finally:
                self._programmatic_change = False
        self.controller.statusBar().showMessage(_("Replaced {} matches").format(replacement_count), 5000)

    def undo_replacement(self, match_item):
        """Revert a single replacement to the original text, preserving formatting and context."""
        hierarchy = match_item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"]
        position = match_item.data(0, Qt.ItemDataRole.UserRole)["position"]
        match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["match_text"]
        original_match_text = match_item.data(0, Qt.ItemDataRole.UserRole)["original_match_text"]
        space_removed = match_item.data(0, Qt.ItemDataRole.UserRole).get("space_removed", False)
        punctuation_removed = match_item.data(0, Qt.ItemDataRole.UserRole).get("punctuation_removed", False)
        before_char = match_item.data(0, Qt.ItemDataRole.UserRole).get("before_char", "")
        after_char = match_item.data(0, Qt.ItemDataRole.UserRole).get("after_char", "")
        space_after = match_item.data(0, Qt.ItemDataRole.UserRole).get("space_after", False)
        content = self.model.load_scene_content(hierarchy)
        if content is None:
            return
        # Strip UUID comment if present
        if content.startswith("<!-- UUID:"):
            content = "\n".join(content.split("\n")[1:])

        # Load content into QTextDocument
        from PyQt5.QtGui import QTextCursor, QTextDocument
        doc = QTextDocument()
        doc.setHtml(content)
        plain_content = doc.toPlainText()

        # Validate position
        if position > len(plain_content):
            self.controller.statusBar().showMessage(_("Invalid position for undo"), 5000)
            return

        cursor = QTextCursor(doc)
        undo_position = position

        # Adjust position for removed space (e.g., before punctuation)
        if space_removed and before_char.isspace() and after_char in ",.!?;":
            undo_position += 1  # Account for removed space before punctuation
            cursor.setPosition(undo_position)
            cursor.insertText(" ")  # Restore the space before the match
        else:
            cursor.setPosition(undo_position)

        # Remove the current text (empty for "" replacements)
        if match_text:
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, len(match_text))
            cursor.removeSelectedText()

        # Insert original match text
        cursor.insertText(original_match_text)

        # Restore space after match if it existed
        if space_after:
            cursor.insertText(" ")

        # Restore punctuation if removed
        if punctuation_removed and after_char in ",.!?;":
            cursor.insertText(after_char)

        # If sentence start, undo capitalization of the next word
        if is_sentence_start(plain_content, position):
            next_char_pos = find_next_non_space_char(plain_content, position + len(original_match_text))
            if next_char_pos != -1 and plain_content[next_char_pos].isupper():
                cursor.setPosition(next_char_pos)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, 1)
                next_char = cursor.selectedText()
                cursor.removeSelectedText()
                cursor.insertText(next_char.lower())

        # Get updated content
        new_content = doc.toHtml()

        # Save the modified content
        filepath = self.model.save_scene(hierarchy, new_content)
        if filepath:
            # Update match item to show original text without undo button
            new_plain_content = doc.toPlainText()
            new_position = position  # Keep original position for context
            context = self.get_single_line_context(new_plain_content, new_position, len(original_match_text))
            match_widget = MatchItemWidget(context, match_item, self.tint_color, show_undo=False)
            self.results_tree.setItemWidget(match_item, 0, match_widget)
            match_item.setData(0, Qt.ItemDataRole.UserRole, {
                "hierarchy": hierarchy,
                "position": new_position,
                "match_text": original_match_text,
                "original_match_text": original_match_text,
                "space_removed": False,
                "punctuation_removed": False,
                "before_char": "",
                "after_char": "",
                "space_after": False
            })
            # Update self.matches
            for i, (s_item, m_item) in enumerate(self.matches):
                if m_item == match_item:
                    self.matches[i] = (s_item, m_item)
                    break
            # Reload the scene if it’s currently open
            current_scene_hierarchy = self.controller.get_current_scene_hierarchy()
            if current_scene_hierarchy and current_scene_hierarchy == hierarchy:
                self._programmatic_change = True
                try:
                    self.controller.load_scene_from_hierarchy(current_scene_hierarchy)
                finally:
                    self._programmatic_change = False
            self.controller.statusBar().showMessage(_("Undone 1 replacement"), 5000)

    def on_result_clicked(self, item, column):
        """Handle clicking a result item."""
        if item.data(0, Qt.ItemDataRole.UserRole):
            # Save unsaved changes before switching scenes
            self.controller.check_unsaved_changes()
            self._programmatic_change = True

            try:
                hierarchy = item.data(0, Qt.ItemDataRole.UserRole)["hierarchy"]
                position = item.data(0, Qt.ItemDataRole.UserRole)["position"]
                stored_match_text = item.data(0, Qt.ItemDataRole.UserRole)["match_text"]
                self.controller.load_scene_from_hierarchy(hierarchy)
                editor = self.controller.scene_editor.editor
                # Clear previous extra selections
                self.clear_extra_selections()
                # Convert HTML content to plain text to validate position
                doc = QTextDocument()
                doc.setHtml(editor.toHtml())
                plain_text = doc.toPlainText()
                # Validate position
                if position >= len(plain_text):
                    position = len(plain_text) - 1 if plain_text else 0
                # Check if the stored match text still exists at the position
                match_length = len(stored_match_text)
                current_text = plain_text[position:position + match_length] if position + match_length <= len(plain_text) else ""
                if current_text != stored_match_text and self.search_text:
                    # Re-search for the current search term starting from the stored position
                    start = max(0, position - 50)  # Look back a bit to catch nearby matches
                    matches = []
                    if self.is_regex:
                        try:
                            pattern = re.compile(self.search_text, re.IGNORECASE)
                            matches = [(m.start(), m.group()) for m in pattern.finditer(plain_text, start)]
                        except re.error:
                            pass
                    else:
                        idx = plain_text.lower().find(self.search_text.lower(), start)
                        if idx != -1:
                            matches = [(idx, plain_text[idx:idx+len(self.search_text)])]
                    # Find the closest match after the stored position
                    closest_pos = None
                    closest_match = None
                    for pos, match in matches:
                        if pos >= position:
                            if closest_pos is None or pos < closest_pos:
                                closest_pos = pos
                                closest_match = match
                    if closest_pos is not None:
                        position = closest_pos
                        match_length = len(closest_match)
                        is_replaced = self.results_tree.itemWidget(item, 0).findChild(UndoButton) is not None
                        # Update context in widget
                        context = self.get_single_line_context(plain_text, closest_pos, len(closest_match))
                        match_widget = MatchItemWidget(context, item, self.tint_color, show_undo=is_replaced)
                        self.results_tree.setItemWidget(item, 0, match_widget)
                        if is_replaced:
                            match_widget.undo_button.clicked_with_item.connect(self.undo_replacement)
                        item.setData(0, Qt.ItemDataRole.UserRole, {
                            "hierarchy": hierarchy,
                            "position": closest_pos,
                            "match_text": closest_match,
                            "original_match_text": item.data(0, Qt.ItemDataRole.UserRole).get("original_match_text", closest_match)
                        })
                    else:
                        # No match found, use stored position with zero-length highlight
                        match_length = 0
                        self.controller.statusBar().showMessage(_("Match not found; content may have changed"), 5000)

                cursor = editor.textCursor()
                cursor.setPosition(position)
                # Apply highlight using ExtraSelection
                if match_length > 0:
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(cursor)
                    selection.cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, match_length)
                    selection.format.setBackground(QColor("yellow"))
                    self.extra_selections.append(selection)
                    editor.setExtraSelections(self.extra_selections)
                editor.setTextCursor(cursor)
                editor.ensureCursorVisible()
                # Update current_match to reflect the clicked item
                for i, (scene_item, match_item) in enumerate(self.matches):
                    if match_item == item:
                        self.current_match = (scene_item, match_item)
                        break
            finally:
                self._programmatic_change = False

    def update_tint(self, tint_color):
        """Update icon tints and parent row backgrounds when theme changes."""
        self.tint_color = tint_color
        self.menu_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/more-vertical.svg", tint_color))
        self.prev_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-up.svg", tint_color))
        self.next_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/chevron-down.svg", tint_color))
        self.replace_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/edit.svg", tint_color))
        self.replace_all_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/repeat.svg", tint_color))
        # Get theme-appropriate background color for parent rows
        parent_bg_color = ThemeManager.get_category_background_color()
        # Update existing match item widgets and parent row backgrounds
        for i in range(self.results_tree.topLevelItemCount()):
            act_item = self.results_tree.topLevelItem(i)
            act_item.setBackground(0, QBrush(parent_bg_color))
            act_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
            for j in range(act_item.childCount()):
                chapter_item = act_item.child(j)
                chapter_item.setBackground(0, QBrush(parent_bg_color))
                chapter_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
                for k in range(chapter_item.childCount()):
                    scene_item = chapter_item.child(k)
                    scene_item.setBackground(0, QBrush(parent_bg_color))
                    scene_item.setData(0, Qt.ItemDataRole.UserRole + 1, "true")  # Mark as category
                    for m in range(scene_item.childCount()):
                        match_item = scene_item.child(m)
                        current_widget = self.results_tree.itemWidget(match_item, 0)
                        if current_widget:
                            is_replaced = current_widget.findChild(UndoButton) is not None
                            context = current_widget.context_label.text()
                            new_widget = MatchItemWidget(context, match_item, tint_color, show_undo=is_replaced)
                            self.results_tree.setItemWidget(match_item, 0, new_widget)
                            if is_replaced:
                                new_widget.undo_button.clicked_with_item.connect(self.undo_replacement)
