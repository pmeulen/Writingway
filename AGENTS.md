# Writingway agent guide

## Architecture map
- `main.py` boots gettext/translation, checks a few hard dependencies, applies the saved theme/font, then launches `workbench.WorkbenchWindow`.
- `workbench.py` is the project launcher. It reads/writes `Projects/projects.json`, opens one `project_window.ProjectWindow` per project, and tracks the last opened project.
- `project_window/project_window.py` is the main editor shell. It composes the activity bar/sidebar (project tree, search/replace, compendium_panel, embedded prompts), scene editor, bottom stack, and tools like focus mode, whisper, workshop, web LLM, and Internet Archive.
- `project_window/project_model.py` owns project state and persistence: structure JSON, project settings, autosave, and compendium-backed data.
- `project_window/project_settings_manager.py` loads/saves per-project settings from `Projects/<project>/project_settings.json` (separate from global `settings.json`).
- `project_window/rewrite_feature.py` provides `RewriteDialog` — a side-by-side rewrite dialog that sends selected text + a chosen prompt to the LLM and lets the user apply the result.
- `project_window/token_limit_dialog.py` provides `TokenLimitDialog` — shown when a prompt exceeds the model's token limit; lets the user edit the summary or truncate.
- `project_window/progress_dialog.py` provides `ProgressDialog` — a streaming log for batch summary generation.
- Project tree edits (acts, chapters, sections) go through `project_window/tree_manager.py` and `project_window/project_structure_manager.py`; updates propagate by `ProjectModel.structureChanged` and are mirrored back into the `QTreeWidget`.
- LLM prompts flow through `muse/prompt_panel.py` / `project_window/embedded_prompts_panel.py` (prompt JSON in `Projects/prompts.json`), `muse/prompt_handler.py` (prompt assembly), and `settings/llm_api_aggregator.py` + `settings/llm_worker.py` (streaming response).
- Summary generation flows through `project_window/bottom_stack.py` (summary UI), `project_window/summary_controller.py` (act/chapter orchestration), `project_window/summary_service.py` (LLM worker lifecycle), and `project_window/summary_model.py` (token-aware content shaping).
- Compendium data is managed by `compendium/compendium_manager.py` and surfaced in `compendium/compendium_panel.py` / `compendium/context_panel.py`.
- `settings/autosave_manager.py` handles autosave timers and `build_scene_identifier(project, hierarchy)` for unique file naming; `settings/backup_manager.py` manages versioned backups and exposes `show_backup_dialog()`.
- `settings/selection_manager.py` (`SelectionManager`) persists `QTreeWidget` checkbox states per project/panel to `Projects/<project>/selections.json`.

### `util/` package
Standalone utilities launched as tools from the main window:
- `util/web_llm.py` (`MainWindow`) — embedded web browser with LLM integration for browsing/summarising web content.
- `util/whisper_app.py` (`WhisperApp`) — OpenAI Whisper speech-to-text transcription tool.
- `util/tts_manager.py` (`WW_TTSManager`) — text-to-speech via `pyttsx3`; reads `general.fast_tts` from settings.
- `util/ia_window.py` (`IAWindow`) + `ia_*_tab.py` tabs — Internet Archive browser (search, download, manage, login).
- `util/wikidata_dialog.py` — Wikipedia/Wikidata lookup dialog for research.
- `util/statistics.py` — project statistics: word counts, character mentions, writing metrics, charts (`PyQt5.QtChart`).
- `util/text_analysis_gui.py` (`TextAnalysisApp`) — prose analysis UI; delegates to language-specific analyser modules.
- `util/base_text_analysis.py` — abstract base class for language analysers; concrete implementations live in `util/analyzers/text_analysis_<lang>.py` (e.g. `text_analysis_en.py`, `text_analysis_de.py`, …20+ locales).
- `util/color_manager.py` (`ColorManager`) — persists user-chosen foreground/background colours for scene text.
- `util/find_dialog.py` (`FindDialog`) — standalone find/replace dialog used by RAG PDF and other tools.

### `workshop/` package
Follows MVC: `WorkshopController` (`workshop_controller.py`) wires `WorkshopModel` (`workshop_model.py`) to `WorkshopView` (`workshop_view.py`).
- Chat sessions: `workshop/chat_session.py` defines `BaseChatSession`, `WritingCoachSession`, `RolePlaySession`.
- Conversation persistence: `workshop/conversation_manager.py` + `workshop/conversation_history_manager.py` (token-aware summarisation via `tiktoken`).
- RAG tools: `workshop/rag_pdf.py` (`PdfRagApp`) — PDF ingestion/Q&A; `workshop/rag_smart_qa.py` (`SmartQAWidget`) — smart QA over processed documents; `workshop/rag_visual_explorer.py`, `workshop/rag_manual_processing.py`, `workshop/rag_utils.py`.
- `workshop/embedding_manager.py` — FAISS-backed embedding index (dummy embeddings by default; replace `get_embedding()` for production).
- `workshop/project_context_provider.py` (`ProjectContextProvider`) — lightweight adapter giving Workshop access to project structure/scene content without importing the full `ProjectModel`.

## Compendium data format
Compendium data is stored in `Projects/<project>/compendium.json` and is managed by `compendium/compendium_manager.py`. 
- `compendium/enhanced_compendium.py` is the main editor for compendium entries
- `compendium/compendium_panel.py` is the main UI for browsing/searching compendium entries from the project window, it is read-only
- `compendium/ai_compendium_dialog.py` (`AICompendiumDialog`) — AI-assisted editor for bulk-generating or refining compendium entries.
- `compendium/pov_combobox.py` — `PovComboBox` widget used in the scene editor; defines two sentinel UUID constants: `NONE_CHARACTER_UUID` (no POV) and `NEW_CHARACTER_UUID` (create new).
- New character entries can be added from the POV selector in the scene editor using a simplified dialog that writes directly to the compendium_manager (bypassing the enhanced editor)
- **Always use `CompendiumManager.make_empty_entry(name)` to create new entries** — it guarantees all canonical fields are present: `name`, `content`, `uuid`, `details`, `tags`, `relationships`, `images`.
- `CompendiumEventBus` (singleton via `CompendiumEventBus.get_instance()`) broadcasts compendium updates cross-component; subscribe with `add_updated_listener(callback)` and unsubscribe with `remove_updated_listener(callback)` when the widget is destroyed.

## General coding conventions
- Add type hints to all functions, including return types.
- Use f-strings for string formatting
- Use uuid4 strings for all IDs (projects, acts, chapters, sections, compendium entries, prompts); generate with `str(uuid.uuid4())`. Prefer to reference items by ID rather than name. Names can change and aren't guaranteed to be unique.
- Create one logger per module: `logger = logging.getLogger(__name__)`.
- Log application flow events and user actions (switching project, loading project, saving project/compendium entry, making a backup, creating chapters/sections/acts, making a choice, sending a prompt to an LLM, stopping it, ets ) with `logger.info()`. Log errors with `logger.error()`. Log warnings with `logger.warning()`.  
- Always log errors with `logger.error()`. Log warnings with `logger.warning()`.

## Qt coding conventions
- Use fully qualified names for Qt attributes. E.g. `QFont.Weight.Bold`, not just `QFont.Bold`
- Create `_setup_some_widget(self) -> None` from the `__init__` of a QMainWindow/QWidget for longer setup code. These functions store references to the widget in the class instance, they do not return them.
- Name slots `_on_<source>_<event>` (e.g. `_on_save_button_clicked`
- Put blockSignals(True)/blockSignals(False) around batch programmatic UI updates to prevent cascading signal chains
- Tree items store the backing dict in `Qt.ItemDataRole.UserRole`; common fields: `uuid`
- Use MVC for UI logic.
- Use the `ThemeManager` to get styling. Do not hardcode colors, fonts, or sizes in the UI; if something isn't in the theme, signal this and propose to add it.

## Project-specific coding conventions
- Use `WWSettingsManager.get_project_path()` / `sanitize()` for project files; project data lives under `Projects/<sanitized project>/`. Use `WWSettingsManager.get_project_relpath(project_name, filename)` to build a full relative path to a file inside a project directory (e.g. `compendium.json`, `selections.json`).
- `EmbeddedPromptsPanel` debounces prompt edits and keeps default prompts read-only; prompt changes are saved back to shared `Projects/prompts.json` (with backup `Projects/prompts.bak.json`).
- Prompt category defaults come from `muse/prompt_utils.py`; keep prompt IDs stable (`default_<category>` for built-ins) because UI logic treats those as non-editable defaults.
- Workshop features follow strict MVC: logic in `WorkshopController`, state in `WorkshopModel`, display in `WorkshopView`. Do not add business logic directly to view widgets.
- Use `SelectionManager(project_name, panel_id)` (from `settings/selection_manager.py`) to persist `QTreeWidget` checkbox states; do not roll your own JSON serialisation for this.

## Developer workflow
- Run the app from the repo root with `python main.py`.
- The documented macOS/Linux startup path is `source start.sh` after `source setup_writingway.sh` creates `venv`, installs `requirements.txt`, and downloads `en_core_web_sm`.
- Packaging is PyInstaller-based: `TARGET_ARCH=arm64 pyinstaller pyinstaller/Writingway_osx.spec` (mirrors `.github/workflows/build-osx-arm64.yml`).
- Developer dependencies and developer tool configuration lives in `pyproject.toml`
- Install developer dependencies with `pip install ".[dev]"`
- Before committing run: `ruff check --fix .`
- Type checking: `mypy .` (configured in `pyproject.toml`; `disallow_untyped_defs` is off to ease incremental adoption) or `pyright` (set to `basic` mode). Both are configured to suppress spurious Qt/third-party stub warnings.

## Testing infrastructure
- Test runner: **pytest** + **pytest-qt** (Qt fixtures) + **pytest-cov** (coverage).
- Run all tests from the repo root: `python -m pytest tests/`.
- Configuration lives in `pytest.ini`.
- Tests are under `tests/`, mirroring the source package layout — e.g. `tests/compendium/` covers `compendium/`, `tests/settings/` covers `settings/`.
- Always write unit tests and check that they pass for new features.
- Test both positive and negative scenarios
- Read TESTING.md before writing or modifying tests.

## Where to look first
- Project structure bugs: `project_window/project_model.py`, `project_window/tree_manager.py`, `project_window/project_tree_widget.py`.
- Per-project settings bugs: `project_window/project_settings_manager.py`.
- Prompt/LLM bugs: `muse/prompt_panel.py`, `muse/prompt_handler.py`, `settings/llm_api_aggregator.py`, `settings/llm_worker.py`.
- Summary bugs: `project_window/summary_controller.py`, `project_window/summary_service.py`, `project_window/summary_model.py`, `project_window/bottom_stack.py`.
- Rewrite/token-limit bugs: `project_window/rewrite_feature.py`, `project_window/token_limit_dialog.py`.
- Compendium bugs: `compendium/compendium_manager.py`, `compendium/compendium_panel.py`, `compendium/context_panel.py`.
- POV/character selector bugs: `compendium/pov_combobox.py`.
- Tool-launch bugs: `project_window/global_toolbar.py`, `project_window/project_window.py`.
- Workshop/chat bugs: `workshop/workshop_controller.py`, `workshop/workshop_model.py`, `workshop/workshop_view.py`, `workshop/chat_session.py`.
- RAG/PDF bugs: `workshop/rag_pdf.py`, `workshop/rag_smart_qa.py`, `workshop/rag_utils.py`.
- Text analysis bugs: `util/text_analysis_gui.py`, `util/base_text_analysis.py`, `util/analyzers/`.
- TTS bugs: `util/tts_manager.py`.
- Web browser bugs: `util/web_llm.py`.
- Whisper/audio bugs: `util/whisper_app.py`.
- Internet Archive bugs: `util/ia_window.py` + `util/ia_*_tab.py`.
- Statistics bugs: `util/statistics.py`.
- Autosave/backup bugs: `settings/autosave_manager.py`, `settings/backup_manager.py`.
