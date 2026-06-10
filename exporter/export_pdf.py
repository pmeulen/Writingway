import logging
import os
import platform
from _collections_abc import Callable
from dataclasses import dataclass

import pymupdf
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

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
        self._font_cache: dict[str, pymupdf.Font] = {}
        self._faux_italic_flags: dict[str, bool] = {}
        self._system_fonts_cache: list[str] = []

    def get_font(self, family: str, bold: bool = False, italic: bool = False) -> tuple[pymupdf.Font, bool]:
        key = f"{family.lower()}_{'b' if bold else ''}{'i' if italic else ''}"
        if key in self._font_cache:
            return self._font_cache[key], self._faux_italic_flags.get(key, False)

        is_faux_italic = False
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
            if not os.path.exists(base): continue
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.lower().endswith(valid_exts):
                        self._system_fonts_cache.append(os.path.join(root, f))

    def _resolve_path(self, family: str, bold: bool, italic: bool) -> str|None:
        self._ensure_font_cache()
        family_tokens = family.lower().split()
        candidates = []
        for path in self._system_fonts_cache:
            filename = os.path.basename(path).lower()
            if not all(token in filename for token in family_tokens):
                continue

            remainder = filename

            has_bold = any(s in remainder for s in ["bold", "-b", "_b", ".b", "bd"])
            has_italic = any(s in remainder for s in ["italic", "oblique", "-i", "_i", ".i", "it"])

            if bold == has_bold and italic == has_italic:
                for t in family_tokens: remainder = remainder.replace(t, "", 1)

            for style_marker in ["bold", "italic", "oblique", "bd", "it", "-", "_", " "]:
                remainder = remainder.replace(style_marker, "")

            score = len(remainder)
            candidates.append((score, path))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]


class RichTextRenderer:
    """Handles HTML parsing and drawing text with word-wrapping."""
    def __init__(self, doc: pymupdf.Document, font_manager: FontManager):
        self.doc = doc
        self.fm = font_manager
        self.margin = 72
        self.page_width = 595
        self.page_height = 842
        self.y = self.margin
        self.x = self.margin
        self.current_page = None
        self._fonts_on_page: set[str] = set()
        self.pdf_toc = []

    def _new_page(self):
        self.current_page = self.doc.new_page()
        self._fonts_on_page = set()
        self.y = self.margin
        self.x = self.margin
        return self.current_page

    def render_html(self, html: str, default_font: str, default_size: float,
                    progress_cb: Callable[[int], None],
                    check_cancel: Callable[[], bool]):
        if not self.current_page: self._new_page()
        soup = BeautifulSoup(html, "html.parser")

        # Identify top-level block elements for progress granular tracking
        nodes = soup.find_all(recursive=False) or [soup]
        total = len(nodes)

        for i, node in enumerate(nodes):
            if check_cancel and check_cancel():
                return False
            self._process_node(node, TextStyle(default_font, default_size))
            if progress_cb:
                progress_cb(int((i / total) * 100))

    def _process_node(self, node, current_style: TextStyle):
        is_block = hasattr(node, 'name') and node.name in ['p', 'h1', 'h2', 'h3', 'div', 'hr']
        new_style = self._derive_style(node, current_style)

        if is_block:
            if node.name in ['h1', 'h2', 'h3']:
                level = 1 if node.name == 'h1' else 2 if node.name == 'h2' else 3
                self.pdf_toc.append([level, node.get_text(), self.doc.page_count])

            if self.x != self.margin:
                self._force_newline(new_style.font_size)
            self.y += new_style.font_size * 0.2

            if node.name == 'hr':
                self._draw_hr()
                return

        if isinstance(node, NavigableString):
            self._draw_text(str(node), new_style)
        elif hasattr(node, 'name') and node.name == 'br':
            self._force_newline(new_style.font_size)
        elif hasattr(node, 'children'):
            for child in node.children:
                self._process_node(child, new_style)

        if is_block:
            self._force_newline(new_style.font_size, extra_spacing=new_style.font_size * 0.5)

    def _derive_style(self, node, base: TextStyle) -> TextStyle:
        if isinstance(node, NavigableString): return base
        raw_style = node.get('style', '').lower().replace(" ", "")

        is_bold = base.bold or node.name in ['b', 'strong', 'h1', 'h2', 'h3'] or "font-weight:bold" in raw_style
        is_italic = base.italic or node.name in ['i', 'em'] or "font-style:italic" in raw_style

        family = base.font_family
        if "font-family:" in raw_style:
            try:
                family = node.get('style').split("font-family:")[1].split(";")[0].split(",")[0].strip("'\" ")
            except: pass

        size = base.font_size
        if node.name == 'h1': size = base.font_size * 2.0
        elif node.name == 'h2': size = base.font_size * 1.5
        elif node.name == 'h3': size = base.font_size * 1.2
        elif "font-size:" in raw_style:
            try:
                val = "".join(c for c in raw_style.split("font-size:")[1].split(";")[0] if c.isdigit() or c == '.')
                size = float(val)
            except: pass

        return TextStyle(family, size, is_bold, is_italic, base.color)

    def _draw_hr(self):
        self.y += 10
        p1 = pymupdf.Point(self.margin, self.y)
        p2 = pymupdf.Point(self.page_width - self.margin, self.y)
        self.current_page.draw_line(p1, p2, color=(0.8, 0.8, 0.8), width=1)
        self.y += 10

    def _force_newline(self, font_size: float, extra_spacing: float = 0.0):
        self.x = self.margin
        self.y += (font_size * 1.4) + extra_spacing
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
        line_buffer = []
        current_line_width = 0
        max_x = self.page_width - self.margin

        for i, word in enumerate(words):
            # Re-add the space we split on
            has_trailing_space = i < (len(words) - 1) or text.endswith(" ")
            word_to_draw = word + (" " if has_trailing_space else "")
            if not word_to_draw: continue
            w_len = font_obj.text_length(word_to_draw, fontsize=style.font_size)

            # Internal wrap (if word exceeds line width)
            if self.x + current_line_width + w_len > max_x:
                if line_buffer:
                    self._render_line_run("".join(line_buffer), style.font_size, font_id, is_faux, font_obj)

                # Use our new force_newline to move down correctly
                self._force_newline(style.font_size)
                if font_id not in self._fonts_on_page:
                    self.current_page.insert_font(fontname=font_id, fontbuffer=font_obj.buffer, set_simple=False)
                    self._fonts_on_page.add(font_id)

                # Since we just wrapped, re-calculate without the leading space
                word_to_draw = word_to_draw.lstrip()
                line_buffer = [word_to_draw]
                current_line_width = font_obj.text_length(word_to_draw, fontsize=style.font_size)
            else:
                # Keep accumulating
                line_buffer.append(word_to_draw)
                current_line_width += w_len

        # Flush remaining text in the buffer
        if line_buffer:
            self._render_line_run("".join(line_buffer), style.font_size, font_id, is_faux, font_obj)

    def _render_line_run(self, text_run: str, size: float, font_alias: str, is_faux: bool, font_obj: pymupdf.Font):
        """Internal helper to actually commit a string to the PDF."""
        # --- FAUX ITALIC LOGIC ---
        insert_pos = pymupdf.Point(self.x, self.y + size)
        morph_data = None

        if is_faux:
            # Apply a skew matrix: Matrix(a, b, c, d, e, f)
            # c = 0.3 creates a ~15 degree slant
            skew_matrix = pymupdf.Matrix(1, 0, 0.3, 1, 0, 0)
            morph_data = (insert_pos, skew_matrix)

        # PyMuPDF insert_text uses the baseline. We adjust y so it doesn't collide with top.
        self.current_page.insert_text(
            insert_pos,
            text_run,
            fontsize=size,
            fontname=font_alias,
            morph=morph_data, # This applies the skew
        )
        self.x += font_obj.text_length(text_run, fontsize=size)

class PDFWorker(QThread):
    """Background worker to handle heavy PDF generation without freezing UI."""
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, path: str, html: str, title: str, author: str, font_family: str, font_size: float, include_toc: bool):
        super().__init__()
        self.path = path
        self.html = html
        self.title = title
        self.author = author
        self.font_family = font_family
        self.font_size = font_size
        self.include_toc = include_toc
        self._is_cancelled = False

    def request_cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            doc = pymupdf.open()
            fm = FontManager()
            renderer = RichTextRenderer(doc, fm)

            # Build standardized header
            #header = f'<div style="text-align: center;"><h1 style="font-size: 28pt;">{self.title}</h1>' \
            #         f'<p style="font-size: 18pt;">{self.author}</p></div><br/><hr/><br/>'
            header = f"""
                <h1 style="text-align: center;">{self.title}</h1>
                <p style="text-align: center; font-size: 16pt;">By {self.author}</p>
                <br/><br/>
                <hr/>
                <br/>
            """

            renderer.render_html(header + self.html, self.font_family, self.font_size,
                                 self.progress.emit, lambda: self._is_cancelled)

            if self._is_cancelled:
                self.finished.emit(False, "Cancelled by user")
                return

            if self.include_toc:
                doc.set_toc(renderer.pdf_toc)

            doc.save(self.path, garbage=3, deflate=True, clean=True)
            self.finished.emit(True, self.path)
        except Exception as e:
            logger.exception("PDF Worker: An error occurred during generation")
            self.finished.emit(False, str(e))
        finally:
            if doc: doc.close()
