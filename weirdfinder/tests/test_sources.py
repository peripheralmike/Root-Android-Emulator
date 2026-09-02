import json

from conftest import fixture  # noqa: F401 - also puts src on sys.path

from weirdfinder.sources import itch, steam


# -- Steam -------------------------------------------------------------------

def test_steam_search_extracts_app_rows():
    rows = steam.parse_search_html(fixture("steam_search.html"))
    ids = [row["appid"] for row in rows]
    assert ids == ["1234560", "998877"]  # the bundle's dupes are collapsed
    assert rows[0]["title"] == "Static Bleed"
    assert rows[0]["released"] == "28 Aug, 2026"
    assert rows[0]["url"] == "https://store.steampowered.com/app/1234560/Static_Bleed/"


def test_steam_search_tolerates_empty_and_junk_html():
    assert steam.parse_search_html("") == []
    assert steam.parse_search_html("<div>nothing here</div>") == []


def test_steam_store_tags_come_out_of_the_tag_modal():
    tags = steam.parse_store_tags(fixture("steam_app_page.html"))
    assert tags == ["Horror", "Psychological Horror", "Surreal", "Analog Horror"]


def test_steam_store_tags_degrade_quietly():
    assert steam.parse_store_tags("<html>no modal</html>") == []
    assert steam.parse_store_tags("InitAppTagModal( 5, [broken json,") == []


def test_steam_details_are_flattened():
    payload = {
        "1234560": {
            "success": True,
            "data": {
                "type": "game",
                "name": "Static Bleed",
                "short_description": "A hallway that should not be that long.",
                "genres": [{"description": "Indie"}, {"description": "Adventure"}],
                "developers": ["vhsghost"],
                "is_free": False,
                "price_overview": {"final_formatted": "$4.99"},
                "release_date": {"coming_soon": False, "date": "28 Aug, 2026"},
                "header_image": "https://cdn/header.jpg",
            },
        }
    }
    details = steam.parse_details(payload, "1234560")
    assert details["title"] == "Static Bleed"
    assert details["genres"] == ["Indie", "Adventure"]
    assert details["price"] == "$4.99"
    assert details["released"] == "28 Aug, 2026"


def test_steam_details_drops_non_games_and_failures():
    dlc = {"7": {"success": True, "data": {"type": "dlc", "name": "Soundtrack"}}}
    assert steam.parse_details(dlc, "7") == {}
    assert steam.parse_details({"7": {"success": False}}, "7") == {}
    assert steam.parse_details({}, "7") == {}
    assert steam.parse_details(None, "7") == {}


def test_steam_free_games_are_labelled_free():
    payload = {"9": {"success": True, "data": {"type": "game", "name": "Free Thing", "is_free": True}}}
    assert steam.parse_details(payload, "9")["price"] == "Free"


def test_steam_reviews_summary():
    payload = {"query_summary": {"total_reviews": 40, "total_positive": 34}}
    assert steam.parse_reviews(payload) == (40, 85.0)


def test_steam_reviews_handles_zero_and_missing():
    assert steam.parse_reviews({"query_summary": {"total_reviews": 0, "total_positive": 0}}) == (0, None)
    assert steam.parse_reviews({}) == (None, None)
    assert steam.parse_reviews({"query_summary": {}}) == (None, None)


# -- itch.io -----------------------------------------------------------------

def test_itch_browse_parses_game_cells():
    games = itch.parse_browse_html(fixture("itch_browse.html"))
    assert len(games) == 2

    first = games[0]
    assert first.source == "itch"
    assert first.source_id == "3344556"
    assert first.title == "TAPE NINE"
    assert first.url == "https://vhsghost.itch.io/tape-nine"  # tracking param stripped
    assert first.author == "vhsghost"
    assert first.price == "$2.00"
    assert "Interactive Fiction" in first.tags
    assert "Windows" in first.tags
    assert first.rating == 90.0  # 4.5 / 5
    assert first.image == "https://img.itch.zone/abc/original/xyz.png"


def test_itch_cell_without_price_or_rating_still_parses():
    second = itch.parse_browse_html(fixture("itch_browse.html"))[1]
    assert second.title == "soft machine"
    assert second.price == "Free / PWYW"
    assert second.rating is None
    assert second.popularity is None  # itch exposes no review count


def test_itch_browse_tolerates_empty_html():
    assert itch.parse_browse_html("") == []
    assert itch.parse_browse_html("<div class='game_cell'></div>") == []


def test_itch_game_page_yields_tags_and_full_blurb():
    detail = itch.parse_game_page(fixture("itch_game_page.html"))
    assert "Analog Horror" in detail["tags"]
    assert "PSX" in detail["tags"]
    assert detail["tags"] == list(dict.fromkeys(detail["tags"]))  # de-duplicated
    assert detail["description"].startswith("A short experimental piece")


def test_itch_game_page_degrades_on_junk():
    detail = itch.parse_game_page("<html></html>")
    assert detail == {"tags": [], "description": ""}


# -- source plumbing ---------------------------------------------------------

class FakeClient:
    """Records requests and replays canned responses keyed by URL substring."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _match(self, url):
        for needle, value in self.routes.items():
            if needle in url:
                return value
        raise AssertionError(f"unexpected request to {url}")

    def get(self, url, params=None):
        self.calls.append(url)
        value = self._match(url)

        class Response:
            text = value if isinstance(value, str) else json.dumps(value)

            @staticmethod
            def json():
                if isinstance(value, str):
                    raise ValueError("not json")
                return value

        return Response()

    def get_json(self, url, params=None):
        self.calls.append(url)
        return self._match(url)

    def get_text(self, url, params=None):
        self.calls.append(url)
        return self._match(url)


def test_itch_collect_merges_tags_when_a_game_appears_in_two_feeds():
    from weirdfinder.config import ItchConfig

    client = FakeClient({"itch.io/games": {"content": fixture("itch_browse.html")}})
    cfg = ItchConfig(
        browse_paths=["games/newest/tag-horror", "games/newest/tag-surreal"],
        pages_per_path=1,
        fetch_details=False,
    )
    games = itch.ItchSource(client, cfg).collect()
    # Same two games from both feeds, de-duplicated by key.
    assert len(games) == 2


def test_itch_collect_falls_back_when_the_json_wrapper_is_absent():
    from weirdfinder.config import ItchConfig

    client = FakeClient({"itch.io/games": fixture("itch_browse.html")})
    cfg = ItchConfig(browse_paths=["games/newest/tag-horror"], pages_per_path=1, fetch_details=False)
    assert len(itch.ItchSource(client, cfg).collect()) == 2


def test_itch_detail_fetch_enriches_tags_and_description():
    from weirdfinder.config import ItchConfig

    client = FakeClient(
        {
            "itch.io/games": {"content": fixture("itch_browse.html")},
            "vhsghost.itch.io": fixture("itch_game_page.html"),
            "oddbird.itch.io": "<html></html>",
        }
    )
    cfg = ItchConfig(browse_paths=["games/newest/tag-horror"], pages_per_path=1, fetch_details=True)
    games = itch.ItchSource(client, cfg).collect()
    tape = next(g for g in games if g.source_id == "3344556")
    assert "Analog Horror" in tape.tags
    assert "Interactive Fiction" in tape.tags  # browse-cell tags kept too
    assert tape.description.startswith("A short experimental piece")


def test_disabled_sources_make_no_requests():
    from weirdfinder.config import ItchConfig, SteamConfig

    client = FakeClient({})
    assert itch.ItchSource(client, ItchConfig(enabled=False)).collect() == []
    assert steam.SteamSource(client, SteamConfig(enabled=False)).collect() == []
    assert client.calls == []


def test_steam_collect_end_to_end_against_canned_responses():
    from weirdfinder.config import SteamConfig

    client = FakeClient(
        {
            "/search/results": {"results_html": fixture("steam_search.html")},
            "/api/appdetails": {
                "1234560": {
                    "success": True,
                    "data": {
                        "type": "game",
                        "name": "Static Bleed",
                        "short_description": "A hallway.",
                        "genres": [{"description": "Indie"}],
                        "developers": ["vhsghost"],
                        "is_free": True,
                        "release_date": {"date": "28 Aug, 2026"},
                    },
                }
            },
            "/appreviews/": {"query_summary": {"total_reviews": 6, "total_positive": 6}},
            "/app/": fixture("steam_app_page.html"),
        }
    )
    cfg = SteamConfig(queries=[{"term": "surreal"}], pages_per_query=1, fetch_tags=True)
    games = steam.SteamSource(client, cfg).collect()

    # appdetails only knows 1234560; 998877 comes back empty and is dropped.
    assert len(games) == 1
    game = games[0]
    assert game.key == "steam:1234560"
    assert game.popularity == 6
    assert game.rating == 100.0
    assert game.price == "Free"
    assert "Analog Horror" in game.tags  # user tags merged in
    assert "Indie" in game.tags  # genres kept
