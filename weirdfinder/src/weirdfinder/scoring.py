"""Turn a Game into a 0-100 weirdness score across three axes.

Obscurity   - how few people have looked at this yet.
Vibe        - surreal / horror / analog signals.
Experimental- art-game / anti-game signals.

Each axis lands in 0..1, then the three are combined with configurable
weights. Both vibe axes saturate: matching ten horror phrases is not ten
times weirder than matching three, so raw lexicon weight is squashed through
1 - exp(-w / saturation).
"""

from __future__ import annotations

import math
import re
import unicodedata

from .config import ScoringConfig
from .lexicon import merged
from .models import Game, Scored

# A phrase found in a curated tag is worth more than the same phrase in prose.
TAG_MULTIPLIER = 1.6


def normalise(text: str) -> str:
    """Lowercase, strip accents, and collapse punctuation to spaces.

    Padding with spaces lets callers match phrases at string boundaries with a
    plain `in` test without dragging in a regex per phrase.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    # Keep hyphens: "anti-game" and "avant-garde" are lexicon entries.
    text = re.sub(r"[^a-z0-9\-]+", " ", text)
    collapsed = re.sub(r"\s+", " ", text).strip()
    return f" {collapsed} "


def obscurity_score(popularity: int | None, cfg: ScoringConfig) -> float:
    """1.0 = nobody has reviewed it, 0.0 = at or past the popularity cap."""
    if popularity is None:
        return _clamp(cfg.unknown_obscurity)
    if popularity <= 0:
        return 1.0
    ratio = math.log1p(popularity) / math.log1p(cfg.popularity_cap)
    return _clamp(1.0 - ratio)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _axis_score(
    text: str,
    tags: list[str],
    phrases: dict[str, float],
    cfg: ScoringConfig,
) -> tuple[float, list[str]]:
    """Sum matched phrase weights, then squash into 0..1."""
    hay_text = normalise(text)
    hay_tags = [normalise(tag) for tag in tags]

    total = 0.0
    matched: list[str] = []
    for phrase, weight in phrases.items():
        needle = f" {normalise(phrase).strip()} "
        in_tag = any(needle in tag for tag in hay_tags)
        in_text = needle in hay_text
        if not (in_tag or in_text):
            continue
        # A phrase counts once, at its best multiplier -- not once per field.
        total += weight * (TAG_MULTIPLIER if in_tag else 1.0)
        matched.append(phrase)

    score = 1.0 - math.exp(-total / cfg.saturation)
    # Longest phrases first: "psychological horror" is more informative than
    # "horror" when explaining why something scored.
    matched.sort(key=lambda p: (-len(p), p))
    return _clamp(score), matched


def excluded(game: Game, cfg: ScoringConfig) -> str | None:
    """Return the exclude term that disqualifies this game, if any."""
    if not cfg.exclude_terms:
        return None
    hay = normalise(f"{game.title} {game.description} {' '.join(game.tags)}")
    for term in cfg.exclude_terms:
        if normalise(term).strip() in hay:
            return term
    return None


def combine(obscurity: float, vibe: float, experimental: float, cfg: ScoringConfig) -> float:
    """Fold the three axes into one 0-100 score.

    Two modes, because "weird" is not one thing:

    "best" (default) treats the vibe and experimental axes as alternative
    flavours of weird rather than requirements to stack. A genuinely great
    analog-horror find should not be marked down for failing to also be an
    art game -- but scoring on both earns a bonus, since that combination is
    exactly the sweet spot. Each axis is first scaled by its own weight
    relative to the larger of the two, so the weights still express which
    flavour you care about more.

    "mean" is the strict reading: a plain weighted average, where a high
    score requires all three axes at once.
    """
    w_obs = cfg.weight_obscurity
    w_vibe = cfg.weight_vibe
    w_exp = cfg.weight_experimental

    if cfg.combine == "mean":
        denom = (w_obs + w_vibe + w_exp) or 1.0
        return _clamp(
            (obscurity * w_obs + vibe * w_vibe + experimental * w_exp) / denom
        ) * 100

    top = max(w_vibe, w_exp) or 1.0
    scaled_vibe = vibe * (w_vibe / top)
    scaled_exp = experimental * (w_exp / top)
    flavour = _clamp(
        max(scaled_vibe, scaled_exp)
        + cfg.second_axis_bonus * min(scaled_vibe, scaled_exp)
    )

    w_flavour = w_vibe + w_exp
    denom = (w_obs + w_flavour) or 1.0
    return _clamp((obscurity * w_obs + flavour * w_flavour) / denom) * 100


def score(game: Game, cfg: ScoringConfig, lexicon_overrides=None) -> Scored:
    """Score one game. Pure function -- no I/O, easy to unit test."""
    phrases = merged(lexicon_overrides)
    text, tags = game.haystack()

    vibe, vibe_hits = _axis_score(text, tags, phrases["vibe"], cfg)
    exp, exp_hits = _axis_score(text, tags, phrases["experimental"], cfg)
    obs = obscurity_score(game.popularity, cfg)

    total = combine(obs, vibe, exp, cfg)

    return Scored(
        game=game,
        obscurity=round(obs, 4),
        vibe=round(vibe, 4),
        experimental=round(exp, 4),
        total=round(total, 1),
        matched=vibe_hits + [h for h in exp_hits if h not in vibe_hits],
    )


def score_all(games, cfg: ScoringConfig, lexicon_overrides=None) -> list[Scored]:
    """Score, drop excluded games, and sort best-first."""
    out = [
        score(game, cfg, lexicon_overrides)
        for game in games
        if excluded(game, cfg) is None
    ]
    out.sort(key=lambda s: s.total, reverse=True)
    return out
