"""Configuration loading.

Config is TOML. Every key has a default, so a minimal config only needs the
Google Sheets section. See config.example.toml for the annotated version.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("WEIRDFINDER_CONFIG", "~/.config/weirdfinder/config.toml")
).expanduser()

DEFAULT_STATE_PATH = Path(
    os.environ.get("WEIRDFINDER_STATE", "~/.local/state/weirdfinder/state.db")
).expanduser()


class ConfigError(Exception):
    """Raised when the config file is missing or unusable."""


@dataclass
class SteamConfig:
    enabled: bool = True
    # Each query is a dict of Steam store-search query params. Copy the query
    # string from a store.steampowered.com/search/ URL you like and drop the
    # pairs in here; `tags` takes Steam's numeric tag ids.
    queries: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"term": "analog horror", "sort_by": "Released_DESC"},
            {"term": "surreal", "sort_by": "Released_DESC"},
            {"term": "experimental", "sort_by": "Released_DESC"},
            {"term": "liminal", "sort_by": "Released_DESC"},
            {"term": "psychological horror", "sort_by": "Released_DESC"},
        ]
    )
    pages_per_query: int = 2
    # Fetch the store page for each hit to read its user tags. Costs one extra
    # request per game but user tags are the single best weirdness signal.
    fetch_tags: bool = True
    country: str = "us"
    language: str = "english"


@dataclass
class ItchConfig:
    enabled: bool = True
    # Browse paths relative to https://itch.io/. "newest" is the firehose;
    # "new-and-popular" is gentler.
    browse_paths: list[str] = field(
        default_factory=lambda: [
            "games/newest/tag-horror",
            "games/newest/tag-surreal",
            "games/newest/tag-experimental",
            "games/newest/tag-psychological-horror",
            "games/newest/tag-analog-horror",
            "games/new-and-popular/tag-weird",
        ]
    )
    pages_per_path: int = 2
    # Fetch each game page to read its full tag list and description.
    fetch_details: bool = True


@dataclass
class ScoringConfig:
    weight_obscurity: float = 0.35
    weight_vibe: float = 0.35
    weight_experimental: float = 0.30
    # How the three axes fold into one score.
    #   "best" - obscurity blended with the stronger vibe axis, plus a bonus
    #            for scoring on both. A pure horror find is not marked down
    #            for failing to also be an art game.
    #   "mean" - strict weighted average; a high score needs all three.
    combine: str = "best"
    # Extra credit, in "best" mode, for the weaker of the two vibe axes.
    second_axis_bonus: float = 0.25
    # Review count at which a game counts as fully "known" (obscurity 0).
    popularity_cap: int = 3000
    # Obscurity assigned when a source does not expose a review count.
    unknown_obscurity: float = 0.75
    # Saturation constant: how much matched lexicon weight is needed before a
    # vibe axis approaches 1.0. Lower = easier to max out.
    saturation: float = 6.0
    # Rows below this total score (0-100) never reach the sheet.
    min_score: float = 45.0
    # Case-insensitive substrings that disqualify a game outright.
    exclude_terms: list[str] = field(default_factory=list)


@dataclass
class SheetConfig:
    spreadsheet_id: str = ""
    worksheet: str = "Weird Games"
    credentials: str = "~/.config/weirdfinder/service-account.json"
    # Re-sort the sheet by score after each run. Off by default so your own
    # row ordering survives; use a filter view instead.
    sort_by_score: bool = False


@dataclass
class HttpConfig:
    user_agent: str = (
        "weirdfinder/0.1 (personal game-discovery tool; "
        "https://github.com/peripheralmike/Root-Android-Emulator)"
    )
    timeout: float = 20.0
    # Seconds to wait between requests to the same host.
    delay: float = 1.5
    retries: int = 4
    # How long a cached detail lookup stays fresh.
    cache_ttl_hours: int = 168


@dataclass
class Config:
    steam: SteamConfig = field(default_factory=SteamConfig)
    itch: ItchConfig = field(default_factory=ItchConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    sheet: SheetConfig = field(default_factory=SheetConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    state_path: Path = field(default_factory=lambda: DEFAULT_STATE_PATH)
    # Extra lexicon entries, merged over the built-ins: {"vibe": {"phrase": 2.0}}
    lexicon: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def credentials_path(self) -> Path:
        return Path(self.sheet.credentials).expanduser()


def _build(cls: type, data: dict[str, Any], where: str):
    """Instantiate a config dataclass, rejecting unknown keys loudly.

    A silently ignored typo in an unattended job is a bug you find weeks later.
    """
    known = {f.name for f in cls.__dataclass_fields__.values()}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(
            f"unknown key(s) in [{where}]: {', '.join(unknown)}. "
            f"Valid keys: {', '.join(sorted(known))}"
        )
    return cls(**data)


def load(path: Path | str | None = None) -> Config:
    """Load config from TOML, filling in defaults for anything absent."""
    path = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"no config at {path}. Run `weirdfinder init` to write a starter one."
        )
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    cfg = Config(
        steam=_build(SteamConfig, data.get("steam", {}), "steam"),
        itch=_build(ItchConfig, data.get("itch", {}), "itch"),
        scoring=_build(ScoringConfig, data.get("scoring", {}), "scoring"),
        sheet=_build(SheetConfig, data.get("sheet", {}), "sheet"),
        http=_build(HttpConfig, data.get("http", {}), "http"),
        lexicon=data.get("lexicon", {}),
    )
    if "state_path" in data:
        cfg.state_path = Path(data["state_path"]).expanduser()
    return cfg


def validate(cfg: Config) -> list[str]:
    """Return a list of human-readable problems; empty means good to go."""
    problems: list[str] = []
    if not cfg.sheet.spreadsheet_id:
        problems.append("sheet.spreadsheet_id is empty")
    if not cfg.credentials_path.exists():
        problems.append(f"service account file not found: {cfg.credentials_path}")
    if not (cfg.steam.enabled or cfg.itch.enabled):
        problems.append("both sources are disabled, there is nothing to fetch")
    weights = (
        cfg.scoring.weight_obscurity
        + cfg.scoring.weight_vibe
        + cfg.scoring.weight_experimental
    )
    if weights <= 0:
        problems.append("scoring weights sum to zero")
    if cfg.scoring.saturation <= 0:
        problems.append("scoring.saturation must be > 0")
    if cfg.scoring.popularity_cap <= 0:
        problems.append("scoring.popularity_cap must be > 0")
    if cfg.scoring.combine not in {"best", "mean"}:
        problems.append(
            f"scoring.combine must be 'best' or 'mean', got {cfg.scoring.combine!r}"
        )
    if not 0.0 <= cfg.scoring.second_axis_bonus <= 1.0:
        problems.append("scoring.second_axis_bonus must be between 0 and 1")
    return problems
