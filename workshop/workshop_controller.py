import datetime
import re
from gettext import gettext as _
from typing import Any, cast

from PyQt5.QtGui import QCursor, QPixmap
from PyQt5.QtWidgets import QMessageBox

from muse.prompt_preview_dialog import PromptPreviewDialog
from settings.llm_api_aggregator import WWApiAggregator
from settings.llm_worker import LLMWorker
from settings.settings_manager import WWSettingsManager

from .audio_utils import AudioRecorder, TranscriptionWorker
from .chat_session import RolePlaySession, WritingCoachSession
from .project_context_provider import ProjectContextProvider
from .rag_pdf import PdfRagApp
from .workshop_model import WorkshopModel
from .workshop_view import WorkshopView


class WorkshopController:
    def __init__(self, parent=None):
        self.model = WorkshopModel(parent.model if parent else None)
        self.view = WorkshopView(parent, self)
        self.parent_controller = parent
        self.current_session = None
        self.char_name = "Coach"
        self.worker = None
        self.current_assistant_response = ""
        self.is_streaming = False
        self.pre_stream_cursor_pos = None
        self.waiting_cursor = QCursor(QPixmap("assets/icons/clock.svg"))
        self.normal_cursor = QCursor()
        self.pdf_window = None
        self.connect_signals()
        self.load_conversations()
        if self.model.conversation_manager.last_viewed_chat:
            self.view.set_current_conversation_item(self.model.conversation_manager.last_viewed_chat)
            self.on_conversation_selection_changed()

    def connect_signals(self):
        self.view.new_chat_button.clicked.connect(self.new_conversation)
        self.view.conversation_list.itemSelectionChanged.connect(self.on_conversation_selection_changed)
        self.view.conversation_list.customContextMenuRequested.connect(self.show_conversation_context_menu)
        self.view.send_button.clicked.connect(self.on_send_or_stop)
        self.view.preview_button.clicked.connect(self.preview_prompt)
        self.view.context_button.clicked.connect(self.toggle_context_panel)
        self.view.pdf_rag_btn.clicked.connect(self.open_pdf_rag_tool)
        self.view.record_button.clicked.connect(self.toggle_recording)
        self.view.pause_button.clicked.connect(self.toggle_pause)
        self.view.recording_timer.timeout.connect(self.update_recording_time)
        self.view.zoom_in_shortcut.activated.connect(self.zoom_in)
        self.view.zoom_out_shortcut.activated.connect(self.zoom_out)
        if self.parent_controller and hasattr(self.parent_controller.model, "structureChanged"):
            self.parent_controller.model.structureChanged.connect(self.view.context_panel.on_structure_changed)

    def load_conversations(self):
        self.view.conversation_list.clear()
        for name in self.model.conversation_manager.get_conversation_names():
            mode = self.model.conversation_manager.get_mode(name)
            icon_path = self.model.conversation_manager.get_icon_path(mode)
            self.view.add_conversation_item(name, icon_path)

    def on_conversation_selection_changed(self):
        # 1. Save the previous session's context before switching
        if hasattr(self, '_current_chat_name') and self._current_chat_name:
            self.save_context_to_manager(self._current_chat_name)

        name = self.view.get_selected_conversation()
        if not name:
            return

        self._current_chat_name = name # Track current name for lifecycle
        conv = self.model.conversation_manager.get_conversation(name)
        chat_project = conv.get("project_name")

        # === TEMPORARILY LOAD THE CHAT SO USER CAN SEE IT ===
        self.current_session = self.create_session(conv["mode"], conv["messages"])
        self.update_chat_log("Coach")  # Temporary display with default speaker

        # Project might have been renamed or deleted
        if not chat_project or chat_project not in self.model.conversation_manager.project_names:
            chat_project = self._prompt_for_project_association(name)
            if not chat_project:
                # User cancelled → fallback to current project
                chat_project = self.model.project_name

        if not isinstance(chat_project, str) or not chat_project:
            return
        chat_project_name: str = chat_project

        # Switch ContextPanel if needed
        if chat_project_name != self.view.context_panel.project_name:
            structure = self.model.load_project_structure(chat_project_name)
            provider = ProjectContextProvider(chat_project_name)
            self.view.context_panel.switch_to_project(chat_project_name, structure=structure, context_provider=provider)

        selections = self.model.conversation_manager.get_context_selections(name)

        # Determine mandatory items (POV Character)
        mandatory = []
        self.char_name = "Coach"
        if conv.get("mode") == "Role Play" and conv.get("pov_character"):
            # Note: This assumes we can find which category the character is in,
            # or we store the full path. If POV is just a name, we find the first match.
            self.char_name = conv["pov_character"]
            mandatory = self._find_compendium_path_by_name(self.char_name)

        self.view.context_panel.set_selections(
            selections["project"],
            selections["compendium"],
            mandatory_compendium_paths=mandatory
        )

        self.model.conversation_manager.set_last_viewed(name)
        self.update_chat_log(self.char_name)
        category = "Roleplay" if conv["mode"] == "Role Play" else "Workshop"
        self.view.prompt_panel.set_category(category)
        self.model.conversation_manager.save()

    def save_context_to_manager(self, chat_name):
        """Helper to pull state from UI into the data manager."""
        project_uuids, comp_paths = self.view.context_panel.get_selections()
        self.model.conversation_manager.update_context_selections(
            chat_name, project_uuids, comp_paths
        )

    def _find_compendium_path_by_name(self, name):
        """Helper to turn a POV character name into a 'Category/Name' path."""
        if not self.view or not self.view.context_panel:
            return []

        root = self.view.context_panel.compendium_tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            for j in range(cat_item.childCount()):
                if cat_item.child(j).text(0) == name:
                    return [f"{cat_item.text(0)}/{name}"]
        return []

    def create_session(self, mode, messages):
        if mode == "Writing Coach":
            return WritingCoachSession(messages, self.view.context_panel, self.view.prompt_panel, self.model.embedding_index)
        elif mode == "Role Play":
            return RolePlaySession(messages, self.view.context_panel, self.view.prompt_panel, self.model.embedding_index)
        raise ValueError(f"Unknown mode: {mode}")

    def update_chat_log(self, char_name="Coach"):
        self.view.clear_chat_log()
        if not self.current_session:
            return
        messages = self.current_session.messages
        n = len(messages)

        for idx, msg in enumerate(messages):
            role = msg.get("role", "Unknown").capitalize()
            content = msg.get("content", "")
            is_edited = msg.get("edited", False)
            speaker = char_name if role == "Assistant" else "User"
            is_last_user = (role.lower() == "user" and idx == len(messages) - 2)  # Before last assistant
            self.view.append_to_chat_log(speaker, content, is_last_user=is_last_user, is_edited=is_edited)
        self.view.format_chat_log_html()

        # Ensure scroll to bottom
        scrollbar = self.view.chat_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def new_conversation(self):
        # Save current before creating new
        if self.model.conversation_manager.last_viewed_chat:
            self.save_context_to_manager(self.model.conversation_manager.last_viewed_chat)

        mode, name, pov = self.view.show_new_chat_dialog()
        if mode and name:
            try:
                # Assume Project is always the one where Workshop was launched from
                self.model.conversation_manager.add_conversation(name, mode, pov, project_name=self.model.project_name)
                icon_path = self.model.conversation_manager.get_icon_path(mode)
                self.view.add_conversation_item(name, icon_path)
                self.view.set_current_conversation_item(name)
                self.model.conversation_manager.save()
            except ValueError as e:
                self.view.show_message_box(_("Error"), str(e))

    def generate_unique_chat_name(self):
        existing_numbers = [int(re.match(r'^Chat (\d+)$', name).group(1)) for name in self.model.conversation_manager.get_conversation_names() if re.match(r'^Chat (\d+)$', name)]
        number = max(existing_numbers, default=0) + 1
        return f"Chat {number}"

    def show_conversation_context_menu(self, pos):
        item = self.view.conversation_list.itemAt(pos)
        if item:
            from PyQt5.QtWidgets import QMenu
            menu = QMenu()
            rename_action = menu.addAction(_("Rename"))
            delete_action = menu.addAction(_("Delete"))
            action = menu.exec_(self.view.conversation_list.mapToGlobal(pos))
            if action == rename_action:
                self.rename_conversation(item)
            elif action == delete_action:
                self.delete_conversation(item)

    def rename_conversation(self, item):
        current_name = item.text()
        new_name, ok = self.view.show_rename_dialog(current_name)
        if ok:
            new_name = new_name.strip()
            if new_name and new_name != current_name:
                try:
                    self.model.conversation_manager.rename_conversation(current_name, new_name)
                    item.setText(new_name)
                    self.model.conversation_manager.save()
                except ValueError as e:
                    self.view.show_message_box(_("Invalid Name"), str(e))

    def delete_conversation(self, item):
        name = item.text()
        if self.view.show_delete_confirmation(name):
            row = self.view.conversation_list.row(item)
            self.view.remove_conversation_item(row)
            self.model.conversation_manager.delete_conversation(name)
            if not self.model.conversation_manager.conversations:
                self.new_conversation()  # Create default if empty
            self.model.conversation_manager.save()

    def on_send_or_stop(self):
        if self.is_streaming:
            self.stop_llm()
        else:
            self.send_message()

    def edit_last_user_message(self):
        """Handle Edit for last user message."""
        if not self.current_session or not self.current_session.messages:
            return

        # Find last user message
        messages = self.current_session.messages
        last_user_idx = None
        for i in range(len(messages)-1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            return

        last_user_msg = messages[last_user_idx]["content"]
        # Confirm
        confirm = QMessageBox.question(
            self.view,
            _("Edit Message"),
            _("This will replace the current chat input with the previous prompt.\n"
            "The last User + Assistant exchange will be marked as edited (struck out).\n"
            "They will be removed only after you send a new message.\n\n"
            "Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.current_session.mark_last_exchange_as_edited()
            self.view.chat_input.setPlainText(last_user_msg)
            self.update_chat_log(self.char_name)
            # Strike out last exchange in UI
            # self._strike_last_exchange_in_log()
        return

    def delete_last_exchange(self):
        """Permanently delete last User + Assistant pair."""
        if not self.current_session or len(self.current_session.messages) < 2:
            return

        confirm = QMessageBox.question(
            self.view,
            _("Delete Exchange"),
            _("Permanently delete the last User message and Assistant response?\n"
            "This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            # Remove last two messages (user + assistant)
            self.current_session.messages = self.current_session.messages[:-2]
            # Update model
            current_chat = self.model.conversation_manager.last_viewed_chat
            self.model.conversation_manager.update_messages(current_chat, self.current_session.messages)
            self.model.conversation_manager.save()
            # Refresh UI
            self.update_chat_log(self.char_name)

    def _strike_last_exchange_in_log(self):
        """Visually strike out last User + Assistant."""
        # Re-render chat log with strike-through for last messages
        self.update_chat_log(self.char_name)  # For now, full refresh; enhance later with <del>
        # TODO: Implement specific strike by modifying last HTML entries if needed

    def send_message(self):
        user_input = self.view.chat_input.toPlainText().strip()
        if not user_input or not self.current_session.validate():
            if not self.current_session.validate():
                self.view.show_message_box(_("Error"), _("Role Play mode requires at least one compendium character to be selected."))
            return

        self._remove_edited_messages()

        self.current_assistant_response = ""
        payload = self.current_session.construct_message(user_input)
        if payload:
            self.current_session.append_message("user", user_input)
            self.view.append_to_chat_log("User", user_input, is_last_user=True)
            self.view.start_new_streaming_message(self.char_name)
            self.view.chat_input.clear()
            self.start_llm(payload)

    def _remove_edited_messages(self):
        """Remove any messages marked as edited before adding a new user message."""
        if not self.current_session:
            return

        # Keep only messages that are NOT marked as edited
        cleaned_messages = [
            msg for msg in self.current_session.messages
            if not msg.get("edited", False)
        ]

        self.current_session.messages = cleaned_messages

        # Also clear the 'edited' flag from any remaining messages (defensive)
        for msg in self.current_session.messages:
            msg.pop("edited", None)

    def start_llm(self, payload):
        overrides = self.view.prompt_panel.get_overrides()
        self.worker = LLMWorker(payload, overrides)
        self.worker.data_received.connect(self.handle_stream_data)
        self.worker.stream_finished.connect(self.handle_stream_finished)
        self.worker.token_limit_exceeded.connect(self.handle_token_limit)
        self.worker.start()
        self.is_streaming = True
        self.view.set_send_button_icon("assets/icons/stop-circle.svg")
        self.pre_stream_cursor_pos = self.view.chat_log.textCursor().position()

    def handle_stream_data(self, data):
        """Accumulate streaming chunks and display them."""
        if not data:
            return
        self.current_assistant_response += data
        self.view.append_to_chat_log(self.char_name, self.current_assistant_response, is_streaming=True)

    def handle_stream_finished(self):
        if self.current_session and self.current_assistant_response:
            self.current_session.append_message("assistant", self.current_assistant_response)

            current_chat = self.model.conversation_manager.last_viewed_chat
            self.model.conversation_manager.update_messages(current_chat, self.current_session.messages)
            self.model.conversation_manager.save()

        self.view.finalize_streaming_message()
        self.update_chat_log(self.char_name)
        self._reset_stream_state()

    def _reset_stream_state(self):
        """Clean up after streaming ends."""
        self.current_assistant_response = ""
        self.is_streaming = False
        self.view.set_send_button_icon("assets/icons/send.svg")
        self.view.format_chat_log_html()
        self.cleanup_worker()

    def handle_token_limit(self):
        self.view.show_message_box(_("Token Limit"), _("Token limit exceeded."))

    def stop_llm(self):
        if self.worker:
            self.worker.stop()

        # Save partial response if any
        if self.current_assistant_response and self.current_session:
            self.current_session.append_message("assistant", self.current_assistant_response + " [Response stopped by user]")
            current_chat = self.model.conversation_manager.last_viewed_chat
            self.model.conversation_manager.update_messages(current_chat, self.current_session.messages)
            self.model.conversation_manager.save()

        self.view.finalize_streaming_message()
        self._reset_stream_state()

    def cleanup_worker(self) -> None:
        if self.worker:
            self.worker.data_received.disconnect()
            self.worker.stream_finished.disconnect()
            self.worker.token_limit_exceeded.disconnect()
            self.worker.deleteLater()
            self.worker = None
        provider_override = self.view.prompt_panel.get_overrides().get("provider")
        provider_name = provider_override if isinstance(provider_override, str) and provider_override else WWSettingsManager.get_active_llm_name()
        _provider = WWApiAggregator.aggregator.get_provider(provider_name)
        # Reset provider if needed

    def preview_prompt(self):
        if self.current_session:
            payload = self.current_session.get_preview_payload(self.view)
            if payload:
                dialog = PromptPreviewDialog(controller=self.parent_controller, conversation_payload=payload, parent=self.view)
                dialog.exec_()

    def toggle_context_panel(self):
        visible = not self.view.context_panel.isVisible()
        self.view.toggle_context_panel_visibility(visible)

    def open_pdf_rag_tool(self):
        self.pdf_window = PdfRagApp()
        self.pdf_window.show()

    def zoom_in(self):
        if self.view.font_size < 24:
            self.view.font_size += 2
            self.view.update_font_size()

    def zoom_out(self):
        if self.view.font_size > 8:
            self.view.font_size -= 2
            self.view.update_font_size()

    def toggle_recording(self):
        if not self.view.record_button.isChecked():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            recording_file = temp_file.name
        self.view.recorder = AudioRecorder()
        self.view.recorder.setup_recording(recording_file)
        cast(Any, self.view.recorder.recording_finished).connect(self.on_recording_finished)
        self.view.recorder.start()
        self.start_time = datetime.datetime.now()
        self.pause_start = None
        self.view.recording_timer.start(1000)
        self.view.set_pause_button_enabled(True)
        self.view.set_record_button_icon("assets/icons/stop-circle.svg")

    def stop_recording(self):
        if self.view.recorder:
            self.view.recorder.stop_recording()
        self.view.recording_timer.stop()
        self.view.set_pause_button_enabled(False)
        self.view.set_record_button_icon("assets/icons/mic.svg")
        self.view.set_time_label("00:00")

    def toggle_pause(self):
        if self.view.recorder.is_paused:
            self.view.recorder.resume()
            self.view.set_pause_button_icon("assets/icons/pause.svg")
            if self.pause_start:
                pause_duration = datetime.datetime.now() - self.pause_start
                self.start_time += pause_duration
                self.pause_start = None
        else:
            self.view.recorder.pause()
            self.view.set_pause_button_icon("assets/icons/play.svg")
            self.pause_start = datetime.datetime.now()

    def update_recording_time(self):
        if self.start_time and not self.view.recorder.is_paused:
            delta = datetime.datetime.now() - self.start_time
            if self.pause_start:
                delta -= datetime.datetime.now() - self.pause_start
            self.view.set_time_label(str(delta).split('.')[0])

    def on_recording_finished(self, file_path):
        self.view.set_override_cursor(self.waiting_cursor)
        language = None if self.view.language_combo.currentText() == "Auto" else self.view.language_combo.currentText()
        self.view.transcription_worker = TranscriptionWorker(file_path, self.view.model_combo.currentText(), language)
        cast(Any, self.view.transcription_worker.transcription_ready).connect(self.handle_transcription)
        self.view.transcription_worker.start()

    def handle_transcription(self, text):
        self.view.restore_cursor()
        if not text.startswith("Error"):
            current_text = self.view.chat_input.toPlainText()
            new_text = current_text + " " + text if current_text else text
            self.view.chat_input.setPlainText(new_text)
        else:
            self.view.show_message_box(_("Transcription Error"), text)

    def close_event_handler(self, event):
        # Final save of context selections
        if self.model.conversation_manager.last_viewed_chat:
            self.save_context_to_manager(self.model.conversation_manager.last_viewed_chat)

        self.stop_llm()
        self.model.conversation_manager.save()
        self.view.write_settings()
        event.accept()

    def _prompt_for_project_association(self, chat_name: str):
        """Ask user which project this chat belongs to (one-time)."""
        projects = self.model.conversation_manager.project_names or [self.model.project_name]

        if len(projects) <= 1:
            project = projects[0]
        else:
            from PyQt5.QtWidgets import QInputDialog
            project, ok = QInputDialog.getItem(
                self.view,
                _("Associate Chat with Project"),
                f"Chat '{chat_name}' has no associated project.\n"
                "Please select the project this conversation belongs to:",
                projects, 0, False
            )
            if not ok:
                return None

        self.model.conversation_manager.update_project_for_conversation(chat_name, project)
        return project
