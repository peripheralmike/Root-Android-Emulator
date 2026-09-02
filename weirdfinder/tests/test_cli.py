"""End-to-end run of the pipeline with the network stubbed out."""

import json

from conftest import fixture  # noqa: F401 - also puts src on sys.path

from weirdfinder import cli


class StubClient:
    """Stands in for http.Client, replaying fixtures by URL substring."""

    def __init__(self, *args, **kwargs):
        self.routes = {
            "/search/results": {"results_html": fixture("steam_search.html")},
            "/api/appdetails": {
                "1234560": {
                    "success": True,
                    "data": {
                        "type": "game",
                        "name": "Static Bleed",
                        "short_description": "Analog horror in a hallway that keeps going.",
                        "genres": [{"description": "Indie"}],
                        "developers": ["vhsghost"],
                        "is_free": True,
                        "release_date": {"date": "28 Aug, 2026"},
                    },
                }
            },
            "/appreviews/": {"query_summary": {"total_reviews": 4, "total_positive": 4}},
            "store.steampowered.com/app/": fixture("steam_app_page.html"),
            "itch.io/games": {"content": fixture("itch_browse.html")},
            "vhsghost.itch.io": fixture("itch_game_page.html"),
            "oddbird.itch.io": "<html></html>",
        }

    def _match(self, url):
        for needle, value in self.routes.items():
            if needle in url:
                return value
        raise AssertionError(f"unexpected request to {url}")

    def get(self, url, params=None):
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
        return self._match(url)

    def get_text(self, url, params=None):
        return self._match(url)


def make_config(tmp_path) -> str:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
state_path = "{tmp_path / 'state.db'}"

[sheet]
spreadsheet_id = "fake"

[steam]
queries = [ {{ term = "analog horror" }} ]
pages_per_query = 1

[itch]
browse_paths = [ "games/newest/tag-horror" ]
pages_per_path = 1
"""
    )
    return str(path)


def test_dry_run_scores_both_sources_without_touching_the_sheet(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Client", StubClient)
    monkeypatch.setattr(
        cli.SheetWriter, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote!"))
    )
    dump = tmp_path / "out.json"

    code = cli.main(
        ["-c", make_config(tmp_path), "run", "--dry-run", "--json", str(dump)]
    )
    assert code == 0

    out = capsys.readouterr().out
    assert "Static Bleed" in out  # from Steam
    assert "TAPE NINE" in out  # from itch
    assert "dry run" in out

    payload = json.loads(dump.read_text())
    sources = {entry["source"] for entry in payload}
    assert sources == {"steam", "itch"}
    assert all(entry["score"] >= 45.0 for entry in payload)


def test_min_score_override_gates_the_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Client", StubClient)
    cli.main(["-c", make_config(tmp_path), "run", "--dry-run", "--min-score", "99.9"])
    assert "0 rows would be synced" in capsys.readouterr().out


def test_first_seen_is_preserved_but_last_seen_moves(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Client", StubClient)
    config = make_config(tmp_path)
    first_dump = tmp_path / "a.json"
    second_dump = tmp_path / "b.json"

    cli.main(["-c", config, "run", "--dry-run", "--json", str(first_dump)])
    cli.main(["-c", config, "run", "--dry-run", "--json", str(second_dump)])

    # The second run must find the same games already known, not treat them as new.
    from weirdfinder.state import State

    state = State(tmp_path / "state.db")
    keys = [entry["source"] + ":" + entry["source_id"] for entry in json.loads(first_dump.read_text())]
    assert keys
    assert all(not state.is_new(key) for key in keys)


def test_a_failing_source_does_not_lose_the_other_ones_results(tmp_path, monkeypatch, capsys):
    class HalfBrokenClient(StubClient):
        def get_json(self, url, params=None):
            if "steampowered" in url:
                raise RuntimeError("steam is down")
            return self._match(url)

    monkeypatch.setattr(cli, "Client", HalfBrokenClient)
    code = cli.main(["-c", make_config(tmp_path), "run", "--dry-run"])

    assert code == 0
    assert "TAPE NINE" in capsys.readouterr().out  # itch results still land


def test_a_run_that_collects_nothing_leaves_the_sheet_alone(tmp_path, monkeypatch):
    class DeadClient(StubClient):
        def get_json(self, url, params=None):
            raise RuntimeError("everything is down")

        def get(self, url, params=None):
            raise RuntimeError("everything is down")

        def get_text(self, url, params=None):
            raise RuntimeError("everything is down")

    monkeypatch.setattr(cli, "Client", DeadClient)
    monkeypatch.setattr(
        cli.SheetWriter, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote!"))
    )
    assert cli.main(["-c", make_config(tmp_path), "run"]) == 1


def test_init_writes_a_config_that_loads(tmp_path, capsys):
    target = tmp_path / "cfg" / "config.toml"
    assert cli.main(["-c", str(target), "init"]) == 0
    assert target.exists()

    from weirdfinder import config as config_module

    config_module.load(target)  # must round-trip

    # A second init must not silently overwrite a tuned config.
    assert cli.main(["-c", str(target), "init"]) == 1
    assert "already exists" in capsys.readouterr().out


def test_run_refuses_to_start_with_an_invalid_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Client", StubClient)
    path = tmp_path / "config.toml"
    path.write_text('[sheet]\nspreadsheet_id = ""\n')
    assert cli.main(["-c", str(path), "run"]) == 1


def test_explain_works_before_any_config_exists(tmp_path, capsys):
    assert cli.main(["-c", str(tmp_path / "none.toml"), "explain", "Surreal Thing",
                     "-t", "Analog Horror"]) == 0
    assert "total" in capsys.readouterr().out
