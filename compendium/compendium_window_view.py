from __future__ import annotations

import enum
from abc import ABC


class Pane(enum.Enum):
    TOOLBAR = enum.auto()
    TREE = enum.auto()
    EDITOR = enum.auto()

class ICompendiumWindowView(ABC):
    """Composition contract: show/hide/switch panes. No PyQt types appear here."""
