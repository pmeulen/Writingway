import re
import tiktoken
from PyQt5.QtCore import Qt

class SummaryModel:
    def __init__(self, project_name, max_tokens=16000, encoding_name="cl100k_base"):
        self.project_name = project_name
        self.max_tokens = max_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.structure = None  # Set by controller

    def optimize_text(self, html_content, max_tokens=None):
        """Convert HTML to optimized plain text for LLM, handling token limits."""
        from PyQt5.QtWidgets import QTextEdit
        temp_editor = QTextEdit()
        temp_editor.setHtml(html_content)
        text = temp_editor.toPlainText()

        # Minimal whitespace normalization
        text = re.sub(r'\n+', '\n', text.strip())
        text = re.sub(r'[ \t]+', ' ', text)

        tokens = self.encoding.encode(text)
        effective_max_tokens = max_tokens or self.max_tokens
        if len(tokens) > effective_max_tokens:
            return self._chunk_text(text, tokens, effective_max_tokens), len(tokens)
        return text, len(tokens)

    def _chunk_text(self, text, tokens, max_tokens):
        """Chunk text to fit token limit."""
        target_tokens = int(max_tokens * 0.9)
        trimmed_text = []
        current_tokens = 0

        lines = text.split('\n')
        for line in lines:
            line_tokens = self.encoding.encode(line)
            if current_tokens + len(line_tokens) <= target_tokens:
                trimmed_text.append(line)
                current_tokens += len(line_tokens)
            else:
                remaining_tokens = target_tokens - current_tokens
                if remaining_tokens > 0:
                    partial_line = self.encoding.decode(line_tokens[:remaining_tokens])
                    trimmed_text.append(partial_line)
                break

        result = '\n'.join(trimmed_text)
        final_tokens = self.encoding.encode(result)
        if len(final_tokens) > max_tokens:
            result = self.encoding.decode(final_tokens[:max_tokens])
        return result

    def gather_child_content(self, item, project_model, force_scene_text=False):
        """Recursively gather content from child scenes or summaries from chapters/acts."""
        scene_data = []
        hierarchy = self._get_hierarchy(item)
        
        # If project_model is provided, use it to load summaries for acts/chapters
        if force_scene_text == False and project_model and len(hierarchy) == 2:  # Chapter level
            node = project_model._get_node_by_hierarchy(hierarchy)
            if node and node.get("has_summary", False):
                summary = project_model.load_summary(hierarchy)
                if summary:
                    return [{
                        "name": item.text(0).strip(),
                        "text": summary,
                        "hierarchy": hierarchy,
                        "type": "summary"
                    }]
        
        # Scene-level or no summary available, gather scene content
        if item.childCount() == 0:
            data = item.data(0, Qt.UserRole)
            if len(hierarchy) < 2:  # Only gather content for scenes
                return scene_data
            text = load_latest_autosave(self.project_name, hierarchy) or data.get("content", "")
            if text.strip():
                scene_data.append({
                    "name": item.text(0).strip(),
                    "text": text,
                    "hierarchy": hierarchy,
                    "type": "scene"
                })
        else:
            for i in range(item.childCount()):
                scene_data.extend(self.gather_child_content(item.child(i), project_model))
        return scene_data

    def _get_hierarchy(self, item):
        hierarchy = []
        temp = item
        while temp:
            hierarchy.insert(0, temp.text(0).strip())
            temp = temp.parent()
        return hierarchy

    def build_final_prompt(self, prompt, content):
        """Build the final prompt text for preview or summarization."""
        return f"### User {prompt.get('text')}\n\nContent:\n{content}"

from settings.autosave_manager import load_latest_autosave