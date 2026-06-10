
# Try to import numbering libraries, provide fallbacks if missing
try:
    import roman
except ImportError:
    roman = None

try:
    import kanjize
except ImportError:
    kanjize = None


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
            roman = NumberingUtility.to_roman(number)
            result = result.replace("{num}", roman).replace("{roman}", roman)
        elif numbering_index == 2:  # Kanji
            kanji = NumberingUtility.to_kanji(number)
            result = result.replace("{num}", kanji).replace("{kanji}", kanji)
        else:  # Arabic
            result = result.replace("{num}", str(number))

        # Replace any leftover placeholders
        result = result.replace("{roman}", NumberingUtility.to_roman(number))
        result = result.replace("{kanji}", NumberingUtility.to_kanji(number))

        return result

class HeadingFormat:
    """Simple data class to hold rich formatting for a heading level."""
    def __init__(self):
        self.bold: bool = False
        self.italic: bool = False
        self.underline: bool = False
        self.color: str | None = None
        self.font_family: str = "Georgia"
        self.font_size: int = 14
        self.template: str = ""
        self.numbering_index = 0 # 0=arabic, 1=roman, 2=kanji

    def to_dict(self) -> dict:
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

class NumberingUtility:
    """Handles conversion of integers to various book numbering styles."""
    
    @staticmethod
    def to_roman(n: int) -> str:
        if roman:
            try: return roman.toRoman(n)
            except: pass
        # Basic fallback for I-X
        fallback = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
        return fallback[n] if n < len(fallback) else str(n)

    @staticmethod
    def to_kanji(n: int) -> str:
        if kanjize:
            try: return kanjize.number2kanji(n)
            except: pass
        # Basic fallback
        fallback = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        return fallback[n] if n < len(fallback) else str(n)

    @staticmethod
    def to_word(n: int) -> str:
        # Simple word fallback for common chapter counts
        words = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"]
        return words[n] if n < len(words) else str(n)
