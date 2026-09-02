import pytest
from conftest import *  # noqa: F401,F403 - puts src on sys.path

from weirdfinder import config as config_module
from weirdfinder.config import Config, ConfigError


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_missing_config_names_the_fix(tmp_path):
    with pytest.raises(ConfigError, match="weirdfinder init"):
        config_module.load(tmp_path / "absent.toml")


def test_minimal_config_gets_every_default(tmp_path):
    cfg = config_module.load(write(tmp_path, '[sheet]\nspreadsheet_id = "abc"\n'))
    assert cfg.sheet.spreadsheet_id == "abc"
    assert cfg.scoring.min_score == 45.0
    assert cfg.steam.enabled is True
    assert cfg.itch.pages_per_path == 2


def test_a_typo_in_a_key_is_an_error_not_a_silent_no_op(tmp_path):
    path = write(tmp_path, "[scoring]\nmin_scores = 60\n")
    with pytest.raises(ConfigError, match="min_scores"):
        config_module.load(path)


def test_the_error_lists_the_valid_keys(tmp_path):
    path = write(tmp_path, "[itch]\nbrowse_path = []\n")
    with pytest.raises(ConfigError, match="browse_paths"):
        config_module.load(path)


def test_queries_and_lexicon_survive_the_round_trip(tmp_path):
    path = write(
        tmp_path,
        """
[steam]
queries = [ { term = "vhs", sort_by = "Released_DESC" } ]

[lexicon.vibe]
"kitchen sink horror" = 3.0
""",
    )
    cfg = config_module.load(path)
    assert cfg.steam.queries == [{"term": "vhs", "sort_by": "Released_DESC"}]
    assert cfg.lexicon["vibe"]["kitchen sink horror"] == 3.0


def test_validate_flags_the_things_that_break_an_unattended_run(tmp_path):
    cfg = Config()
    problems = config_module.validate(cfg)
    assert any("spreadsheet_id" in p for p in problems)
    assert any("service account" in p for p in problems)


def test_validate_rejects_a_bad_combine_mode():
    cfg = Config()
    cfg.scoring.combine = "sideways"
    assert any("combine" in p for p in config_module.validate(cfg))


def test_validate_rejects_all_sources_disabled():
    cfg = Config()
    cfg.steam.enabled = cfg.itch.enabled = False
    assert any("both sources" in p for p in config_module.validate(cfg))


def test_validate_rejects_zero_weights():
    cfg = Config()
    cfg.scoring.weight_obscurity = 0
    cfg.scoring.weight_vibe = 0
    cfg.scoring.weight_experimental = 0
    assert any("weights" in p for p in config_module.validate(cfg))


def test_the_shipped_example_config_parses_and_validates_cleanly(tmp_path):
    from pathlib import Path

    example = Path(config_module.__file__).parent / "config.example.toml"
    cfg = config_module.load(example)
    problems = config_module.validate(cfg)
    # Only the two things the user is told to fill in should be outstanding.
    assert all(
        "spreadsheet_id" in p or "service account" in p for p in problems
    ), problems


def test_unknown_lexicon_axis_is_rejected():
    from weirdfinder.lexicon import merged

    with pytest.raises(KeyError, match="unknown lexicon axis"):
        merged({"spooky": {"x": 1.0}})
