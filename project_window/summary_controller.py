from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication
from .summary_service import SummaryService
from muse.prompt_preview_dialog import PromptPreviewDialog
from .progress_dialog import ProgressDialog
import time
from enum import Enum

class SummaryMode(Enum):
    """Enum for summary generation modes."""
    ACT_ONLY = "Write Act Summary Only"
    ACT_AND_CHAPTERS = "Write Act + Chapters as needed"
    IGNORE_EXISTING = "Ignore all existing summaries"

    def display_name(self):
        """Return the localized display name for the mode."""
        return _(self.value)

class ChapterSummary:
    """Encapsulates data and logic for a single chapter's summary process."""
    def __init__(self, hierarchy, scenes, existing_summary=None):
        self.hierarchy = hierarchy
        self.scenes = scenes
        self.existing_summary = existing_summary
        self.partial_summary = ""
        self.current_scene_index = 0

class ActSummary:
    """Encapsulates data and logic for an act's summary process."""
    def __init__(self, hierarchy, chapters):
        self.hierarchy = hierarchy
        self.chapters = chapters  # List of ChapterSummary objects
        self.combined_summary = ""

class SummaryController(QObject):
    progress_updated = pyqtSignal(str)
    RATE_LIMIT_DELAY = 1.0  # Seconds to wait between requests to avoid throttling

    def __init__(self, model, view, project_tree):
        super().__init__()
        self.model = model
        self.view = view
        self.project_tree = project_tree
        self.service = SummaryService()
        self.service.summary_generated.connect(self._partial_update)
        self.service.error_occurred.connect(self._show_error)
        self.service.finished.connect(self._on_service_finished)
        self.current_summary = None
        self.progress_dialog = None
        self.current_prompt = {}
        self.current_overrides = {}
        self.parent_act_summary = None  # Store the parent ActSummary during chapter processing

    def create_chapter_summary(self):
        """Generate summary for a single chapter."""
        current_item = self.project_tree.tree.currentItem()
        if not self._validate_selection(current_item, require_chapter=True):
            return

        prompt = self.view.summary_prompt_panel.get_prompt()
        if not prompt:
            self._show_warning(_("Selected prompt not found."))
            return

        overrides = self.view.summary_prompt_panel.get_overrides()
        scenes = self.model.gather_child_content(current_item, self.view.model, force_scene_text=True)
        if not scenes:
            self._show_warning(_("No content found to summarize."))
            return

        hierarchy = self.model._get_hierarchy(current_item)
        self.current_summary = ChapterSummary(hierarchy, scenes)
        self.current_prompt = prompt
        self.current_overrides = overrides
        
        self.view.scene_editor.editor.clear()

        self.progress_dialog = ProgressDialog(self.view)
        self.progress_dialog.show()
        QApplication.processEvents()
        self.progress_dialog.append_message(_("Processing summary for chapter '{}'").format(hierarchy[-1]))
        self._process_next_scene()

    def create_act_summary(self):
        """Generate summary for an act, combining chapter summaries."""
        current_item = self.project_tree.tree.currentItem()
        if not self._validate_selection(current_item, require_chapter=False):
            return

        prompt = self.view.summary_prompt_panel.get_prompt()
        if not prompt:
            self._show_warning(_("Selected prompt not found."))
            return

        overrides = self.view.summary_prompt_panel.get_overrides()
        mode = self.view.summary_mode_combo.itemData(self.view.summary_mode_combo.currentIndex())
        force_scene_text = mode == SummaryMode.IGNORE_EXISTING

        chapters = self._gather_chapter_data(current_item, force_scene_text)
        if not chapters:
            self._show_warning(_("No chapters found to summarize."))
            return

        hierarchy = self.model._get_hierarchy(current_item)
        self.current_summary = ActSummary(hierarchy, chapters)
        self.current_prompt = prompt
        self.current_overrides = overrides

        self.view.scene_editor.editor.clear()

        self.progress_dialog = ProgressDialog(self.view)
        self.progress_dialog.show()
        QApplication.processEvents()
        self.progress_dialog.append_message(_("Processing summary for act '{}' with {} chapters").format(hierarchy[-1], len(chapters)))
        self._process_next_chapter()

    def delete_summary(self):
        current_item = self.project_tree.tree.currentItem()
        if not self._validate_selection(current_item):
            return
        hierarchy = self.model._get_hierarchy(current_item)
        reply = QMessageBox.question(
            self.view,
            _("Delete Summary"),
            _("Are you sure you want to delete the summary for {}?").format("/".join(hierarchy)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.view.scene_editor.editor.clear()
            if self.project_tree.model.reset_summary(hierarchy):
                self.progress_updated.emit(_("Summary deleted for {}").format('/'.join(hierarchy)))
            else:
                self._show_error(_("Summary delete failed."))

    def _validate_selection(self, item, require_chapter=False):
        if not item:
            self._show_warning(_("Please select an item."))
            return False
        level = self.project_tree.get_item_level(item)
        if require_chapter and level != 1:
            self._show_warning(_("Please select a Chapter."))
            return False
        if level >= 2:
            self._show_warning(_("Please select an Act or Chapter (not a Scene)."))
            return False
        return True

    def _gather_chapter_data(self, act_item, force_scene_text):
        """Gather chapter data for act summary."""
        chapters = []
        hierarchy = self.model._get_hierarchy(act_item)
        for i in range(act_item.childCount()):
            chapter_item = act_item.child(i)
            chapter_hierarchy = self.model._get_hierarchy(chapter_item)
            scenes = self.model.gather_child_content(chapter_item, self.view.model, force_scene_text)
            if scenes:
                node = self.project_tree.model._get_node_by_hierarchy(chapter_hierarchy)
                existing_summary = self.project_tree.model.load_summary(chapter_hierarchy) if not force_scene_text and node.get("has_summary", False) else None
                chapters.append(ChapterSummary(chapter_hierarchy, scenes, existing_summary))
        return chapters

    def _process_next_chapter(self):
        """Process the next chapter in an act summary."""
        if not isinstance(self.current_summary, ActSummary) or not self.current_summary.chapters:
            self._finalize_act_summary()
            return

        chapter = self.current_summary.chapters[0]
        self.current_summary.chapters.pop(0)
        if chapter.existing_summary and self.view.summary_mode_combo.itemData(self.view.summary_mode_combo.currentIndex()) != SummaryMode.IGNORE_EXISTING:
            max_tokens = self.current_overrides.get("max_tokens", self.model.max_tokens)
            plain_text, token_count = self.model.optimize_text(chapter.existing_summary, max_tokens)
            if token_count > max_tokens:
                self.progress_dialog.append_message(_("Existing summary for chapter '{}' exceeds token limit ({}/{} tokens). Truncating content.").format(chapter.hierarchy[-1], token_count, max_tokens))
            self.progress_dialog.append_message(_("Summarizing existing summary for chapter '{}'").format(chapter.hierarchy[-1]))
            self.current_summary.partial_summary = f"\n\nChapter '{chapter.hierarchy[-1]}': "  # Store chapter header temporarily
            self.service.generate_summary(self.current_prompt, plain_text, self.current_overrides)
            time.sleep(self.RATE_LIMIT_DELAY)  # Add delay to prevent throttling
            return

        self.parent_act_summary = self.current_summary  # Store ActSummary before switching
        self.current_summary = chapter  # Temporarily switch to chapter processing
        self._process_next_scene()

    def _process_next_scene(self):
        """Process the next scene in a chapter summary."""
        if not isinstance(self.current_summary, ChapterSummary):
            self._process_next_chapter()
            return

        if self.current_summary.current_scene_index >= len(self.current_summary.scenes):
            self._finalize_chapter_summary()
            return

        max_tokens = self.current_overrides.get("max_tokens", self.model.max_tokens)
        scene_data = self.current_summary.scenes[self.current_summary.current_scene_index]
        plain_text, token_count = self.model.optimize_text(scene_data["text"], max_tokens)
        if token_count > max_tokens:
            self.progress_dialog.append_message(_("{} '{}' exceeds token limit ({}/{} tokens). Truncating content.").format(scene_data['type'].capitalize(), scene_data['name'], token_count, max_tokens))

        self.progress_dialog.append_message(_("Generating summary for {} '{}' in '{}' ({} of {})").format(scene_data['type'], scene_data['name'], self.current_summary.hierarchy[-1], self.current_summary.current_scene_index + 1, len(self.current_summary.scenes)))
        self.current_summary.partial_summary += f"\n\n{scene_data['name']}: "
        self.service.generate_summary(self.current_prompt, plain_text, self.current_overrides)
        self.current_summary.current_scene_index += 1
        time.sleep(self.RATE_LIMIT_DELAY)  # Add delay to prevent throttling

    def _finalize_chapter_summary(self):
        """Save the completed chapter summary and resume act processing if needed."""
        if isinstance(self.current_summary, ChapterSummary):
            summary_text = self.current_summary.partial_summary.strip()
            if summary_text:
                self.view.scene_editor.editor.clear()
                self._update_editor(summary_text)
                if not self.parent_act_summary:
                    self.project_tree.model.save_summary(self.current_summary.hierarchy, summary_text)
                
                # If part of an act summary, send the chapter summary to LLM for further summarization
                if self.parent_act_summary:
                    mode = self.view.summary_mode_combo.itemData(self.view.summary_mode_combo.currentIndex())
                    if mode == SummaryMode.ACT_AND_CHAPTERS:
                        self.project_tree.model.save_summary(self.current_summary.hierarchy, summary_text)
                        self.progress_dialog.append_message(_("Saved summary for chapter '{}'").format(self.current_summary.hierarchy[-1]))

                    max_tokens = self.current_overrides.get("max_tokens", self.model.max_tokens)
                    plain_text, token_count = self.model.optimize_text(summary_text, max_tokens)
                    if token_count > max_tokens:
                        self.progress_dialog.append_message(_("Chapter summary for '{}' exceeds token limit ({}/{} tokens). Truncating content.").format(self.current_summary.hierarchy[-1], token_count, max_tokens))
                    self.progress_dialog.append_message(_("Summarizing chapter summary for '{}'").format(self.current_summary.hierarchy[-1]))
                    self.parent_act_summary.partial_summary = f"\n\nChapter '{self.current_summary.hierarchy[-1]}': "  # Store chapter header
                    self.service.generate_summary(self.current_prompt, plain_text, self.current_overrides)
                    self.current_summary = self.parent_act_summary  # Restore ActSummary
                    self.parent_act_summary = None  # Clear parent reference
                    time.sleep(self.RATE_LIMIT_DELAY)  # Add delay to prevent throttling
                    return
            else:
                self.progress_dialog.append_message(_("The summary is empty. Summary generation completed."))
                if self.parent_act_summary:
                    self.current_summary = self.parent_act_summary  # Restore ActSummary
                    self.parent_act_summary = None
                    self._process_next_chapter()
                    return
            
            self.current_summary = None
            self._process_next_chapter()

    def _finalize_act_summary(self):
        """Finalize and save the act summary."""
        if isinstance(self.current_summary, ActSummary):
            combined_text = self.current_summary.combined_summary.strip()
            if combined_text:
                max_tokens = self.current_overrides.get("max_tokens", self.model.max_tokens)
                token_count = len(self.model.encoding.encode(combined_text))
                if token_count > max_tokens:
                    self.progress_dialog.append_message(_("Combined chapter summaries exceed token limit ({}/{} tokens). Summarizing summaries...").format(token_count, max_tokens))
                    plain_text, unused = self.model.optimize_text(combined_text, max_tokens)
                    self.service.generate_summary(self.current_prompt, plain_text, self.current_overrides)
                else:
                    self.view.scene_editor.editor.clear()
                    self._update_editor(combined_text)
                    self.project_tree.model.save_summary(self.current_summary.hierarchy, combined_text)
                    self.progress_dialog.append_message(_("Saved summary for act '{}'").format(self.current_summary.hierarchy[-1]))
            self.current_summary = None
            self.progress_dialog.append_message(_("Summary generation completed."))
            self.service.cleanup_worker()

    def preview_summary(self):
        """Preview the summary prompt."""
        prompt = self.view.summary_prompt_panel.get_prompt()
        if not prompt.get("name") or prompt.get("name") == _("Select Summary Prompt"):
            self._show_warning(_("Please select a summary prompt."))
            return

        current_item = self.project_tree.tree.currentItem()
        if not self._validate_selection(current_item):
            return

        mode = self.view.summary_mode_combo.itemData(self.view.summary_mode_combo.currentIndex())
        force_scene_text = mode == SummaryMode.IGNORE_EXISTING
        scene_data = self.model.gather_child_content(current_item, self.view.model, force_scene_text=force_scene_text)
        if not scene_data:
            self._show_warning(_("No content found to summarize."))
            return

        overrides = self.view.summary_prompt_panel.get_overrides()
        max_tokens = overrides.get("max_tokens", self.model.max_tokens)
        combined_text = self._build_preview_text(scene_data, force_scene_text, max_tokens)

        dialog = PromptPreviewDialog(
            controller=self.view.controller,
            prompt_config=prompt,
            user_input=None,
            additional_vars=None,
            current_scene_text=combined_text,
            extra_context=None
        )
        dialog.exec_()

    def _build_preview_text(self, scene_data, force_scene_text, max_tokens):
        """Build preview text for the summary prompt."""
        chapters = {}
        for scene in scene_data:
            hierarchy = scene["hierarchy"][:-1]
            hierarchy_str = "/".join(hierarchy)
            if hierarchy_str not in chapters:
                node = self.project_tree.model._get_node_by_hierarchy(hierarchy)
                has_summary = node.get("has_summary", False) if node else False
                existing_summary = self.project_tree.model.load_summary(hierarchy) if not force_scene_text and has_summary else None
                chapters[hierarchy_str] = {
                    "name": hierarchy[-1],
                    "content": [],
                    "existing_summary": existing_summary
                }
            chapters[hierarchy_str]["content"].append(scene)

        combined_text = ""
        for chapter in chapters.values():
            if chapter["existing_summary"] and not force_scene_text:
                combined_text += f"### Chapter '{chapter['name']}'\n{chapter['existing_summary']}\n\n"
            else:
                for i, data in enumerate(chapter['content'], 1):
                    plain_text, token_count = self.model.optimize_text(data["text"], max_tokens)
                    if token_count > max_tokens:
                        self.progress_dialog.append_message(_("{} '{}' exceeds token limit ({}/{} tokens). Truncating for preview.").format(data['type'].capitalize(), data['name'], token_count, max_tokens))
                    combined_text += f"### {data['type'].capitalize()} '{data['name']}'\n{plain_text}\n\n"
        return combined_text

    def _partial_update(self, text: str):
        if isinstance(self.current_summary, ChapterSummary):
            self.current_summary.partial_summary += text
        elif isinstance(self.current_summary, ActSummary):
            self.current_summary.combined_summary += self.current_summary.partial_summary + text
            self.current_summary.partial_summary = ""  # Clear temporary chapter header
        self._update_editor(text)

    def _update_editor(self, text: str):
        editor = self.view.scene_editor.editor
        editor.insertPlainText(text.strip())

    def _on_service_finished(self):
        if hasattr(self.service, 'worker') and self.service.worker and hasattr(self.service.worker, 'error') and self.service.worker.error:
            self.progress_dialog.append_message(_("Error processing scene {}. Skipping to next scene.").format(self.current_summary.current_scene_index))
        self._process_next_scene()

    def _show_warning(self, message):
        QMessageBox.warning(self.view, _("Summary"), message)

    def _show_error(self, message):
        QMessageBox.critical(self.view, _("Summary Error"), message)