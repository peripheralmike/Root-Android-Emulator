"""Steam store adapter.

Three public surfaces are used, all of them the same ones a browser hits:

  /search/results/          the store search, for discovery
  /api/appdetails           per-app metadata (name, blurb, price, release)
  /appreviews/<id>          review totals, which drive the obscurity axis

Plus, optionally, the store page itself, because Steam's *user* tags are the
single most useful weirdness signal and they only exist in that HTML.

Every parser here is written against possibly-absent fields: Steam changes
this markup without warning and an unattended job must degrade, not crash.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from ..config import SteamConfig
from ..http import Client, FetchError
from ..models import Game

log = logging.getLogger(__name__)

SEARCH_URL = "https://store.steampowered.com/search/results/"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
APP_URL = "https://store.steampowered.com/app/{appid}/"

# Steam's own "this is a game, not a DLC/soundtrack/video" search filter.
GAMES_ONLY = {"category1": "998", "ignore_preferences": "1"}

_APPID_IN_URL = re.compile(r"/app/(\d+)")
_TAG_MODAL = re.compile(r"InitAppTagModal\(\s*\d+\s*,\s*(\[.*?\])\s*,", re.S)


def parse_search_html(html: str) -> list[dict[str, str]]:
    """Pull app rows out of a search results fragment.

    Returns dicts rather than Games because a search row alone is too thin to
    score -- it gets enriched below.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.select("a.search_result_row"):
        appid = anchor.get("data-ds-appid") or ""
        if not appid:
            match = _APPID_IN_URL.search(anchor.get("href", ""))
            appid = match.group(1) if match else ""
        # Bundles carry comma-joined appid lists; take the first real app.
        appid = appid.split(",")[0].strip()
        if not appid or appid in seen:
            continue
        seen.add(appid)

        def text_of(selector: str) -> str:
            node = anchor.select_one(selector)
            return node.get_text(" ", strip=True) if node else ""

        rows.append(
            {
                "appid": appid,
                "title": text_of("span.title"),
                "released": text_of("div.search_released"),
                "url": (anchor.get("href") or APP_URL.format(appid=appid)).split("?")[0],
            }
        )
    return rows


def parse_store_tags(html: str) -> list[str]:
    """Extract user tags from a store page's InitAppTagModal payload."""
    match = _TAG_MODAL.search(html)
    if not match:
        return []
    try:
        entries = json.loads(match.group(1))
    except ValueError:
        log.debug("could not decode tag payload")
        return []
    return [
        str(entry["name"]).strip()
        for entry in entries
        if isinstance(entry, dict) and entry.get("name")
    ]


def parse_details(payload: dict, appid: str) -> dict:
    """Normalise the /api/appdetails envelope into a flat dict."""
    entry = (payload or {}).get(str(appid)) or {}
    if not entry.get("success"):
        return {}
    data = entry.get("data") or {}
    if data.get("type") and data["type"] != "game":
        return {}

    price = "Free" if data.get("is_free") else ""
    overview = data.get("price_overview") or {}
    if not price:
        price = overview.get("final_formatted") or ""

    release = data.get("release_date") or {}
    return {
        "title": data.get("name") or "",
        "description": data.get("short_description") or "",
        "genres": [g["description"] for g in data.get("genres") or [] if g.get("description")],
        "developers": data.get("developers") or [],
        "price": price,
        "released": release.get("date") or "",
        "coming_soon": bool(release.get("coming_soon")),
        "image": data.get("header_image") or "",
    }


def parse_reviews(payload: dict) -> tuple[int | None, float | None]:
    """Return (total reviews, positive percent) from the appreviews summary."""
    summary = (payload or {}).get("query_summary") or {}
    total = summary.get("total_reviews")
    positive = summary.get("total_positive")
    if not isinstance(total, int):
        return None, None
    pct = round(100.0 * positive / total, 1) if total and isinstance(positive, int) else None
    return total, pct


class SteamSource:
    """Discovery + enrichment for the Steam store."""

    name = "steam"

    def __init__(self, client: Client, cfg: SteamConfig, cache=None) -> None:
        self.client = client
        self.cfg = cfg
        self.cache = cache

    def _search_page(self, query: dict[str, str], page: int) -> list[dict[str, str]]:
        params = {
            **GAMES_ONLY,
            **query,
            "page": str(page),
            "infinite": "1",
            "cc": self.cfg.country,
            "l": self.cfg.language,
        }
        payload = self.client.get_json(SEARCH_URL, params=params)
        html = (payload or {}).get("results_html") or ""
        return parse_search_html(html)

    def _cached(self, key: str, fetch):
        """Look through the detail cache when one is wired up."""
        if self.cache is None:
            return fetch()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = fetch()
        self.cache.put(key, value)
        return value

    def _enrich(self, row: dict[str, str]) -> Game | None:
        appid = row["appid"]
        try:
            details = self._cached(
                f"steam:details:{appid}",
                lambda: parse_details(
                    self.client.get_json(
                        DETAILS_URL,
                        params={
                            "appids": appid,
                            "cc": self.cfg.country,
                            "l": self.cfg.language,
                        },
                    ),
                    appid,
                ),
            )
        except FetchError as exc:
            log.warning("steam details %s failed: %s", appid, exc)
            details = {}

        # An empty dict means "not a game" (DLC, soundtrack) or a dead appid.
        if not details:
            return None

        try:
            reviews = self._cached(
                f"steam:reviews:{appid}",
                lambda: parse_reviews(
                    self.client.get_json(
                        REVIEWS_URL.format(appid=appid),
                        params={
                            "json": "1",
                            "num_per_page": "0",
                            "language": "all",
                            "purchase_type": "all",
                        },
                    )
                ),
            )
        except FetchError as exc:
            log.warning("steam reviews %s failed: %s", appid, exc)
            reviews = (None, None)
        total_reviews, positive_pct = reviews

        tags: list[str] = list(details.get("genres") or [])
        if self.cfg.fetch_tags:
            try:
                user_tags = self._cached(
                    f"steam:tags:{appid}",
                    lambda: parse_store_tags(
                        self.client.get_text(
                            APP_URL.format(appid=appid),
                            params={"cc": self.cfg.country, "l": self.cfg.language},
                        )
                    ),
                )
            except FetchError as exc:
                log.warning("steam tags %s failed: %s", appid, exc)
                user_tags = []
            for tag in user_tags:
                if tag not in tags:
                    tags.append(tag)

        developers = details.get("developers") or []
        return Game(
            source=self.name,
            source_id=appid,
            title=details.get("title") or row.get("title") or f"App {appid}",
            url=row.get("url") or APP_URL.format(appid=appid),
            description=details.get("description", ""),
            tags=tags,
            author=", ".join(developers),
            price=details.get("price", ""),
            released=details.get("released") or row.get("released", ""),
            popularity=total_reviews,
            rating=positive_pct,
            image=details.get("image", ""),
            raw={"coming_soon": details.get("coming_soon", False)},
        )

    def collect(self) -> list[Game]:
        """Run every configured query and return de-duplicated games."""
        if not self.cfg.enabled:
            return []

        rows: dict[str, dict[str, str]] = {}
        for query in self.cfg.queries:
            for page in range(1, max(1, self.cfg.pages_per_query) + 1):
                try:
                    found = self._search_page(query, page)
                except FetchError as exc:
                    log.warning("steam search %s page %d failed: %s", query, page, exc)
                    break
                if not found:
                    break
                for row in found:
                    rows.setdefault(row["appid"], row)
        log.info("steam: %d unique apps from search", len(rows))

        games: list[Game] = []
        for row in rows.values():
            game = self._enrich(row)
            if game is not None:
                games.append(game)
        log.info("steam: %d games after enrichment", len(games))
        return games
