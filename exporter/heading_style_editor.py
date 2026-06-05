from gettext import gettext as _

from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QFontComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from exporter.heading_formatter import HeadingFormat, HeadingFormatter
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager


class HeadingStyleEditor(QWidget):
    """
    Reusable widget for configuring heading styles for Acts, Chapters, or Scenes.
    """
    previewUpdated = pyqtSignal()

    def __init__(self, title, level: str = "Chapter", default_font: str = "Georgia", default_size: int = 14, parent=None):
        """
        level: "Act", "Chapter", or "Scene"
        """
        super().__init__(parent)
        self.level = level
        self.title = title
        self._default_font_name = default_font
        self._default_size = str(default_size)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Group box
        group = QGroupBox(self.title)
        group.setStyleSheet("font-weight: bold;")
        group_layout = QVBoxLayout(group)

        # Toolbar
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(22, 22))
        self.setup_toolbar()
        group_layout.addWidget(self.toolbar)

        # Editor
        self.editor = QTextEdit()
        self.editor.setMaximumHeight(60)
        self.editor.setMinimumHeight(30)
        self.editor.textChanged.connect(self._on_editor_changed)
        group_layout.addWidget(self.editor)

        # Numbering and Template
        controls_layout = QHBoxLayout()

        # Numbering Style
        numbering_label = QLabel(_("Numbering Style:"))
        self.numbering_combo = QComboBox()
        self.numbering_combo.addItems([
            "Number: 1, 2, 3...",
            "Roman: I, II, III...",
            "Kanji: 一, 二, 三..."
        ])
        self.numbering_combo.currentIndexChanged.connect(self._on_numbering_changed)
        controls_layout.addWidget(numbering_label)
        controls_layout.addWidget(self.numbering_combo, stretch=1)

        # Template
        template_label = QLabel(_("Template:"))
        self.template_combo = QComboBox()
        self.template_combo.setEditable(True)
        self.template_combo.setInsertPolicy(QComboBox.NoInsert)

        self._populate_templates()
        self.template_combo.activated.connect(self._on_template_changed)
        self.template_combo.lineEdit().setReadOnly(True)

        controls_layout.addWidget(template_label, stretch=0)
        controls_layout.addWidget(self.template_combo, stretch=2)

        group_layout.addLayout(controls_layout)
        layout.addWidget(group)

    def _populate_templates(self):
        """Populate appropriate templates based on level."""
        if self.level == "Act":
            self.template_combo.addItems([
                "Act {num}: {title}",
                "Part {num}: {title}",
                "{num}. {title}",
                "{num} - {title}",
                "第{num}幕 {title}",
                "{title}"
            ])
        elif self.level == "Chapter":
            self.template_combo.addItems([
                "Chapter {num}: {title}",
                "Part {num}: {title}",
                "{num}. {title}",
                "{num} - {title}",
                "第{num}章 {title}",
                "{title}"
            ])
        elif self.level == "Scene":
            self.template_combo.addItems([
                "Scene {num}: {title}",
                "{num}. {title}",
                "{num} - {title}",
                "Scene {title}",
                "第{num}場 {title}",
                "{title}"
            ])

    def setup_toolbar(self):
        tint = ThemeManager.ICON_TINTS.get(
            WWSettingsManager.get_appearance_settings().get("theme", "Notion Light"), "#333333"
        )

        # Bold
        self.bold_action = QAction(ThemeManager.get_tinted_icon("assets/icons/bold.svg", tint), _("Bold"), self)
        self.bold_action.setCheckable(True)
        self.bold_action.triggered.connect(self.toggle_bold)

        # Italic
        self.italic_action = QAction(ThemeManager.get_tinted_icon("assets/icons/italic.svg", tint), _("Italic"), self)
        self.italic_action.setCheckable(True)
        self.italic_action.triggered.connect(self.toggle_italic)

        # Underline (NEW)
        self.underline_action = QAction(ThemeManager.get_tinted_icon("assets/icons/underline.svg", tint), _("Underline"), self)
        self.underline_action.setCheckable(True)
        self.underline_action.triggered.connect(self.toggle_underline)

        # Color
        self.color_action = QAction(ThemeManager.get_tinted_icon("assets/icons/color.svg", tint), _("Text Color"), self)
        self.color_action.triggered.connect(self.choose_color)

        self.toolbar.addAction(self.bold_action)
        self.toolbar.addAction(self.italic_action)
        self.toolbar.addAction(self.underline_action)
        self.toolbar.addAction(self.color_action)
        self.toolbar.addSeparator()

        # Font family
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self._default_font_name))
        self.font_combo.currentFontChanged.connect(self.apply_font_family)
        self.toolbar.addWidget(self.font_combo)

        # Font size
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems([str(s) for s in [10, 12, 14, 16, 18, 20, 24, 28, 32]])
        self.font_size_combo.setCurrentText(self._default_size)
        self.font_size_combo.setMinimumWidth(70)
        self.font_size_combo.currentIndexChanged.connect(self.apply_font_size)
        self.toolbar.addWidget(self.font_size_combo)

    # ==================== FORMATTING METHODS ====================

    def toggle_bold(self):
        self._toggle_format("bold")

    def toggle_italic(self):
        self._toggle_format("italic")

    def toggle_underline(self):
        self._toggle_format("underline")

    def _toggle_format(self, fmt_type: str):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.LineUnderCursor)

        char_fmt = QTextCharFormat()
        current_fmt = cursor.charFormat()

        if fmt_type == "bold":
            is_bold = current_fmt.fontWeight() >= QFont.Bold
            char_fmt.setFontWeight(QFont.Normal if is_bold else QFont.Bold)
            self.bold_action.setChecked(not is_bold)

        elif fmt_type == "italic":
            is_italic = current_fmt.fontItalic()
            char_fmt.setFontItalic(not is_italic)
            self.italic_action.setChecked(not is_italic)

        elif fmt_type == "underline":
            is_underline = current_fmt.fontUnderline()
            char_fmt.setFontUnderline(not is_underline)
            self.underline_action.setChecked(not is_underline)

        cursor.mergeCharFormat(char_fmt)
        self.editor.setTextCursor(cursor)
        self.previewUpdated.emit()

    def choose_color(self):
        from PyQt5.QtWidgets import QColorDialog
        col = QColorDialog.getColor()
        if col.isValid():
            cursor = self.editor.textCursor()
            if not cursor.hasSelection():
                cursor.select(QTextCursor.LineUnderCursor)
            char_fmt = QTextCharFormat()
            char_fmt.setForeground(col)
            cursor.mergeCharFormat(char_fmt)
            self.editor.setTextCursor(cursor)
            self.previewUpdated.emit()

    def apply_font_family(self, font):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.LineUnderCursor)
        char_fmt = QTextCharFormat()
        char_fmt.setFontFamilies([font.family()])
        cursor.mergeCharFormat(char_fmt)
        self.editor.setTextCursor(cursor)
        self.previewUpdated.emit()

    def apply_font_size(self):
        size = int(self.font_size_combo.currentText())
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.LineUnderCursor)
        char_fmt = QTextCharFormat()
        char_fmt.setFontPointSize(size)
        cursor.mergeCharFormat(char_fmt)
        self.editor.setTextCursor(cursor)
        self.previewUpdated.emit()

    def _on_editor_changed(self):
        """Updates the combo box state to match the editor text."""
        text = self.editor.toPlainText()
        # Normalize to {num} to find a match in the preset list
        normalized = text.replace("{roman}", "{num}").replace("{kanji}", "{num}")
        
        idx = self.template_combo.findText(normalized)
        
        # We don't need blockSignals here if we use .activated for the combo,
        # but it's still good practice to prevent currentIndexChanged side-effects
        self.template_combo.blockSignals(True)
        if idx != -1:
            self.template_combo.setCurrentIndex(idx)
        else:
            self.template_combo.setCurrentText(_("Custom"))
        self.template_combo.blockSignals(False)

        self.previewUpdated.emit()

    def _on_numbering_changed(self, index: int):
        """Swaps placeholders in the editor based on numbering selection without losing user text."""
        placeholder_map = {0: "{num}", 1: "{roman}", 2: "{kanji}"}
        target = placeholder_map.get(index, "{num}")
        
        text = self.editor.toPlainText()
        # Replace any existing placeholder with the new one
        for p in ["{num}", "{roman}", "{kanji}"]:
            if p in text:
                text = text.replace(p, target)
        
        self.editor.setPlainText(text)
        self.previewUpdated.emit()

    def _on_template_changed(self, index: int):
        """Overwrites the editor with a preset, but respects the current numbering style."""
        template_text = self.template_combo.currentText()
        
        # Don't overwrite if the user selects "Custom" or if it's empty
        if template_text == _("Custom") or not template_text:
            return

        # Get current numbering placeholder
        placeholder_map = {0: "{num}", 1: "{roman}", 2: "{kanji}"}
        target = placeholder_map.get(self.numbering_combo.currentIndex(), "{num}")

        # Templates in the combo always use {num}, convert it to the active style
        new_text = template_text.replace("{num}", target)
        
        self.editor.setPlainText(new_text)
        self.previewUpdated.emit()

    def _update_heading_from_combos(self):
        numbering_idx = self.numbering_combo.currentIndex()
        template_text = self.template_combo.currentText().strip()

        if not template_text:
            default = {
                "Act": "Act {num}: {title}",
                "Chapter": "Chapter {num}: {title}",
                "Scene": "Scene {num}: {title}"
            }.get(self.level, "Chapter {num}: {title}")
            template_text = default

        if numbering_idx == 1:  # Roman
            heading = template_text.replace("{num}", "{roman}")
        elif numbering_idx == 2:  # Kanji
            heading = template_text.replace("{num}", "{kanji}")
        else:
            heading = template_text

        self.editor.setPlainText(heading)

    # Add these methods to HeadingStyleEditor class

    def get_heading_format(self) -> HeadingFormat:
        fmt = HeadingFormat()
        fmt.template = self.get_heading_text()
        fmt.bold = self.bold_action.isChecked()
        fmt.italic = self.italic_action.isChecked()
        fmt.underline = self.underline_action.isChecked()
        fmt.font_family = self.font_combo.currentFont().family()
        fmt.font_size = int(self.font_size_combo.currentText())
        fmt.numbering_index = self.get_numbering_index()

        # Extract color from current format
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.LineUnderCursor)
        cf = cursor.charFormat().foreground().color()
        if cf.isValid() and cf.name != "#000000":
            fmt.color = cf.name()

        return fmt

    def set_rich_format(self, heading_fmt: HeadingFormat):
        self.editor.setPlainText(heading_fmt.template)
        self.bold_action.setChecked(heading_fmt.bold)
        self.italic_action.setChecked(heading_fmt.italic)
        self.underline_action.setChecked(heading_fmt.underline)
        self.numbering_combo.setCurrentIndex(heading_fmt.numbering_index)
        self.font_combo.setCurrentFont(QFont(heading_fmt.font_family))
        self.font_size_combo.setCurrentText(str(heading_fmt.font_size))

        # In case the user entered {roman} or {kanji}, find the {num} template that matches
        lookup = heading_fmt.template.replace("{roman}", "{num}").replace("{kanji}", "{num}")
        idx = self.template_combo.findText(lookup)

        if idx != -1:
            self.template_combo.setCurrentIndex(idx)
        else:
            self.template_combo.setCurrentText(_("Custom"))

        if heading_fmt.color:
            # apply color
            cursor = self.editor.textCursor()
            cursor.select(QTextCursor.LineUnderCursor)
            char_fmt = QTextCharFormat()
            char_fmt.setForeground(QColor(heading_fmt.color))
            cursor.mergeCharFormat(char_fmt)
            self.editor.setTextCursor(cursor)
        self.previewUpdated.emit()

    def get_formatted_sample(self, number: int, title: str) -> str:
        """Return HTML-formatted sample for preview."""
        fmt = self.get_heading_format()
        text = HeadingFormatter.format_heading(
            fmt.template or f"{self.level} {{num}}: {{title}}",
            title,
            number,
            fmt.numbering_index
        )
        style = self._build_inline_style(fmt)
        return f'<span style="{style}">{text}</span>'

    def _build_inline_style(self, fmt: HeadingFormat) -> str:
        styles = []
        if fmt.font_family:
            styles.append(f"font-family: '{fmt.font_family}'")
        if fmt.font_size:
            styles.append(f"font-size: {fmt.font_size}pt")
        if fmt.bold:
            styles.append("font-weight: bold")
        if fmt.italic:
            styles.append("font-style: italic")
        if fmt.underline:
            styles.append("text-decoration: underline")
        if fmt.color:
            styles.append(f"color: {fmt.color}")
        return "; ".join(styles)

    # Getters/Setters
    def get_heading_text(self) -> str:
        return self.editor.toPlainText().strip()

    def get_numbering_index(self) -> int:
        return self.numbering_combo.currentIndex()

    def get_template_index(self) -> int:
        return self.template_combo.currentIndex()

    def set_settings(self, heading_text: str, numbering_index: int, template_index: int):
        self.numbering_combo.setCurrentIndex(numbering_index)

        if 0 <= template_index < self.template_combo.count():
            self.template_combo.setCurrentIndex(template_index)
        else:
            self.template_combo.setCurrentText(_("Custom"))

        if heading_text:
            self.editor.setPlainText(heading_text)
        else:
            self._update_heading_from_combos()
