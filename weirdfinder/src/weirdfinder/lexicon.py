"""Weighted phrase lists for the two vibe axes.

Weights are rough "how strongly does this phrase mean weird" values, not
probabilities. A phrase matched in a tag counts for more than one matched in
prose (see scoring.TAG_MULTIPLIER) because tags are curated and prose is not.

Tune these freely -- they are the main knob on what lands in your sheet. You
can add or override entries from config without editing this file:

    [lexicon.vibe]
    "kitchen sink horror" = 3.0
"""

from __future__ import annotations

# Surreal / horror / analog axis.
VIBE: dict[str, float] = {
    "analog horror": 3.5,
    "found footage": 2.8,
    "vhs": 2.4,
    "liminal space": 3.5,
    "liminal": 3.0,
    "backrooms": 2.8,
    "dreamcore": 3.2,
    "weirdcore": 3.4,
    "surreal": 3.0,
    "surrealist": 3.0,
    "dreamlike": 2.6,
    "fever dream": 3.0,
    "uncanny": 2.6,
    "unsettling": 2.4,
    "eerie": 2.2,
    "dread": 1.8,
    "ps1": 2.2,
    "psx": 2.2,
    "lo-fi": 1.6,
    "low poly": 1.2,
    "retro horror": 2.4,
    "psychological horror": 2.6,
    "cosmic horror": 2.4,
    "eldritch": 2.2,
    "body horror": 2.8,
    "glitch": 2.0,
    "hallucination": 2.2,
    "nightmare": 1.8,
    "haunting": 1.6,
    "disturbing": 1.8,
    "ominous": 1.5,
    "cursed": 1.6,
    "occult": 1.8,
    "ritual": 1.4,
    "horror": 1.0,
    "creepy": 1.2,
    "atmospheric": 1.0,
    "paranormal": 1.4,
    "cryptid": 2.0,
    "folk horror": 2.6,
    "mockumentary": 2.2,
    "static": 1.0,
    "vaporwave": 2.4,
}

# Experimental / art-game axis.
EXPERIMENTAL: dict[str, float] = {
    "experimental": 3.4,
    "art game": 3.4,
    "altgame": 3.2,
    "anti-game": 3.2,
    "avant-garde": 3.2,
    "avant garde": 3.2,
    "dada": 3.0,
    "abstract": 2.2,
    "non-game": 2.6,
    "unconventional": 2.6,
    "bizarre": 2.6,
    "absurd": 2.4,
    "weird": 2.6,
    "strange": 1.8,
    "surreal comedy": 2.8,
    "generative": 2.0,
    "procedural art": 2.4,
    "glitch art": 2.8,
    "interactive fiction": 1.4,
    "walking simulator": 1.6,
    "immersive sim": 1.2,
    "minimalist": 1.2,
    "meta": 1.4,
    "fourth wall": 2.2,
    "no combat": 1.2,
    "short": 0.8,
    "experimental narrative": 3.0,
    "stream of consciousness": 2.8,
    "hypertext": 2.2,
    "toy": 1.4,
    "sandbox toy": 1.8,
    "unique": 1.0,
    "oddity": 2.4,
    "cursed game": 2.6,
}

AXES = {"vibe": VIBE, "experimental": EXPERIMENTAL}


def merged(overrides: dict[str, dict[str, float]] | None) -> dict[str, dict[str, float]]:
    """Built-in lexicon with config overrides layered on top.

    A phrase set to 0 (or below) in config is dropped, which is how you mute a
    built-in entry that keeps producing false positives.
    """
    result = {axis: dict(entries) for axis, entries in AXES.items()}
    for axis, entries in (overrides or {}).items():
        if axis not in result:
            raise KeyError(
                f"unknown lexicon axis '{axis}'; expected one of {sorted(result)}"
            )
        for phrase, weight in entries.items():
            phrase = phrase.strip().lower()
            if weight > 0:
                result[axis][phrase] = float(weight)
            else:
                result[axis].pop(phrase, None)
    return result
