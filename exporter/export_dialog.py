# ruff: noqa: RUF001, E701, E702
import os
import textwrap
from gettext import gettext as _

from bs4 import BeautifulSoup
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
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from project_window.tree_manager import load_structure
from settings.settings_manager import WWSettingsManager
from settings.theme_manager import ThemeManager

from .export_pdf import PDFWorker
from .export_settings_manager import ExportSettingsManager
from .heading_formatter import HeadingFormat, HeadingFormatter
from .heading_style_editor import HeadingStyleEditor


class ExportDialog(QDialog):
    """
    Refactored Export Dialog with threaded PDF generation and standardized numbering.
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
        self.toc_entries = []

        self.setWindowTitle(_("Export Project"))
        self.resize(920, 800)
        self.setModal(True)

        self._setup_ui()
        self._load_settings()
        self._apply_theme()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.tabs, stretch=1)

        self._setup_metadata_tab()
        self._setup_content_tab()
        self._setup_advanced_tab()

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)

        # Output Form
        output_form = QFormLayout()
        output_form.setLabelAlignment(Qt.AlignRight)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["EPUB", "HTML", "Markdown", "PDF", "Text"])
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        output_form.addRow(_("Output Format:"), self.format_combo)

        path_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        browse_btn = QPushButton(_("Browse..."))
        browse_btn.clicked.connect(self._browse_output)
        path_layout.addWidget(self.output_path_edit)
        path_layout.addWidget(browse_btn)
        output_form.addRow(_("Output File:"), path_layout)
        output_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        main_layout.addLayout(output_form)

        # Buttons
        btn_layout = QHBoxLayout()
        self.export_btn = QPushButton(_("Export"))
        self.cancel_btn = QPushButton(_("Cancel"))
        self.export_btn.clicked.connect(self._perform_export)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.export_btn)
        main_layout.addLayout(btn_layout)

    def _setup_metadata_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        form.addRow(_("Book Title:"), self.title_edit)
        form.addRow(_("Author:"), self.author_edit)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        cover_group = QGroupBox()
        cover_v = QVBoxLayout(cover_group)
        self.cover_label = QLabel(_("No Cover Selected"))
        self.cover_label.setMinimumSize(200, 260)
        self.cover_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")

        btn_h = QHBoxLayout()
        ch_btn = QPushButton(_("Change"))
        rm_btn = QPushButton(_("Remove"))
        ch_btn.clicked.connect(self._change_cover)
        rm_btn.clicked.connect(self._remove_cover)
        btn_h.addWidget(ch_btn)
        btn_h.addWidget(rm_btn)

        cover_v.addWidget(self.cover_label, stretch=1)
        cover_v.addLayout(btn_h)
        form.addRow(cover_group)
        self.tabs.addTab(tab, _("Metadata"))

    def _setup_content_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.heading_preview = QTextEdit()
        self.heading_preview.setReadOnly(True)
        self.heading_preview.setMinimumHeight(200)
        layout.addWidget(self.heading_preview, stretch=1)

        self.level_tabs = QTabWidget()
        layout.addWidget(self.level_tabs)

        self.act_editor = HeadingStyleEditor(None, "Act", "Georgia", 24)
        self.chapter_editor = HeadingStyleEditor(None, "Chapter", "Georgia", 18)
        self.scene_editor = HeadingStyleEditor(None, "Scene", "Georgia", 14)

        for editor in [self.act_editor, self.chapter_editor, self.scene_editor]:
            editor.previewUpdated.connect(self._update_heading_preview)

        self.use_acts_cb = QCheckBox(_("Use Act Headings"))
        self.use_chapters_cb = QCheckBox(_("Use Chapter Headings"))
        self.use_scenes_cb = QCheckBox(_("Use Scene Headings"))

        self._build_level_tab(self.use_acts_cb, self.act_editor, _("Acts"))
        self._build_level_tab(self.use_chapters_cb, self.chapter_editor, _("Chapters"))
        self._build_level_tab(self.use_scenes_cb, self.scene_editor, _("Scenes"))
        self._setup_story_tab()

        self.tabs.addTab(tab, _("Content"))

    def _build_level_tab(self, cb, ed, name):
        w = QWidget()
        v = QVBoxLayout(w)
        cb.setChecked(True)
        cb.stateChanged.connect(lambda: ed.setEnabled(cb.isChecked()))
        cb.stateChanged.connect(self._update_heading_preview)
        v.addWidget(cb)
        v.addWidget(ed)
        self.level_tabs.addTab(w, name)

    def _setup_story_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(20)

        # Font Styles
        group = QGroupBox(_("Paragraph Style"))
        form = QFormLayout(group)
        font_row_layout = QHBoxLayout()

        self.body_font_combo = QComboBox()
        self.body_font_combo.addItems(["Georgia", "Times New Roman", "Arial", "Verdana"])
        self.body_font_combo.addItems(QFontDatabase().families())
        self.body_size_combo = QComboBox()
        self.body_size_combo.addItems([str(i) for i in range(8, 30)])
        self.body_size_combo.setCurrentText("12")
        self.body_size_combo.setMinimumWidth(70)

        self.body_font_combo.currentTextChanged.connect(self._update_heading_preview)
        self.body_size_combo.currentTextChanged.connect(self._update_heading_preview)

        self.font_info_button = QPushButton()
        self.font_info_button.setFixedSize(24, 24)
        self.font_info_button.setIcon(ThemeManager.get_tinted_icon("assets/icons/info.svg"))
        self.font_info_button.setToolTip(_("Font Exceptions"))
        self.font_info_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.font_info_button.clicked.connect(self._show_font_exceptions)

        font_row_layout.addWidget(self.body_font_combo, 1) # '1' makes the combo stretch
        font_row_layout.addWidget(self.font_info_button)

        form.addRow(_("Font Family:"), font_row_layout)
        form.addRow(_("Font Size:"), self.body_size_combo)
        lay.addWidget(group)

        # Range
        r_group = QGroupBox(_("Export Range"))
        r_lay = QVBoxLayout(r_group)
        self.start_act_combo = QComboBox()
        self.start_ch_combo = QComboBox()
        self.end_act_combo = QComboBox()
        self.end_ch_combo = QComboBox()

        act_names = [a.get("name", "Act") for a in self.acts]
        self.start_act_combo.addItems(act_names)
        self.end_act_combo.addItems(act_names)

        self.start_act_combo.currentIndexChanged.connect(lambda i: self._update_chapter_list(i, self.start_ch_combo))
        self.end_act_combo.currentIndexChanged.connect(lambda i: self._update_chapter_list(i, self.end_ch_combo))

        row1 = QHBoxLayout(); row1.addWidget(QLabel(_("From:"))); row1.addWidget(self.start_act_combo); row1.addWidget(self.start_ch_combo)
        row2 = QHBoxLayout(); row2.addWidget(QLabel(_("To:  "))); row2.addWidget(self.end_act_combo); row2.addWidget(self.end_ch_combo)
        r_lay.addLayout(row1); r_lay.addLayout(row2)
        lay.addWidget(r_group)

        self.level_tabs.addTab(tab, _("Story"))
        if self.acts:
            self._update_chapter_list(0, self.start_ch_combo)
            self._update_chapter_list(0, self.end_ch_combo)
            self.end_act_combo.setCurrentIndex(len(self.acts) - 1)
            self.end_ch_combo.setCurrentIndex(self.end_ch_combo.count() - 1)

    def _setup_advanced_tab(self):
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

        for cb in [self.include_prompts_cb, self.include_summaries_cb, self.clean_quotes_cb,
                   self.chapter_page_break_cb, self.include_toc_cb, self.ignore_acts_numbering_cb]:
            checkbox_layout.addWidget(cb)

        layout.addLayout(checkbox_layout)
        layout.addStretch()
        self.tabs.addTab(tab, _("Advanced"))

    def _update_chapter_list(self, idx, combo):
        combo.clear()
        if 0 <= idx < len(self.acts):
            combo.addItems([c.get("name", "Chapter") for c in self.acts[idx].get("chapters", [])])

    def _update_heading_preview(self):
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

    def _apply_theme(self):
        theme = WWSettingsManager.get_appearance_settings().get("theme", "Notion Light")
        self.setStyleSheet(ThemeManager.get_stylesheet(theme))
        self._update_cover_display()

    def _update_cover_display(self):
        if self.current_cover_path and os.path.exists(self.current_cover_path):
            label_size = self.cover_label.size()
            if label_size.width() < 50 or label_size.height() < 50:
                label_size = QSize(240, 340)  # fallback
            pix = QPixmap(self.current_cover_path).scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(pix)
        else:
            self.cover_label.setText(_("No Cover"))

    def resizeEvent(self, event) -> None: # type: ignore[override]
        """Re-scale cover image when dialog or tab resizes"""
        super().resizeEvent(event)
        if hasattr(self, 'cover_label') and self.current_cover_path:
            self._update_cover_display()

    def _change_cover(self):
        p, _unused = QFileDialog.getOpenFileName(self, _("Select Cover"), "", "Images (*.png *.jpg)")
        if p:
            self.current_cover_path = p
            self._update_cover_display()

    def _remove_cover(self):
        self.current_cover_path = None
        self._update_cover_display()

    def _browse_output(self):
        fmt = self.format_combo.currentText()
        ext = {"EPUB":".epub", "HTML":".html", "Markdown":".md", "PDF":".pdf", "Text":".txt"}[fmt]
        p, _unused = QFileDialog.getSaveFileName(self, _("Save"), self.project_name + ext, f"{fmt} (*{ext})")
        if p: self.output_path_edit.setText(p)

    def _on_format_changed(self, fmt):
        curr = self.output_path_edit.text()
        if curr:
            ext = {"EPUB":".epub", "HTML":".html", "Markdown":".md", "PDF":".pdf", "Text":".txt"}[fmt]
            self.output_path_edit.setText(os.path.splitext(curr)[0] + ext)

    def _show_font_exceptions(self):
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

    def _load_settings(self):
        settings = self.settings_manager.load_settings().get("settings", {})
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

    def _save_settings(self):
        s = {
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
            s[f"{level}_heading_format"] = fmt.to_dict()

        self.settings_manager.save_settings(s)

    def _perform_export(self):
        self._save_settings()
        path = self.output_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, _("Export"), _("Please specify an output file."))
            return

        if os.path.exists(path):
            file_name = os.path.basename(path)
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
        title = self.title_edit.text() or self.project_name
        author = self.author_edit.text() or _("Unknown")

        try:
            if fmt == "PDF":
                self._export_to_pdf(path, title, author)
                return
            if fmt == "EPUB": self._export_to_epub(path, title, author)
            elif fmt == "HTML": self._export_to_html(path, title, author)
            elif fmt == "Markdown": self._export_to_markdown(path, title, author)
            elif fmt == "Text": self._export_to_text(path, title, author)

            QMessageBox.information(self, _("Success"), _("Exported successfully to:\n{}").format(path))
            self.exportCompleted.emit(path)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, _("Export Failed"), str(e))

    def _export_to_pdf(self, path, title, author):
        html = self._get_full_project_text("pdf")
        font = self.body_font_combo.currentText()
        size = float(self.body_size_combo.currentText())
        toc = self.include_toc_cb.isChecked()

        self.pd = QProgressDialog(_("Rendering PDF..."), _("Cancel"), 0, 100, None)

        self.worker = PDFWorker(path, html, title, author, font, size, toc)
        self.worker.progress.connect(self.pd.setValue)
        self.pd.canceled.connect(self._on_cancel)
        self.worker.finished.connect(self._on_pdf_finished)

        self.hide()
        self.worker.start()

    def _on_cancel(self):
        if self.worker.isRunning(): self.worker.request_cancel(); self.worker.wait()
        self.show()

    def _on_pdf_finished(self, success, msg):
        self.pd.close()
        if success:
            main_window = self.parentWidget()
            self.exportCompleted.emit(msg)
            self.accept()
            QMessageBox.information(main_window, _("Success"), _("Exported to: ") + msg)
        else:
            self.show()
            QMessageBox.critical(self, _("Failed"), msg)

    def _export_to_html(self, path, title, author):
        content = self._get_full_project_text("html")
        toc_html = ""
        if self.include_toc_cb.isChecked():
            items = [f"<li><a href='#{e['id']}'>{e['title']}</a></li>" for e in self.toc_entries]
            toc_html = f"<nav><h2>Contents</h2><ul>{''.join(items)}</ul></nav><hr/>"

        full = f"<html><head><meta charset='utf-8'><title>{title}</title>" \
               f"<style>body{{font-family:serif; max-width:800px; margin:40px auto; line-height:1.6;}}" \
               f"h1{{text-align:center;}} hr{{margin:40px 0;}}</style></head>" \
               f"<body><h1>{title}</h1><p>By: {author}</p>{toc_html}{content}</body></html>"

        with open(path, "w", encoding="utf-8") as f: f.write(full)

    def _export_to_markdown(self, path, title, author):
        text = self._get_full_project_text("markdown")
        md = f"# {title}\n\n**By {author}**\n\n{text}"
        with open(path, "w", encoding="utf-8") as f: f.write(md)

    def _export_to_text(self, path, title, author):
        text = self._get_full_project_text("text")
        wrapped = self._wrap_text(f"{title}\n\nBy {author}\n\n{text}")
        with open(path, "w", encoding="utf-8") as f: f.write(wrapped)

    def _export_to_epub(self, path, title, author):
        try:
            from ebooklib import epub
            book = epub.EpubBook()
            book.set_identifier(f"id_{self.project_name.replace(' ', '_')}")
            book.set_title(title)
            book.add_author(author)

            if self.current_cover_path and os.path.exists(self.current_cover_path):
                with open(self.current_cover_path, "rb") as f:
                    data = f.read()
                book.set_cover("cover.jpg", data)

            content = self._get_full_project_text("epub")

            epub_toc = []
            for entry in self.toc_entries:
                epub_toc.append(epub.Link("content.xhtml#"+entry["id"], entry["title"], entry["id"]))
            book.toc = tuple(epub_toc)

            c1 = epub.EpubHtml(title=title, file_name='content.xhtml', content=f"<h1>{title}</h1>{content}")
            book.add_item(c1)
            book.spine = ['nav', c1]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(path, book)
        except: raise ImportError("ebooklib required for EPUB") from None

    def _get_full_project_text(self, format_type):
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
                    elif format_type in ("text"):
                        scene_text = self._wrap_text(self._html_to_plain_text(html_content))
                    else:  # html/epub/pdf
                        scene_text = self._html_to_fragment(html_content, body_font, body_size)

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

        if format_type in ("html", "epub", "pdf"):
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

        p_style = f"font-family: '{base_font}'; font-size: {base_size}pt; line-height: 1.5;"

        # Helper to parse style strings into dicts
        def parse_styles(style_str):
            d = {}
            for part in style_str.lower().split(';'):
                if ':' in part:
                    k, v = part.split(':', 1)
                    d[k.strip()] = v.strip()
            return d

        # === Clean up Qt empty paragraphs ===
        for p in content.find_all('p'):
            style = p.get('style', '')

            # Remove Qt empty paragraph spacers
            if '-qt-paragraph-type:empty' in style:
                p.decompose()          # Completely remove these empty spacers
                continue
            p['style'] = p_style

            # Identify if the paragraph starts with a span and get its font overrides
            # We look for the first child that isn't just whitespace
            first_child = next((c for c in p.children if str(c).strip()), None)

            target_font = None
            target_size = None

            if first_child and first_child.name == 'span':
                first_styles = parse_styles(first_child.get('style', ''))
                target_font = first_styles.get('font-family')
                target_size = first_styles.get('font-size')

            # If we found target values to strip, process all spans in this paragraph
            if target_font or target_size:
                for span in p.find_all('span'):
                    s_styles = parse_styles(span.get('style', ''))

                    # Remove the property if it matches the "paragraph-wide" override
                    if target_font and s_styles.get('font-family') == target_font:
                        s_styles.pop('font-family')
                    if target_size and s_styles.get('font-size') == target_size:
                        s_styles.pop('font-size')

                    # Rebuild the style string
                    if s_styles:
                        new_style_str = "; ".join([f"{k}: {v}" for k, v in s_styles.items()])
                        span['style'] = new_style_str
                    else:
                        # If no styles left (e.g. it was just the font/size), unwrap it
                        span.unwrap()

            # Secondary cleanup for any remaining spans (e.g. ones that didn't match the first span
            # but still use default Arial/12pt that we want to strip)
            for span in p.find_all('span'):
                s_styles = parse_styles(span.get('style', ''))
                changed = False

                # Cleanup standard defaults that might have survived
                if s_styles.get('font-family') in ["arial", "helvetica neue", "verdana"]:
                    s_styles.pop('font-family')
                    changed = True
                if s_styles.get('font-size') == "12pt":
                    s_styles.pop('font-size')
                    changed = True

                if changed:
                    if s_styles:
                        span['style'] = "; ".join([f"{k}: {v}" for k, v in s_styles.items()])
                    else:
                        span.unwrap()

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

    def _normalize_typography(self, t):
        d = {'“':'"', '”':'"', '‘':"'", '’':"'", '—':'-', '–':'-', '…':'...'}
        for o, n in d.items(): t = t.replace(o, n)
        return t

    def _wrap_text(self, t, w=75):
        return "\n\n".join([textwrap.fill(p.strip(), width=w) for p in t.split('\n\n') if p.strip()])

    def get_default_documents_path(self) -> str:
        """Cross-platform Documents folder"""
        return os.path.expanduser("~/Documents")

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

def show_export_dialog(parent, name, model=None, cover_path=None):
    ExportDialog(parent, name, model, cover_path).exec_()
