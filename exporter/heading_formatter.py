# exporter/heading_formatter.py
from typing import Dict, Optional


class HeadingFormatter:
    """Shared utility for formatting headings with numbering support."""

    @staticmethod
    def format_heading(
        template: str,
        title: str,
        number: int = 1,
        numbering_index: int = 0
    ) -> str:
        """
        Formats a heading template with title and numbering.
        
        Args:
            template: e.g. "Chapter {num}: {title}"
            title: The heading title
            number: The numeric position (1, 2, ...)
            numbering_index: 0=Arabic, 1=Roman, 2=Kanji
        """
        result = template.replace("{title}", title)

        if numbering_index == 1:  # Roman
            roman = HeadingFormatter._to_roman(number)
            result = result.replace("{num}", roman).replace("{roman}", roman)
        elif numbering_index == 2:  # Kanji
            kanji = HeadingFormatter._to_kanji(number)
            result = result.replace("{num}", kanji).replace("{kanji}", kanji)
        else:  # Arabic
            result = result.replace("{num}", str(number))

        # Replace any leftover placeholders
        result = result.replace("{roman}", HeadingFormatter._to_roman(number))
        result = result.replace("{kanji}", HeadingFormatter._to_kanji(number))

        return result

    @staticmethod
    def _to_roman(num: int) -> str:
        """Convert integer to Roman numeral."""
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        syb = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
        roman = ''
        i = 0
        while num > 0:
            for _ in range(num // val[i]):
                roman += syb[i]
                num -= val[i]
            i += 1
        return roman

    @staticmethod
    def _to_kanji(num: int) -> str:
        kanji_map = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        return kanji_map[min(num-1, len(kanji_map)-1)] if num <= 10 else str(num)


    @staticmethod
    def get_sample_html(heading_fmt, number: int, title: str) -> str:
        """Convenience for preview (can be extended with rich formatting later)."""
        text = HeadingFormatter.format_heading(
            heading_fmt.get_heading_text() if hasattr(heading_fmt, 'get_heading_text') else str(heading_fmt),
            title,
            number,
            heading_fmt.get_numbering_index() if hasattr(heading_fmt, 'get_numbering_index') else 0
        )
        return text  # You can wrap with <span style=...> later

class HeadingFormat:
    """Simple data class to hold rich formatting for a heading level."""
    def __init__(self):
        self.bold: bool = False
        self.italic: bool = False
        self.underline: bool = False
        self.color: Optional[str] = None
        self.font_family: str = "Georgia"
        self.font_size: int = 14
        self.template: str = ""
        self.numbering_index = 0 # 0=arabic, 1=roman, 2=kanji

    def to_dict(self) -> Dict:
        return {
            "bold": self.bold,
            "italic": self.italic,
            "underline": self.underline,
            "color": self.color,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "template": self.template,
            "numbering_index": self.numbering_index,
        }

    @classmethod
    def from_dict(cls, data: dict):
        fmt = cls()
        for k, v in data.items():
            if hasattr(fmt, k):
                setattr(fmt, k, v)
        return fmt
    
    def get_numbering_index(self) -> int:
        return self.numbering_index