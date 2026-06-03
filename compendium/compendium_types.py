"""
TypedDict definitions for the compendium data model.

These types mirror the JSON structure stored in `compendium.json`

The `TypedDict` subclasses are still plain `dict` at runtime, so no conversion is needed
to existing code.
"""

from typing import TypedDict

# ---------------------------------------------------------------------------
# Entry sub-types
# ---------------------------------------------------------------------------

class CompendiumTag(TypedDict):
    """A tag attached to a compendium entry."""

    name: str
    color: str  # hex color code, e.g. "#ff0000"


class CompendiumRelationship(TypedDict):
    """A directed relationship from one entry to another."""

    uuid: str   # uuid of the related entry
    type: str   # relationship type, e.g. "parent", "ally"


# ---------------------------------------------------------------------------
# Entry-level types
# ---------------------------------------------------------------------------

class CompendiumEntry(TypedDict):
    """A single entry inside a compendium category.

    All fields are guaranteed to be present after ``CompendiumManager._load_data``
    has normalised the data (legacy entries missing optional fields are patched
    on load).
    """

    uuid: str
    name: str
    content: str
    details: str
    tags: list[CompendiumTag]
    relationships: list[CompendiumRelationship]
    images: list[str]  # paths to image files on disk


class EntryWithContext(CompendiumEntry):
    """A ``CompendiumEntry`` augmented with the containing category's identity.

    Returned by ``CompendiumManager.find_entries``.
    """

    category_uuid: str
    category_name: str


# ---------------------------------------------------------------------------
# Category-level types
# ---------------------------------------------------------------------------

class CompendiumCategory(TypedDict):
    """A category that groups related compendium entries."""

    uuid: str
    name: str
    entries: list[CompendiumEntry]


class CategorySummary(TypedDict):
    """Lightweight category descriptor (no entries).

    Returned by ``CompendiumManager.list_categories`` and used as the values
    in ``CompendiumManager.find_categories``.
    """

    uuid: str
    name: str


# ---------------------------------------------------------------------------
# Top-level document type
# ---------------------------------------------------------------------------

class CompendiumData(TypedDict):
    """The root object stored in ``compendium.json``."""

    version: int
    categories: list[CompendiumCategory]


# ---------------------------------------------------------------------------
# Convenience / legacy summary types
# ---------------------------------------------------------------------------

class PovCharacter(TypedDict):
    """Minimal character descriptor used by the POV selector.

    Returned by ``CompendiumManager.list_pov_characters``.
    """

    uuid: str
    name: str

