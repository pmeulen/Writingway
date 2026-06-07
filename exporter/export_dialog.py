# ruff: noqa: RUF001
import os
import platform
import textwrap
from dataclasses import dataclass
from gettext import gettext as _

import pymupdf
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from markdownify import MarkdownConverter
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exporter.export_settings_manager import ExportSettingsManager
from exporter.heading_formatter import HeadingFormat, HeadingFormatter
from exporter.heading_style_editor import HeadingStyleEditor
from project_window.tree_manager import load_structure
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager


class ExportDialog(QDialog):
    """
    Reusable modal dialog for exporting projects with persistent settings.
    """
    exportCompleted = pyqtSignal(str)

    def __init__(self, parent=None, project_name: str = "", project_model=None, cover_path: str | None = None):
        super().__init__(parent)
        self.project_name = project_name or "Untitled"
        self.project_model = project_model
        self.project_structure = load_structure(self.project_name)
        self.acts = self.project_structure.get("acts", [])
        self.current_cover_path = cover_path
        self.settings_manager = ExportSettingsManager(project_name)

        self.setWindowTitle(_("Export Project"))
        self.resize(920, 800)
        self.setModal(True)

        self.setup_ui()
        self.load_settings()
        self.apply_theme()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.tabs, stretch=1)

        self.setup_metadata_tab()
        self.setup_content_tab()
        self.setup_advanced_tab()

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)

        # Output Options - Two rows
        output_form = QFormLayout()
        output_form.setLabelAlignment(Qt.AlignRight)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["EPUB", "HTML", "Markdown", "PDF", "Text"])
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        output_form.addRow(_("Output Format:"), self.format_combo)

        output_file_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        browse_btn = QPushButton(_("Browse..."))
        browse_btn.clicked.connect(self.browse_output)
        output_file_layout.addWidget(self.output_path_edit)
        output_file_layout.addWidget(browse_btn)
        output_form.addRow(_("Output File:"), output_file_layout)
        output_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        main_layout.addLayout(output_form)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self.export_btn = QPushButton(_("Export"))
        self.cancel_btn = QPushButton(_("Cancel"))
        self.export_btn.clicked.connect(self.perform_export)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.export_btn)
        main_layout.addLayout(btn_layout)

    def setup_metadata_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.title_edit = QLineEdit()
        form.addRow(_("Book Title:"), self.title_edit)

        self.author_edit = QLineEdit()
        form.addRow(_("Author:"), self.author_edit)

        cover_group = QGroupBox()
        cover_v = QVBoxLayout(cover_group)
        cover_v.setSpacing(8)
        self.cover_label = QLabel()
        self.cover_label.setMinimumSize(200, 260)
        self.cover_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid #ccc; background: #f8f8f8;")
        self.update_cover_display()

        cover_btns = QHBoxLayout()
        self.change_cover_btn = QPushButton(_("Change Cover"))
        self.remove_cover_btn = QPushButton(_("Remove Cover"))
        self.change_cover_btn.clicked.connect(self.change_cover)
        self.remove_cover_btn.clicked.connect(self.remove_cover)
        cover_btns.addWidget(self.change_cover_btn)
        cover_btns.addWidget(self.remove_cover_btn)

        cover_v.addWidget(self.cover_label, stretch=1)
        cover_v.addLayout(cover_btns)
        form.addWidget(cover_group)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        layout.addLayout(form)
        self.tabs.addTab(tab, _("Metadata"))

    def setup_content_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        self.heading_preview = QTextEdit()
        self.heading_preview.setReadOnly(True)
        self.heading_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.heading_preview.setMinimumHeight(200)
        layout.addWidget(self.heading_preview, stretch=1)

        self.level_tabs = QTabWidget()
        layout.addWidget(self.level_tabs)

        self.setup_act_tab()
        self.setup_chapter_tab()
        self.setup_scene_tab()
        self.setup_story_tab()

        layout.addStretch()
        self.tabs.addTab(tab, _("Content"))

    def setup_act_tab(self):
        self.use_acts_cb = QCheckBox(_("Use Act Headings"))
        self.use_acts_cb.setChecked(True)
        self.use_acts_cb.stateChanged.connect(self.on_use_changed)

        self.act_editor = HeadingStyleEditor(None, "Act", default_font="Georgia", default_size=24)
        self.act_editor.previewUpdated.connect(self.update_heading_preview)
        self._build_level_tab(self.use_acts_cb, self.act_editor, _("Acts"))

    def setup_chapter_tab(self):
        self.use_chapters_cb = QCheckBox(_("Use Chapter Headings"))
        self.use_chapters_cb.setChecked(True)
        self.use_chapters_cb.stateChanged.connect(self.on_use_changed)

        self.chapter_editor = HeadingStyleEditor(None, "Chapter", default_font="Georgia", default_size=18)
        self.chapter_editor.previewUpdated.connect(self.update_heading_preview)
        self._build_level_tab(self.use_chapters_cb, self.chapter_editor, _("Chapters"))

    def setup_scene_tab(self):
        self.use_scenes_cb = QCheckBox(_("Use Scene Headings"))
        self.use_scenes_cb.setChecked(True)
        self.use_scenes_cb.stateChanged.connect(self.on_use_changed)

        self.scene_editor = HeadingStyleEditor(None, "Scene", default_font="Georgia", default_size=14)
        self.scene_editor.previewUpdated.connect(self.update_heading_preview)
        self._build_level_tab(self.use_scenes_cb, self.scene_editor, _("Scenes"))


    def _build_level_tab(self, checkbox: QCheckBox, editor: HeadingStyleEditor, tab_name: str):
        container = QWidget()
        vlay = QVBoxLayout(container)
        vlay.setSpacing(8)
        vlay.addWidget(checkbox)
        vlay.addWidget(editor)
        self.level_tabs.addTab(container, tab_name)

    def setup_story_tab(self):
        """Tab for paragraph styling and export range."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)

        # 1. Paragraph Styling Group
        style_group = QGroupBox(_("Paragraph Styling"))
        style_form = QFormLayout(style_group)
        font_row_layout = QHBoxLayout()

        self.body_font_combo = QComboBox()
        # Populate with common serif/sans fonts and system fonts
        standard_fonts = ["Georgia", "Times New Roman", "Arial", "Verdana", "Courier New"]
        system_fonts = QFontDatabase().families()
        self.body_font_combo.addItems(standard_fonts)
        self.body_font_combo.insertSeparator(len(standard_fonts))
        self.body_font_combo.addItems(system_fonts)
        self.body_font_combo.currentTextChanged.connect(self.update_heading_preview)


        self.body_size_combo = QComboBox()
        self.body_size_combo.addItems([str(i) for i in range(8, 26)])
        self.body_size_combo.setCurrentText("12")
        self.body_size_combo.currentTextChanged.connect(self.update_heading_preview)

        self.font_info_button = QPushButton()
        self.font_info_button.setFixedSize(24, 24)
        self.font_info_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/info.svg"))
        self.font_info_button.setToolTip(_("Font Exceptions"))
        self.font_info_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.font_info_button.clicked.connect(self.show_font_exceptions)

        font_row_layout.addWidget(self.body_font_combo, 1) # '1' makes the combo stretch
        font_row_layout.addWidget(self.font_info_button)

        style_form.addRow(_("Font Family:"), font_row_layout)
        style_form.addRow(_("Font Size (pt):"), self.body_size_combo)
        self.body_size_combo.setMinimumWidth(70)
        layout.addWidget(style_group)

        # 2. Export Range Group
        range_group = QGroupBox(_("Export Range"))
        range_layout = QVBoxLayout(range_group)

        # Start Row
        start_lay = QHBoxLayout()
        self.start_act_combo = QComboBox()
        self.start_ch_combo = QComboBox()
        start_lay.addWidget(QLabel(_("Start:")))
        start_lay.addWidget(QLabel(_("Act")))
        start_lay.addWidget(self.start_act_combo, 1)
        start_lay.addWidget(QLabel(_("Chapter")))
        start_lay.addWidget(self.start_ch_combo, 1)
        range_layout.addLayout(start_lay)

        # End Row
        end_lay = QHBoxLayout()
        self.end_act_combo = QComboBox()
        self.end_ch_combo = QComboBox()
        end_lay.addWidget(QLabel(_("End:  ")))
        end_lay.addWidget(QLabel(_("Act")))
        end_lay.addWidget(self.end_act_combo, 1)
        end_lay.addWidget(QLabel(_("Chapter")))
        end_lay.addWidget(self.end_ch_combo, 1)
        range_layout.addLayout(end_lay)

        layout.addWidget(range_group)
        layout.addStretch()

        # Populate Range Combos
        act_names = [a.get("name", _("Untitled Act")) for a in self.acts]
        self.start_act_combo.addItems(act_names)
        self.end_act_combo.addItems(act_names)

        # Connect signals
        self.start_act_combo.currentIndexChanged.connect(
            lambda idx: self._update_chapter_list(idx, self.start_ch_combo)
        )
        self.end_act_combo.currentIndexChanged.connect(
            lambda idx: self._update_chapter_list(idx, self.end_ch_combo)
        )

        # Initial populations
        if self.acts:
            self._update_chapter_list(0, self.start_ch_combo)
            self.end_act_combo.setCurrentIndex(len(self.acts) - 1)
            self._update_chapter_list(len(self.acts) - 1, self.end_ch_combo)
            self.end_ch_combo.setCurrentIndex(self.end_ch_combo.count() - 1)

        self.level_tabs.addTab(tab, _("Story"))

    def _update_chapter_list(self, act_idx: int, chapter_combo: QComboBox):
        """Populates the chapter combo based on the selected act index."""
        chapter_combo.clear()
        if 0 <= act_idx < len(self.acts):
            chapters = self.acts[act_idx].get("chapters", [])
            ch_names = [c.get("name", _("Untitled Chapter")) for c in chapters]
            chapter_combo.addItems(ch_names)

    def on_use_changed(self):
        # Enable/disable editors
        self.act_editor.setEnabled(self.use_acts_cb.isChecked())
        self.chapter_editor.setEnabled(self.use_chapters_cb.isChecked())
        self.scene_editor.setEnabled(self.use_scenes_cb.isChecked())
        self.update_heading_preview()

    def setup_advanced_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 30, 20, 20)  # Top margin for breathing room

        checkbox_layout = QVBoxLayout()
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox_layout.setSpacing(12)

        self.include_prompts_cb = QCheckBox(_("Include Action Beats (AI Prompts)"))
        self.include_summaries_cb = QCheckBox(_("Include Summaries"))
        self.clean_quotes_cb = QCheckBox(_('Convert curly quotes (“”, ‘’) to straight quotes (", \')'))
        self.chapter_page_break_cb = QCheckBox(_("Start Chapters on New Page (E-book/HTML only)"))
        self.include_toc_cb = QCheckBox(_("Generate Table of Contents (E-book/HTML/PDF only)"))
        self.ignore_acts_numbering_cb = QCheckBox(_("Ignore Acts when Numbering Chapters (Global Numbering)"))

        checkbox_layout.addWidget(self.include_prompts_cb)
        checkbox_layout.addWidget(self.include_summaries_cb)
        checkbox_layout.addWidget(self.clean_quotes_cb)
        checkbox_layout.addWidget(self.chapter_page_break_cb)
        checkbox_layout.addWidget(self.include_toc_cb)
        checkbox_layout.addWidget(self.ignore_acts_numbering_cb)

        layout.addLayout(checkbox_layout)
        layout.addStretch()
        layout.addWidget(QLabel(_("Additional metadata and options will be added here.")))
        self.tabs.addTab(tab, _("Advanced"))

    def update_heading_preview(self):
        use_acts = self.use_acts_cb.isChecked()
        use_chapters = self.use_chapters_cb.isChecked()
        use_scenes = self.use_scenes_cb.isChecked()

        body_font = self.body_font_combo.currentText()
        body_size = self.body_size_combo.currentText()
        body_style = f"font-family: '{body_font}'; font-size: {body_size}pt; color: #333;"

        preview_html = '<div style="text-align:left; padding:12px; border-radius:6px; font-family: Georgia;">'

        if use_acts:
            act_sample = self.act_editor.get_formatted_sample(1, "Act One")
            preview_html += f'<div style="margin:25px 0 12px 0;">{act_sample}</div>'

        if use_chapters:
            ch1 = self.chapter_editor.get_formatted_sample(1, "Prologue")
            preview_html += f'<div style="margin:20px 0 8px 0;">{ch1}</div>'

        if use_scenes:
            sc1 = self.scene_editor.get_formatted_sample(1, "Introduction")
            preview_html += f'<div style="margin:15px 0 6px 0;">{sc1}</div>'

        preview_html += f'<p style="{body_style}">Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</p>'

        # Sample Chapter 2
        if use_chapters:
            ch2 = self.chapter_editor.get_formatted_sample(2, "The Beginning")
            preview_html += f'<div style="margin:20px 0 8px 0;">{ch2}</div>'

        if use_scenes:
            sc2 = self.scene_editor.get_formatted_sample(1, "Opening Scene")
            preview_html += f'<div style="margin:15px 0 6px 0;">{sc2}</div>'

        preview_html += f'<p style="{body_style}">Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</p>'
        preview_html += '</div>'

        self.heading_preview.setHtml(preview_html)

    def apply_theme(self):
        theme = WWSettingsManager.get_appearance_settings().get("theme", "Notion Light")
        self.setStyleSheet(ThemeManager.get_stylesheet(theme))

    def update_cover_display(self):
        if self.current_cover_path and os.path.exists(self.current_cover_path):
            pixmap = QPixmap(self.current_cover_path)
            label_size = self.cover_label.size()
            if label_size.width() < 50 or label_size.height() < 50:
                label_size = QSize(240, 340)  # fallback

            scaled = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)
        else:
            self.cover_label.setText(_("No Cover Selected"))
            self.cover_label.setPixmap(QPixmap())

    def resizeEvent(self, event) -> None: # type: ignore[override]
        """Re-scale cover image when dialog or tab resizes"""
        super().resizeEvent(event)
        if hasattr(self, 'cover_label') and self.current_cover_path:
            self.update_cover_display()

    def change_cover(self):
        file_path, _unused = QFileDialog.getOpenFileName(
            self, _("Select Book Cover"), "", _("Images (*.png *.jpg *.jpeg *.bmp)")
        )
        if file_path:
            self.current_cover_path = file_path
            self.update_cover_display()

    def remove_cover(self):
        self.current_cover_path = None
        self.update_cover_display()

    def browse_output(self):
        fmt = self.format_combo.currentText()
        ext_map = {"EPUB": ".epub", "HTML": ".html", "Markdown": ".md", "PDF": ".pdf", "Text": ".txt"}
        default_name = f"{self.title_edit.text() or self.project_name}{ext_map.get(fmt, '.epub')}"
        path, _unused = QFileDialog.getSaveFileName(self, _("Save As"), default_name,
                                              f"{fmt} (*{ext_map.get(fmt, '.epub')})")
        if path:
            self.output_path_edit.setText(path)

    def on_format_changed(self, fmt: str):
        current = self.output_path_edit.text()
        if current:
            base = os.path.splitext(current)[0]
            ext_map = {"EPUB": ".epub", "HTML": ".html", "Markdown": ".md", "PDF": ".pdf", "Text": ".txt"}
            self.output_path_edit.setText(base + ext_map.get(fmt, ".epub"))

    def get_default_documents_path(self) -> str:
        """Cross-platform Documents folder"""
        return os.path.expanduser("~/Documents")

    def show_font_exceptions(self):
        """Displays an information dialog about font overrides."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(_("Font Style Information"))
        msg.setText(_("Note on Paragraph Styling:"))
        msg.setInformativeText(
            _("The 'Story Font' selected here applies to the general body text. "
              "However, it may be overridden in two ways:\n\n"
              "1. Scene Edits: Specific formatting applied manually inside a scene (like bold or custom fonts) will be preserved.\n"
              "2. E-Readers: EPUB and PDF readers often allow users to override the book's font with their own system preferences.")
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def load_settings(self):
        data = self.settings_manager.load_settings()
        settings = data["settings"]

        self.title_edit.setText(settings.get("title") or self.project_name)
        self.author_edit.setText(settings.get("author", "Unknown Author"))
        self.format_combo.setCurrentText(settings.get("format", "EPUB"))
        self.include_prompts_cb.setChecked(settings.get("include_prompts", False))
        self.include_summaries_cb.setChecked(settings.get("include_summaries", False))
        self.clean_quotes_cb.setChecked(settings.get("clean_quotes", False))
        self.chapter_page_break_cb.setChecked(settings.get("chapter_page_break", False))
        self.include_toc_cb.setChecked(settings.get("include_toc", True))
        self.ignore_acts_numbering_cb.setChecked(settings.get("ignore_acts_numbering", False))
        self.use_acts_cb.setChecked(settings.get("use_acts", True))
        self.use_chapters_cb.setChecked(settings.get("use_chapters", True))
        self.use_scenes_cb.setChecked(settings.get("use_scenes", True))
        self.body_font_combo.setCurrentText(settings.get("body_font_family", "Georgia"))
        self.body_size_combo.setCurrentText(settings.get("body_font_size", "12"))


        # Load rich heading formats
        for level, editor in [("act", self.act_editor), ("chapter", self.chapter_editor), ("scene", self.scene_editor)]:
            fmt_data = settings.get(f"{level}_heading_format", {})
            if fmt_data:
                editor.set_rich_format(HeadingFormat.from_dict(fmt_data))
            else:
                # fallback
                editor.set_settings(
                    settings.get(f"{level}_heading_text", f"{level.capitalize()} {{num}}: {{title}}"),
                    settings.get(f"{level}_numbering_index", 0),
                    settings.get(f"{level}_template_index", 0)
                )

        last_path = settings.get("last_output_path")
        if last_path and os.path.exists(os.path.dirname(last_path)):
            self.output_path_edit.setText(last_path)
        else:
            docs = self.get_default_documents_path()
            default_path = os.path.join(docs, f"{self.project_name}.epub")
            self.output_path_edit.setText(default_path)

        s_act = settings.get("start_act_idx", 0)
        s_ch = settings.get("start_ch_idx", 0)
        e_act = settings.get("end_act_idx", -1) 
        e_ch = settings.get("end_ch_idx", -1)

        if 0 <= s_act < self.start_act_combo.count():
            self.start_act_combo.setCurrentIndex(s_act)
            if 0 <= s_ch < self.start_ch_combo.count():
                self.start_ch_combo.setCurrentIndex(s_ch)

        if e_act == -1:
            e_act = self.end_act_combo.count() - 1

        if 0 <= e_act < self.end_act_combo.count():
            self.end_act_combo.setCurrentIndex(e_act)
            # Re-update list before setting chapter
            self._update_chapter_list(e_act, self.end_ch_combo)
            if e_ch == -1:
                e_ch = self.end_ch_combo.count() - 1
            if 0 <= e_ch < self.end_ch_combo.count():
                self.end_ch_combo.setCurrentIndex(e_ch)
            else:
                self.end_ch_combo.setCurrentIndex(self.end_ch_combo.count() - 1)


    def save_current_settings(self):
        settings = {
            "title": self.title_edit.text().strip(),
            "author": self.author_edit.text().strip(),
            "format": self.format_combo.currentText(),
            "include_prompts": self.include_prompts_cb.isChecked(),
            "include_summaries": self.include_summaries_cb.isChecked(),
            "clean_quotes": self.clean_quotes_cb.isChecked(),
            "chapter_page_break": self.chapter_page_break_cb.isChecked(),
            "include_toc": self.include_toc_cb.isChecked(),
            "ignore_acts_numbering": self.ignore_acts_numbering_cb.isChecked(),
            "use_acts": self.use_acts_cb.isChecked(),
            "use_chapters": self.use_chapters_cb.isChecked(),
            "use_scenes": self.use_scenes_cb.isChecked(),
            "body_font_family": self.body_font_combo.currentText(),
            "body_font_size": self.body_size_combo.currentText(),
            "start_act_idx": self.start_act_combo.currentIndex(),
            "start_ch_idx": self.start_ch_combo.currentIndex(),
            "end_act_idx": self.end_act_combo.currentIndex(),
            "end_ch_idx": self.end_ch_combo.currentIndex(),
            "last_output_path": self.output_path_edit.text().strip()
        }

        # Save rich formats
        for level, editor in [("act", self.act_editor), ("chapter", self.chapter_editor), ("scene", self.scene_editor)]:
            fmt = editor.get_heading_format()
            settings[f"{level}_heading_format"] = fmt.to_dict()

        self.settings_manager.save_settings(settings)

    def perform_export(self):
        self.save_current_settings()
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, _("Export"), _("Please specify an output file."))
            return

        if os.path.exists(output_path):
            file_name = os.path.basename(output_path)
            reply = QMessageBox.question(
                self,
                _("Overwrite File?"),
                _("The file '{}' already exists. Do you want to replace it?").format(file_name),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        fmt = self.format_combo.currentText()
        title = self.title_edit.text().strip() or self.project_name
        author = self.author_edit.text().strip() or _("Unknown Author")

        try:
            if fmt == "EPUB":
                self.export_to_epub(output_path, title, author)
            elif fmt == "HTML":
                self.export_to_html(output_path, title, author)
            elif fmt == "Markdown":
                self.export_to_markdown(output_path, title, author)
            elif fmt == "PDF":
                self.export_to_pdf(output_path, title, author)
            elif fmt == "Text":
                self.export_to_text(output_path, title, author)

            QMessageBox.information(self, _("Success"), _("Exported successfully to:\n{}").format(output_path))
            self.exportCompleted.emit(output_path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, _("Export Failed"), str(e))

    def export_to_epub(self, path: str, title: str, author: str):
        try:
            from ebooklib import epub
            from ebooklib.epub import EpubHtml
            book = epub.EpubBook()
            book.set_identifier(f"id_{self.project_name.replace(' ', '_')}")
            book.set_title(title)
            book.set_language("en")
            book.add_author(author)

            if self.current_cover_path and os.path.exists(self.current_cover_path):
                with open(self.current_cover_path, "rb") as f:
                    data = f.read()
                book.set_cover("cover.jpg", data)

            full_text = self._get_full_project_text("epub")
            
            # Create TOC for EPUB sidebar
            epub_toc = []
            for entry in self.toc_entries:
                epub_toc.append(epub.Link("content.xhtml#"+entry["id"], entry["title"], entry["id"]))
            
            book.toc = tuple(epub_toc)
            
            # Simple single chapter for now; can be expanded to per-chapter
            c1 = EpubHtml(title=title, file_name="content.xhtml", lang="en")
            c1.content = f"""
            <?xml version="1.0" encoding="utf-8"?>
            <!DOCTYPE html>
            <html xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <title>{title}</title>
                <link rel="stylesheet" type="text/css" href="style/nav.css" />
            </head>
            <body>
                <h1>{title}</h1>
                <p>by {author}</p>
                {full_text}
            </body>
            </html>
            """
            book.add_item(c1)

            # book.toc = (epub.Link("content.xhtml", "Main Content", "content"),)
            book.spine = ['nav', c1]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(path, book)
        except ImportError:
            raise ImportError("Please pip install EbookLib")

    def export_to_html(self, path: str, title: str, author: str):
        """Full HTML export."""
        full_text = self._get_full_project_text("html")
        toc_html = ""
        if self.include_toc_cb.isChecked():
            toc_links = []
            for entry in self.toc_entries:
                margin = (entry['level'] - 1) * 20
                toc_links.append(f'<li style="margin-left: {margin}px; list-style: none;">'
                                f'<a href="#{entry["id"]}">{entry["title"]}</a></li>')
            toc_html = f"<nav><h2>Contents</h2><ul>{''.join(toc_links)}</ul></nav><hr/>"

        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Georgia, serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3 {{ color: #333; }}
        hr {{ border: 1px solid #ccc; margin: 30px 0; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p><em>by {author}</em></p>
    {toc_html}
    {full_text}
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)

    def export_to_markdown(self, path: str, title: str, author: str):
        """Full Markdown export."""
        full_text = self._get_full_project_text("markdown")

        md_content = f"""# {title}

By {author}

{full_text}
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_content)

    def export_to_pdf(self, path: str, title: str, author: str):
        doc = pymupdf.open()
        fm = FontManager()
        renderer = RichTextRenderer(doc, fm)

        body_font = self.body_font_combo.currentText()
        try:
            body_size = float(self.body_size_combo.currentText())
        except ValueError:
            body_size = 12.0

        full_content_html = self._get_full_project_text(format_type="html")
        header_html = f"""
            <h1 style="text-align: center;">{title}</h1>
            <p style="text-align: center; font-size: 16pt;">By {author}</p>
            <br/><br/>
            <hr/>
            <br/>
        """
        styled_html = header_html + full_content_html

        renderer.render_html_block(styled_html, body_font, body_size)
        if self.include_toc_cb.isChecked():
            doc.set_toc(renderer.pdf_toc)

        doc.save(path, garbage=3, deflate=True, clean=True)
        doc.close()

    def export_to_text(self, path: str, title: str, author: str):
        full_text = self._get_full_project_text(format_type="text")
        text = f"""{title}
by {author}

{full_text}
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _normalize_typography(self, text: str) -> str:
        """Normalize quotes and other problematic characters for PDF."""
        if not text:
            return ""

        # This mapping fixes common "unsupported glyph" issues in basic fonts
        # by converting specialized punctuation to standard ASCII punctuation.
        replacements = {
            '“': '"',   # left double
            '”': '"',   # right double
            '‘': "'",   # left single
            '’': "'",   # right single
            '—': '-',   # em dash
            '–': '-',   # en dash
            '…': '...', # ellipsis
            '\u00A0': ' ',  # non-breaking space
            '\u2028': ' ',  # line separator
            '\u2029': ' ',  # paragraph separator
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        return text

    def _get_full_project_text(self, format_type: str = "text") -> str:
        """Build complete project text with proper format conversion."""
        if not self.project_model:
            return self._fallback_content_extraction(format_type)

        include_summaries = self.include_summaries_cb.isChecked()
        use_acts = self.use_acts_cb.isChecked()
        use_chapters = self.use_chapters_cb.isChecked()
        use_scenes = self.use_scenes_cb.isChecked()

        start_a = self.start_act_combo.currentIndex() + 1
        start_c = self.start_ch_combo.currentIndex() + 1
        end_a = self.end_act_combo.currentIndex() + 1
        end_c = self.end_ch_combo.currentIndex() + 1
        # If the user puts end before start, assume they want one act and one chapter.
        end_a = max(start_a, end_a)
        if start_a == end_a:
            end_c = max(start_c, end_c)

        # Build Body CSS
        body_font = self.body_font_combo.currentText()
        body_size = self.body_size_combo.currentText()
        body_style = f"font-family: '{body_font}', serif; font-size: {body_size}pt; line-height: 1.6;"

        content_parts = []
        self.toc_entries = []
        global_ch_idx = 0
        ignore_acts = self.ignore_acts_numbering_cb.isChecked()

        for act_idx, act in enumerate(self.acts, 1):
            if act_idx < start_a or act_idx > end_a:
                continue

            if use_acts:
                heading_id = f"act_{act_idx}"
                heading = self._apply_heading_format(
                    act, act_idx, self.act_editor, format_type, heading_id
                )
                content_parts.append(heading)
                if not ignore_acts:
                    self.toc_entries.append({"level": 1, "title": act.get("name", "Act"), "id": heading_id})

            if include_summaries:
                hierarchy = [act.get("name")]
                summary = self.project_model.load_summary(hierarchy=hierarchy)
                if summary and not summary.startswith("This is the summary"):
                    content_parts.append(f"## Act Summary\n{summary}\n")

            for ch_idx, chapter in enumerate(act.get("chapters", []), 1):
                # Filter chapter range
                if act_idx == start_a and ch_idx < start_c: continue
                if act_idx == end_a and ch_idx > end_c: continue

                global_ch_idx += 1
                current_ch_num = global_ch_idx if ignore_acts else ch_idx

                if use_chapters:
                    heading_id = f"ch_{global_ch_idx}"
                    heading = self._apply_heading_format(
                        chapter, ch_idx, self.chapter_editor, format_type, heading_id
                    )
                    content_parts.append(heading)

                    toc_title = chapter.get("name", "Chapter")
                    if ignore_acts:
                        toc_title = HeadingFormatter.format_heading(
                            self.chapter_editor.get_heading_format().template,
                            toc_title, current_ch_num, 
                            self.chapter_editor.get_numbering_index()
                        )
                    
                    self.toc_entries.append({"level": 2, "title": toc_title, "id": heading_id})

                if include_summaries:
                    hierarchy = [act.get("name"), chapter.get("name")]
                    summary = self.project_model.load_summary(hierarchy=hierarchy)
                    if summary and not summary.startswith("This is the summary"):
                        content_parts.append(f"### Chapter Summary\n{summary}\n")

                for sc_idx, scene in enumerate(chapter.get("scenes", []), 1):
                    if use_scenes:
                        heading = self._apply_heading_format(
                            scene, sc_idx, self.scene_editor, format_type
                        )
                        content_parts.append(heading)

                    hierarchy = [act.get("name"), chapter.get("name"), scene.get("name")]
                    html_content = self.project_model.load_scene_content(hierarchy) or scene.get("content", "")
                    if not self.include_prompts_cb.isChecked():
                        html_content = self._remove_ai_prompts(html_content)

                    if format_type == "markdown":
                        scene_text = self._html_to_markdown(html_content)
                    elif format_type in ("text", "pdf"):
                        scene_text = self._wrap_text(self._html_to_plain_text(html_content))
                    else:  # html/epub
                        scene_text = self._html_to_fragment(html_content, body_font, body_size)
                        # Wrap in a div with the chosen paragraph style
                        # content_parts.append(f'<div style="{body_style}">{scene_text}</div>')

                    if self.clean_quotes_cb.isChecked():
                        scene_text = self._normalize_typography(scene_text)

                    content_parts.append(scene_text)

        return "\n\n".join(content_parts)

    def _apply_heading_format(self, item: dict, number: int, editor, format_type: str, anchor_id: str = "") -> str:
        """Apply full rich formatting + correct heading tag."""
        fmt = editor.get_heading_format()
        title = item.get("name", "Untitled")

        heading_text = HeadingFormatter.format_heading(
            fmt.template or f"{editor.level} {{num}}: {{title}}",
            title,
            number,
            fmt.numbering_index
        )

        if self.clean_quotes_cb.isChecked():
            heading_text = self._normalize_typography(heading_text)

        if format_type == "text":
            return heading_text

        # Determine heading level
        if editor.level == "Act":
            tag = "h1"
        elif editor.level == "Chapter":
            tag = "h2"
        else:  # Scene
            tag = "h3"

        if format_type in ("html", "epub"):
            style = self._build_css_style(fmt)
            id_attr = f' id="{anchor_id}"' if anchor_id else ""
            # Add specific logic for Chapter Page Breaks
            if editor.level == "Chapter" and self.chapter_page_break_cb.isChecked():
                # 1. page-break-before ensures a new page in EPUB/Print-ready HTML
                # 2. We use a 'spacer' div with a height.
                # 3. We use 'vh' (viewport height) or '%' instead of 'pt' for better "halfway" accuracy.
                # 4. The &nbsp; (non-breaking space) is crucial; Apple Books ignores empty divs.
                spacer_style = "height: 20vh; margin: 0; padding: 0; border: none; display: block;"
                spacer = f'<div style="{spacer_style}">&nbsp;</div>'
                return f'<div style="page-break-before: always;"{id_attr}>{spacer}<{tag} style="{style}">{heading_text}</{tag}></div>'

            return f'<{tag}{id_attr} style="{style}">{heading_text}</{tag}>'

        elif format_type == "markdown":
            prefix = "#" * (1 if tag == "h1" else 2 if tag == "h2" else 3)
            md_text = heading_text
            if fmt.bold:
                md_text = f"**{md_text}**"
            if fmt.italic:
                md_text = f"*{md_text}*"
            return f"{prefix} {md_text}"

        elif format_type == "pdf":
            # For PDF we return tagged text so the PDF renderer can parse it
            return f"<{tag}>{heading_text}</{tag}>"

        return heading_text

    def _build_css_style(self, fmt: HeadingFormat) -> str:
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

    def _html_to_fragment(self, html_content: str, base_font: str, base_size: str) -> str:
        """Extract only the body content from Qt-generated rich HTML, removing full document wrapper."""
        if not html_content or not html_content.strip().startswith('<'):
            return html_content or ""

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract content from <body> if present
        if soup.body:
            body = soup.body
            # Remove Qt meta/style tags
            for tag in body.find_all(['style', 'meta']):
                tag.decompose()

            content = body
        else:
            content = soup


        default_families = ["arial", "helvetica neue", "verdana"]
        default_size = "12pt"
        p_style = f"font-family: '{base_font}'; font-size: {base_size}pt; line-height: 1.5;"


        # === Clean up Qt empty paragraphs ===
        for tag in content.find_all(True):
            if tag.name == 'p':
                style = tag.get('style', '')

                # Remove Qt empty paragraph spacers
                if '-qt-paragraph-type:empty' in style:
                    tag.decompose()          # Completely remove these empty spacers
                    continue
                # tag.attrs.pop('style', None)
                tag['style'] = p_style


            if tag.name == 'span':
                style_str = tag.get('style', '')
                if not style_str:
                    continue

                # Parse the inline style string into a dictionary
                styles = {}
                for part in style_str.split(';'):
                    if ':' in part:
                        k, v = part.split(':', 1)
                        styles[k.strip().lower()] = v.strip().lower()

                new_styles = []

                # Check Font Family:
                # Keep it ONLY if it's NOT one of the common defaults (meaning a user override)
                family_val = styles.get('font-family', '')
                if family_val:
                    # 1. Split by comma, 2. Strip quotes and whitespace from each item
                    fonts = [f.strip().strip("'").strip('"').lower() for f in family_val.split(',')]

                    # 3. Check the primary (first) font in the list
                    primary_font = fonts[0] if fonts else ""

                    # If the primary font is NOT a standard default, it's a user choice (like 'arial black')
                    if primary_font and primary_font not in default_families:
                        orig_family = styles['font-family']
                        # Ensure font name is quoted if it has spaces
                        if ' ' in orig_family and not (orig_family.startswith("'") or orig_family.startswith('"')):
                            orig_family = f"'{orig_family}'"
                        new_styles.append(f"font-family: {orig_family}")

                # Check Font Size:
                # Keep it ONLY if it differs from the default 12pt
                size = styles.get('font-size', '')
                if size and size != default_size:
                    new_styles.append(f"font-size: {styles['font-size']}")

                # Always keep these "Highlights"
                for key in ['font-style', 'font-weight', 'text-decoration', 'color', 'background-color']:
                    if key in styles:
                        new_styles.append(f"{key}: {styles[key]}")

                if new_styles:
                    tag['style'] = "; ".join(new_styles)
                else:
                    # If the span now has no meaningful styles, remove the tag but keep the text
                    tag.unwrap()


        # Return cleaned inner HTML
        return ''.join(str(child) for child in content.children).strip()

    def _remove_ai_prompts(self, html_content: str) -> str:
        """Removes markers and all content between them using a flat index approach."""
        if not html_content or "__________" not in html_content:
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Get a flat list of all paragraph tags in the document
        all_ps = soup.find_all('p')

        # 2. Identify the indices of paragraphs that contain the separator text
        marker_indices = [i for i, p in enumerate(all_ps) if "__________" in p.get_text()]

        # 3. Process markers in pairs, working backwards through the list
        # We work backwards so that deleting elements doesn't mess up the indices of
        # the markers we haven't processed yet.
        # len(marker_indices) // 2 * 2 ensures we only iterate over complete pairs
        for j in range(len(marker_indices) // 2 * 2 - 2, -1, -2):
            start_idx = marker_indices[j]
            end_idx = marker_indices[j+1]

            # Remove every paragraph from the start marker to the end marker (inclusive)
            # Working backwards here too (end_idx down to start_idx)
            for k in range(end_idx, start_idx - 1, -1):
                all_ps[k].decompose()

        # 4. Cleanup: If there's a dangling marker (odd number of separators),
        # remove it as well to ensure the '______' doesn't appear in the final text.
        remaining_markers = [p for p in soup.find_all('p') if "__________" in p.get_text()]
        for p in remaining_markers:
            p.decompose()

        return str(soup)

    def _fallback_content_extraction(self, format_type: str) -> str:
        """Fallback when ProjectModel is not available - with proper numbering."""
        content_parts = []

        use_acts = self.use_acts_cb.isChecked()
        use_chapters = self.use_chapters_cb.isChecked()
        use_scenes = self.use_scenes_cb.isChecked()

        for act_idx, act in enumerate(self.acts, 1):
            if use_acts:
                heading = self._apply_heading_format(
                    act, act_idx, self.act_editor, format_type
                )
                content_parts.append(heading)

            # Need Act summaries here and for chapters below

            for ch_idx, chapter in enumerate(act.get("chapters", []), 1):
                if use_chapters:
                    heading = self._apply_heading_format(
                        chapter, ch_idx, self.chapter_editor, format_type
                    )
                    content_parts.append(heading)

                for sc_idx, scene in enumerate(chapter.get("scenes", []), 1):
                    if use_scenes:
                        heading = self._apply_heading_format(
                            scene, sc_idx, self.scene_editor, format_type
                        )
                        content_parts.append(heading)

                    content = scene.get("content", "")
                    content_parts.append(content)

        return "\n\n".join(content_parts)

    def _html_to_plain_text(self, html_content: str) -> str:
        """Convert HTML scene content to clean plain text."""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove script/style tags
        for tag in soup(["script", "style"]):
            tag.decompose()

        # Convert semantic tags to paragraph breaks
        for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote']):
            if tag.get_text(strip=True):
                tag.insert_after(soup.new_string('\n\nPARAGRAPH_BREAK\n\n'))

        # Handle double <br/> as paragraph break
        for br in soup.find_all('br'):
            next_sib = br.find_next_sibling()
            if next_sib and next_sib.name == 'br':
                br.replace_with('\n\nPARAGRAPH_BREAK\n\n')
            else:
                br.replace_with('\n')

        # Get the full text
        text = soup.get_text(separator="\n")

        # Process paragraph breaks
        paragraphs = []
        current_para = []

        for line in text.split('\n'):
            line = line.strip()
            if line == "PARAGRAPH_BREAK":
                if current_para:
                    paragraphs.append(" ".join(current_para))
                    current_para = []
            elif line:
                current_para.append(line)
            elif current_para and line == "":  # Empty line also ends paragraph
                paragraphs.append(" ".join(current_para))
                current_para = []

        if current_para:
            paragraphs.append(" ".join(current_para))

        if not paragraphs:
            text = soup.get_text(separator="\n\n", strip=True)
            paragraphs = [line.strip() for line in text.split('\n') if line.strip()]
        return "\n\n".join(paragraphs)

    def _wrap_text(self, text: str, width: int = 75) -> str:
        """Wrap text at word boundaries with 75 char width and blank lines between paragraphs."""
        if not text:
            return ""

        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        wrapped_paragraphs = []

        for para in paragraphs:
            # Wrap each paragraph
            wrapped = textwrap.fill(para, width=width, break_long_words=False, replace_whitespace=True, drop_whitespace=True)
            #wrapped = textwrap.fill(para, width=width, break_long_words=False, replace_whitespace=False)
            wrapped_paragraphs.append(wrapped)

        # Join paragraphs with blank line between them
        return "\n\n".join(wrapped_paragraphs)

    def _html_to_markdown(self, html_content: str) -> str:
        """Simple HTML to Markdown conversion."""
        if not html_content:
            return ""

        # Convert HTML to Markdown
        markdown_text = MDConverter(
            heading_style="ATX",           # Use # ## ### style (better for export)
            bullets="-",                   # Consistent bullet style
            escape_asterisks=False,
            escape_underscores=False
        ).convert(html_content)

        # Clean up excessive whitespace
        lines = [line.rstrip() for line in markdown_text.splitlines()]
        # Remove multiple blank lines
        cleaned = []
        for line in lines:
            if line.strip() or (cleaned and cleaned[-1].strip()):
                cleaned.append(line)

        return '\n'.join(cleaned).strip()

# PDF specific functions

@dataclass
class TextStyle:
    """Carries styling state through the HTML tree."""
    font_family: str
    font_size: float
    bold: bool = False
    italic: bool = False
    color: tuple[float, float, float] = (0, 0, 0)

class FontManager:
    """Resolves and caches PyMuPDF Font objects."""
    def __init__(self):
        self._font_cache: dict[str, pymupdf.Font] = {} # Stores Font objects for width calc
        self._faux_italic_flags: dict[str, bool] = {}
        self._system_fonts_cache: list[str] = []  # Cache of all full paths to font files

    def get_font(self, family: str, bold: bool = False, italic: bool = False) -> tuple[pymupdf.Font, bool]:
        """Returns a Font object and a unique reference name for it."""
        key = f"{family.lower()}_{'b' if bold else ''}{'i' if italic else ''}"
        if key in self._font_cache:
            return self._font_cache[key], self._faux_italic_flags.get(key, False)

        is_faux_italic = False
        font_obj = None
        path = self._resolve_path(family, bold, italic)

        if not path and italic:
            path = self._resolve_path(family, bold, False)
            if path:
                is_faux_italic = True

        if not path and bold:
            path = self._resolve_path(family, False, False)

        try:
            font_obj = pymupdf.Font(fontfile=path) if path else pymupdf.Font("helv")
        except Exception:
            font_obj = pymupdf.Font("helv")

        self._font_cache[key] = font_obj
        self._faux_italic_flags[key] = is_faux_italic
        return font_obj, is_faux_italic

    def _ensure_font_cache(self):
        """Builds a list of all available system font paths once."""
        if self._system_fonts_cache:
            return

        sys_name = platform.system()
        search_paths = []
        if sys_name == "Darwin":
            search_paths = [
                "/System/Library/Fonts/Supplemental",
                "/System/Library/Fonts",
                "/Library/Fonts",
                os.path.expanduser("~/Library/Fonts")
            ]
        elif sys_name == "Windows":
            search_paths = [os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')]
        else:
            search_paths = ["/usr/share/fonts", "/usr/local/share/fonts"]

        valid_exts = ('.ttf', '.otf', '.ttc', '.otc')

        for base in search_paths:
            if not os.path.exists(base):
                continue
            # os.walk is much more reliable for case-insensitive custom filtering
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.lower().endswith(valid_exts):
                        self._system_fonts_cache.append(os.path.join(root, f))

    def _resolve_path(self, family: str, bold: bool, italic: bool) -> str | None:
        """Discovery logic optimized for macOS Supplemental fonts and case-insensitivity."""
        self._ensure_font_cache()

        family_tokens = family.lower().split()

        # 2. Search our cached list of full paths
        # We look for a path where the FILENAME contains all necessary tokens
        for path in self._system_fonts_cache:
            filename = os.path.basename(path).lower()

            # Check if all family words (e.g. "arial", "black") are in the filename
            if not all(token in filename for token in family_tokens):
                continue

            remainder = filename
            for t in family_tokens:
                remainder = remainder.replace(t, "", 1)

            # Define markers. We use common patterns found in font filenames.
            # We check for markers like 'bold', 'bd', 'italic', 'oblique', 'it', etc.
            has_bold = any(s in remainder for s in ["bold", " -b", "_b", ".b", "bd"])
            has_italic = any(s in remainder for s in ["italic", "oblique", " -i", "_i", ".i", " -it", "_it"])

            # Logic: If we requested bold, the file MUST have a bold marker.
            # If we requested regular, the file MUST NOT have a bold/italic marker.
            if bold == has_bold and italic == has_italic:
                return path

        return None

class RichTextRenderer:
    """Handles HTML parsing and drawing text with word-wrapping."""
    def __init__(self, doc: pymupdf.Document, font_manager: FontManager):
        self.doc = doc
        self.fm = font_manager
        self.margin = 72
        self.page_width = 595  # A4
        self.page_height = 842
        self.y = self.margin
        self.current_page = None
        self._fonts_on_page = set() # OPTIMIZATION: track fonts per page
        self.pdf_toc = []

    def _new_page(self):
        self.current_page = self.doc.new_page()
        self._fonts_on_page = set() # Reset for new page
        self.y = self.margin
        self.x = self.margin
        return self.current_page

    def render_html_block(self, html: str, default_font: str, default_size: float):
        """Parses HTML into styled runs and draws them with wrapping."""
        if not self.current_page: self._new_page()
        soup = BeautifulSoup(html, "html.parser")
        self._process_node(soup, TextStyle(default_font, default_size))

    def _process_node(self, node, current_style: TextStyle):
        """Recursive tree walker to handle nested tags and block level spacing."""
        is_block = hasattr(node, 'name') and node.name in ['p', 'h1', 'h2', 'h3', 'div']

        new_style = self._derive_style(node, current_style)

        # 2. Handle Block Start (Paragraphs/Headings)
        if is_block:
            # If node has an ID or we know it's a heading
            level = 1 if node.name == 'h1' else 2 if node.name == 'h2' else 3
            if node.name in ['h1', 'h2', 'h3']:
                self.pdf_toc.append([level, node.get_text(), self.doc.page_count])

            # If we aren't already at the start of a line, move to the next one
            if self.x != self.margin:
                self._force_newline(new_style.font_size)
            # Add small paragraph-top padding
            self.y += new_style.font_size * 0.2

        # 3. Handle Content
        if isinstance(node, NavigableString):
            self._draw_text(str(node), new_style)
        elif hasattr(node, 'name') and node.name == 'br':
            self._force_newline(new_style.font_size)
        elif hasattr(node, 'children'):
            for child in node.children:
                self._process_node(child, new_style)

        # 4. Handle Block End
        if is_block:
            self._force_newline(new_style.font_size, extra_spacing=new_style.font_size * 0.5)

    def _derive_style(self, node, base: TextStyle) -> TextStyle:
        if isinstance(node, NavigableString):
            return base

        raw_style = node.get('style', '')
        norm_style = raw_style.lower().replace(" ", "")

        # Check tags and inline CSS
        is_bold = base.bold or node.name in ['b', 'strong', 'h1', 'h2', 'h3'] or "font-weight:bold" in norm_style
        is_italic = base.italic or node.name in ['i', 'em'] or "font-style:italic" in norm_style

        # Check font family override
        family = base.font_family
        lower_raw = raw_style.lower()
        if "font-family:" in lower_raw:
            try:
                # Find the position in the raw string using the lowercase locator
                start_marker = "font-family:"
                start_idx = lower_raw.find(start_marker) + len(start_marker)

                # Find the end of the declaration (either ; or end of string)
                end_idx = raw_style.find(";", start_idx)
                if end_idx == -1:
                    end_idx = len(raw_style)

                # Extract the actual value from the RAW string
                family_val = raw_style[start_idx:end_idx]

                # Handle font stacks (comma separated) and strip quotes/spaces
                # This preserves "Academy Engraved LET" exactly as it is
                family = family_val.split(",")[0].strip("'\" ")
            except Exception:
                pass

        # Check font size override
        size = base.font_size
        if node.name == 'h1': size = base.font_size * 2.0
        elif node.name == 'h2': size = base.font_size * 1.5
        elif node.name == 'h3': size = base.font_size * 1.2
        elif "font-size:" in norm_style:
            try:
                # Extract digits for pt/px
                val = "".join(c for c in norm_style.split("font-size:")[1].split(";")[0] if c.isdigit() or c == '.')
                size = float(val)
            except: pass

        return TextStyle(family, size, is_bold, is_italic, base.color)

    def _force_newline(self, font_size: float, extra_spacing: float = 0.0):
        """Moves cursor to the start of the next line, accounting for font height."""
        line_height = font_size * 1.4 # Standard typography leading
        self.x = self.margin
        self.y += line_height + extra_spacing

        # Check for page break after moving Y
        if self.y > self.page_height - self.margin:
            self._new_page()

    def _draw_text(self, text: str, style: TextStyle):
        if not text: return

        # Normalize newlines to spaces, but do NOT fully strip yet.
        # Stripping too early removes the space between "word <i>italic</i>"
        display_text = text.replace('\n', ' ')

        # If we are at the start of a line (x == margin), strip leading whitespace
        if self.x == self.margin:
            display_text = display_text.lstrip()

        if not display_text: return

        font_obj, is_faux = self.fm.get_font(style.font_family, style.bold, style.italic)
        font_id = font_obj.name.replace(" ", "-")

        if font_id not in self._fonts_on_page:
            self.current_page.insert_font(
                fontname=font_id, 
                fontbuffer=font_obj.buffer, 
                set_simple=False
            )
            self._fonts_on_page.add(font_id)

        words = display_text.split(" ")

        for i, word in enumerate(words):
            # Re-add the space we split on
            has_trailing_space = i < (len(words) - 1) or text.endswith(" ")
            word_to_draw = word + (" " if has_trailing_space else "")
            if not word_to_draw: continue
            w_len = font_obj.text_length(word_to_draw, fontsize=style.font_size)

            # Internal wrap (if word exceeds line width)
            if self.x + w_len > self.page_width - self.margin:
                # Use our new force_newline to move down correctly
                self._force_newline(style.font_size)
                if font_id not in self._fonts_on_page:
                    self.current_page.insert_font(fontname=font_id, fontbuffer=font_obj.buffer, set_simple=False)
                self._fonts_on_page.add(font_id)

                # Since we just wrapped, re-calculate without the leading space
                word_to_draw = word_to_draw.lstrip()
                w_len = font_obj.text_length(word_to_draw, fontsize=style.font_size)

            # --- FAUX ITALIC LOGIC ---
            insert_pos = pymupdf.Point(self.x, self.y + style.font_size)
            morph_data = None

            if is_faux:
                # Apply a skew matrix: Matrix(a, b, c, d, e, f)
                # c = 0.3 creates a ~15 degree slant
                skew_matrix = pymupdf.Matrix(1, 0, 0.3, 1, 0, 0)
                morph_data = (insert_pos, skew_matrix)

            # PyMuPDF insert_text uses the baseline. We adjust y so it doesn't collide with top.
            self.current_page.insert_text(
                insert_pos,
                word_to_draw,
                fontsize=style.font_size,
                fontname=font_id,
                morph=morph_data, # This applies the skew
            )
            self.x += w_len

# Markdown specific functions
class MDConverter(MarkdownConverter):
    def convert_span(self, el, text, convert_as_inline=True, **kwargs):
        # Check for italic or bold in the span's style attribute
        style = el.get("style", "").lower()

        if "font-style:italic" in style:
            return f"*{text}*"
        elif "font-weight:bold" in style:
            return f"**{text}**"

        # Fallback for unstyled or differently styled spans
        return text
    # Fool vulture so it thinks overriden functions are used
    _vulture_hooks = [convert_span]

def show_export_dialog(parent, project_name: str, project_model=None, cover_path=None):
    dialog = ExportDialog(parent, project_name, project_model, cover_path)
    dialog.exec_()
