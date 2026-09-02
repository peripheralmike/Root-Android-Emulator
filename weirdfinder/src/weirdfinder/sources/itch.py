"""itch.io adapter.

itch's browse pages accept ?format=json, which returns the same game-cell
markup wrapped in {"content": ..., "num_items": N}. We ask for that and fall
back to the raw page when the shape is not what we expect.

itch exposes no review count, so obscurity for these falls back to
scoring.unknown_obscurity -- which is fine, because "newest" on itch is
almost by definition the long tail.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..config import ItchConfig
from ..http import Client, FetchError
from ..models import Game

log = logging.getLogger(__name__)

BASE = "https://itch.io/"
_RATING = re.compile(r"([0-9.]+)\s*(?:/|out of)\s*5")


def _cell_text(cell, selector: str) -> str:
    node = cell.select_one(selector)
    return node.get_text(" ", strip=True) if node else ""


def parse_rating(cell) -> float | None:
    """itch shows stars as a title like 'Average rating: 4.5 / 5'. Rescale to 0-100."""
    node = cell.select_one("[title*='rating'], [title*='Rating']")
    if not node:
        return None
    match = _RATING.search(node.get("title", ""))
    if not match:
        return None
    try:
        return round(float(match.group(1)) / 5.0 * 100, 1)
    except ValueError:
        return None


def parse_browse_html(html: str) -> list[Game]:
    """Turn a page of itch game cells into Games."""
    soup = BeautifulSoup(html, "html.parser")
    games: list[Game] = []

    for cell in soup.select("div.game_cell"):
        game_id = (cell.get("data-game_id") or "").strip()
        link = cell.select_one("a.title.game_link") or cell.select_one("a.game_link")
        if not link:
            continue
        url = (link.get("href") or "").split("?")[0]
        if not game_id:
            # No id attribute: fall back to the URL, which is also stable.
            game_id = url.rsplit("/", 1)[-1] or url
        if not url:
            continue

        title = link.get_text(" ", strip=True)
        genre = _cell_text(cell, "div.game_genre")
        platforms = _cell_text(cell, "div.game_platform")
        tags = [part.strip() for part in genre.split(",") if part.strip()]
        if platforms:
            tags.extend(part.strip() for part in platforms.split(",") if part.strip())

        thumb = cell.select_one("img[data-lazy_src], img[src]")
        image = ""
        if thumb:
            image = thumb.get("data-lazy_src") or thumb.get("src") or ""

        games.append(
            Game(
                source="itch",
                source_id=game_id,
                title=title,
                url=url,
                description=_cell_text(cell, "div.game_text"),
                tags=tags,
                author=_cell_text(cell, "div.game_author"),
                price=_cell_text(cell, "div.price_value") or "Free / PWYW",
                rating=parse_rating(cell),
                image=image,
            )
        )
    return games


def parse_game_page(html: str) -> dict:
    """Read the tag list and full blurb off an itch game page."""
    soup = BeautifulSoup(html, "html.parser")
    tags: list[str] = []

    # The info panel is a table of label/value rows; the tag row links to
    # /tag-<name> URLs, which is a more reliable marker than the row order.
    for anchor in soup.select("a[href*='/tag-']"):
        text = anchor.get_text(" ", strip=True)
        if text and text not in tags:
            tags.append(text)

    blurb = ""
    meta = soup.select_one("meta[name='description'], meta[property='og:description']")
    if meta and meta.get("content"):
        blurb = meta["content"].strip()
    if not blurb:
        body = soup.select_one("div.formatted_description")
        if body:
            blurb = body.get_text(" ", strip=True)[:600]

    return {"tags": tags, "description": blurb}


class ItchSource:
    """Discovery + optional per-game enrichment for itch.io."""

    name = "itch"

    def __init__(self, client: Client, cfg: ItchConfig, cache=None) -> None:
        self.client = client
        self.cfg = cfg
        self.cache = cache

    def _browse_page(self, path: str, page: int) -> list[Game]:
        url = BASE + path.lstrip("/")
        payload = self.client.get(url, params={"page": str(page), "format": "json"})
        try:
            data = payload.json()
        except ValueError:
            # Not JSON: itch served the page itself, which parses just as well.
            return parse_browse_html(payload.text)
        html = data.get("content") if isinstance(data, dict) else None
        return parse_browse_html(html or "")

    def _cached(self, key: str, fetch):
        if self.cache is None:
            return fetch()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = fetch()
        self.cache.put(key, value)
        return value

    def _enrich(self, game: Game) -> Game:
        try:
            detail = self._cached(
                f"itch:detail:{game.source_id}",
                lambda: parse_game_page(self.client.get_text(game.url)),
            )
        except FetchError as exc:
            log.warning("itch detail %s failed: %s", game.url, exc)
            return game

        for tag in detail.get("tags") or []:
            if tag not in game.tags:
                game.tags.append(tag)
        # The browse cell blurb is truncated; the page one is the real thing.
        if detail.get("description"):
            game.description = detail["description"]
        return game

    def collect(self) -> list[Game]:
        """Walk every configured browse path and return de-duplicated games."""
        if not self.cfg.enabled:
            return []

        found: dict[str, Game] = {}
        for path in self.cfg.browse_paths:
            for page in range(1, max(1, self.cfg.pages_per_path) + 1):
                try:
                    batch = self._browse_page(path, page)
                except FetchError as exc:
                    log.warning("itch browse %s page %d failed: %s", path, page, exc)
                    break
                if not batch:
                    break
                for game in batch:
                    existing = found.get(game.key)
                    if existing is None:
                        found[game.key] = game
                    else:
                        # Same game via two tag feeds: keep both tag sets, they
                        # are exactly the signal we are scoring on.
                        for tag in game.tags:
                            if tag not in existing.tags:
                                existing.tags.append(tag)
        log.info("itch: %d unique games from browse", len(found))

        games = list(found.values())
        if self.cfg.fetch_details:
            games = [self._enrich(game) for game in games]
        return games
