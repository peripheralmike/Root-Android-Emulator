from conftest import *  # noqa: F401,F403 - puts src on sys.path

from weirdfinder.config import ScoringConfig
from weirdfinder.models import Game
from weirdfinder import scoring


def game(**kwargs) -> Game:
    base = dict(source="test", source_id="1", title="", url="")
    base.update(kwargs)
    return Game(**base)


def test_normalise_strips_punctuation_but_keeps_hyphens():
    assert scoring.normalise("Avant-Garde!! GAME") == " avant-garde game "


def test_normalise_folds_decomposable_accents():
    assert scoring.normalise("Café Niño") == " cafe nino "
    assert scoring.normalise("") == "  "


def test_normalise_survives_letters_that_do_not_decompose():
    # "ø" has no NFKD decomposition, so it drops out rather than folding to
    # "o". Documented here so the behaviour is a decision, not a surprise.
    assert scoring.normalise("Cøde") == " c de "


def test_obscurity_is_one_with_no_reviews():
    cfg = ScoringConfig()
    assert scoring.obscurity_score(0, cfg) == 1.0


def test_obscurity_falls_to_zero_at_the_cap():
    cfg = ScoringConfig(popularity_cap=3000)
    assert scoring.obscurity_score(3000, cfg) == 0.0
    assert scoring.obscurity_score(999_999, cfg) == 0.0


def test_obscurity_is_monotonic():
    cfg = ScoringConfig()
    values = [scoring.obscurity_score(n, cfg) for n in (0, 5, 50, 500, 2500)]
    assert values == sorted(values, reverse=True)


def test_unknown_popularity_uses_the_configured_default():
    cfg = ScoringConfig(unknown_obscurity=0.75)
    assert scoring.obscurity_score(None, cfg) == 0.75


def test_tags_count_more_than_prose():
    cfg = ScoringConfig()
    in_tag = scoring.score(game(tags=["Surreal"]), cfg)
    in_prose = scoring.score(game(description="surreal"), cfg)
    assert in_tag.vibe > in_prose.vibe


def test_a_phrase_matched_in_both_fields_is_only_counted_once():
    cfg = ScoringConfig()
    both = scoring.score(game(title="Surreal", description="surreal surreal", tags=["Surreal"]), cfg)
    tag_only = scoring.score(game(tags=["Surreal"]), cfg)
    assert both.vibe == tag_only.vibe


def test_axes_saturate_below_one():
    cfg = ScoringConfig()
    everything = scoring.score(
        game(tags=["Analog Horror", "Surreal", "Liminal", "PSX", "Body Horror", "Weirdcore"]),
        cfg,
    )
    assert 0.9 < everything.vibe < 1.0


def test_weights_are_normalised_so_only_the_ratio_matters():
    small = ScoringConfig(weight_obscurity=1, weight_vibe=1, weight_experimental=1)
    large = ScoringConfig(weight_obscurity=10, weight_vibe=10, weight_experimental=10)
    subject = game(tags=["Surreal"], popularity=10)
    assert scoring.score(subject, small).total == scoring.score(subject, large).total


def test_obscure_analog_horror_outranks_a_popular_shooter():
    cfg = ScoringConfig()
    weird = scoring.score(
        game(title="TAPE NINE", tags=["Analog Horror", "Liminal"], popularity=3), cfg
    )
    normal = scoring.score(
        game(title="Space Shooter", tags=["Action", "FPS"], popularity=40_000), cfg
    )
    assert weird.total > normal.total
    assert weird.total > 80  # strong on two axes is a strong find


def test_matched_explains_the_score_longest_phrase_first():
    cfg = ScoringConfig()
    result = scoring.score(game(tags=["Psychological Horror"]), cfg)
    assert result.matched[0] == "psychological horror"
    assert "horror" in result.matched


def test_lexicon_override_adds_a_phrase():
    cfg = ScoringConfig()
    subject = game(tags=["Kitchen Sink Horror"])
    before = scoring.score(subject, cfg)
    after = scoring.score(subject, cfg, {"vibe": {"kitchen sink horror": 5.0}})
    assert after.vibe > before.vibe


def test_lexicon_override_of_zero_mutes_a_builtin():
    cfg = ScoringConfig()
    subject = game(tags=["Horror"])
    muted = scoring.score(subject, cfg, {"vibe": {"horror": 0}})
    assert muted.vibe == 0.0


def test_exclude_terms_are_case_insensitive_and_match_tags():
    cfg = ScoringConfig(exclude_terms=["Asset Flip"])
    assert scoring.excluded(game(tags=["asset flip"]), cfg) == "Asset Flip"
    assert scoring.excluded(game(title="Fine Game"), cfg) is None


def test_score_all_drops_excluded_and_sorts_best_first():
    cfg = ScoringConfig(exclude_terms=["nope"])
    games = [
        game(source_id="a", title="Space Shooter", tags=["FPS"], popularity=90_000),
        game(source_id="b", title="TAPE NINE", tags=["Analog Horror"], popularity=2),
        game(source_id="c", title="nope", tags=["Surreal"]),
    ]
    result = scoring.score_all(games, cfg)
    assert [item.game.source_id for item in result] == ["b", "a"]
    assert result[0].total >= result[1].total


def test_total_stays_inside_zero_to_one_hundred():
    cfg = ScoringConfig()
    nothing = scoring.score(game(title="x", popularity=10**9), cfg)
    everything = scoring.score(
        game(
            title="Surreal Experimental Analog Horror Art Game",
            tags=["Weirdcore", "Liminal", "Avant-Garde", "Anti-Game", "Dada"],
            popularity=0,
        ),
        cfg,
    )
    assert 0.0 <= nothing.total <= 100.0
    assert 90 < everything.total <= 100.0


def test_weighted_mean_mode_requires_all_three_axes():
    strict = ScoringConfig(combine="mean")
    loose = ScoringConfig(combine="best")
    # Great on obscurity and vibe, nothing on experimental.
    subject = game(tags=["Analog Horror", "Liminal"], popularity=3)
    assert scoring.score(subject, loose).total > scoring.score(subject, strict).total


def test_best_mode_does_not_punish_a_single_strong_flavour():
    cfg = ScoringConfig(combine="best")
    horror_only = scoring.score(game(tags=["Analog Horror", "Liminal", "PSX"], popularity=2), cfg)
    art_only = scoring.score(game(tags=["Art Game", "Avant-Garde", "Dada"], popularity=2), cfg)
    assert horror_only.total > 75
    assert art_only.total > 75


def test_best_mode_rewards_scoring_on_both_axes():
    cfg = ScoringConfig(combine="best")
    one = scoring.score(game(tags=["Analog Horror", "Liminal", "PSX"], popularity=2), cfg)
    both = scoring.score(
        game(tags=["Analog Horror", "Liminal", "PSX", "Art Game", "Avant-Garde"], popularity=2),
        cfg,
    )
    assert both.total > one.total


def test_second_axis_bonus_of_zero_is_a_pure_max():
    no_bonus = ScoringConfig(combine="best", second_axis_bonus=0.0)
    one = scoring.score(game(tags=["Analog Horror", "Liminal", "PSX"], popularity=2), no_bonus)
    both = scoring.score(
        game(tags=["Analog Horror", "Liminal", "PSX", "Art Game"], popularity=2), no_bonus
    )
    assert both.total == one.total


def test_combine_never_leaves_the_zero_to_hundred_range():
    for mode in ("best", "mean"):
        cfg = ScoringConfig(combine=mode)
        assert 0.0 <= scoring.combine(0.0, 0.0, 0.0, cfg) <= 100.0
        assert 0.0 <= scoring.combine(1.0, 1.0, 1.0, cfg) <= 100.0
        assert scoring.combine(1.0, 1.0, 1.0, cfg) == 100.0
