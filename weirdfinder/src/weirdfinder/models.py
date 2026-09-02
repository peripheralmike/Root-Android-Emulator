"""Core data types shared between sources, scoring and the sheet writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Game:
    """A single candidate game, normalised across sources."""

    source: str  # "steam" | "itch"
    source_id: str
    title: str
    url: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    price: str = ""
    released: str = ""
    # Number of reviews / ratings. None means "the source does not tell us",
    # which is different from 0 ("nobody has reviewed it").
    popularity: int | None = None
    # 0-100. Steam positive%, itch stars rescaled. None when unknown.
    rating: float | None = None
    image: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity used to de-duplicate rows across runs."""
        return f"{self.source}:{self.source_id}"

    def haystack(self) -> tuple[str, list[str]]:
        """Free text and tag list used by the scorer."""
        return f"{self.title}\n{self.description}", list(self.tags)


@dataclass
class Scored:
    """A game plus its weirdness breakdown."""

    game: Game
    obscurity: float = 0.0
    vibe: float = 0.0
    experimental: float = 0.0
    total: float = 0.0
    matched: list[str] = field(default_factory=list)
