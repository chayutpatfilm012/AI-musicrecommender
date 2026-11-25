"""
Baseline regression tests for VibeFinder 1.0.

These tests pin the behavior of the original recommender (scoring weights,
mood similarity, ranking, explanations, and the exact top-5 results for the
default and stress-test profiles) so that VibeFinder 2.0 extensions cannot
silently change it.
"""

import sys

import pytest

from src import main as main_module
from src.main import STRESS_PROFILES
from src.recommender import (
    GENRE_WEIGHT,
    MOOD_WEIGHT,
    NUMERIC_WEIGHTS,
    SIMILAR_MOOD_WEIGHT,
    SIMILAR_MOODS,
    Recommender,
    Song,
    UserProfile,
    load_songs,
    recommend_songs,
    score_song,
)

TOL = 1e-6

# The default profile hardcoded inside src.main.main().
DEFAULT_PROFILE = {"genre": "pop", "mood": "happy", "energy": 0.8}


@pytest.fixture(scope="module")
def songs():
    return load_songs("data/songs.csv")


def make_song(**overrides):
    """A neutral song dict; override only the fields a test cares about."""
    song = {
        "id": 1,
        "title": "Test Song",
        "artist": "Test Artist",
        "genre": "pop",
        "mood": "happy",
        "energy": 0.5,
        "tempo_bpm": 100.0,
        "valence": 0.5,
        "danceability": 0.5,
        "acousticness": 0.5,
    }
    song.update(overrides)
    return song


def top5(prefs, songs):
    return [(song["title"], score) for song, score, _ in recommend_songs(prefs, songs, k=5)]


def assert_ranking(actual, expected):
    assert [title for title, _ in actual] == [title for title, _ in expected]
    for (_, got), (_, want) in zip(actual, expected):
        assert got == pytest.approx(want, abs=TOL)


# ---------------------------------------------------------------------------
# Guard rails on the original configuration
# ---------------------------------------------------------------------------

def test_original_weights_unchanged():
    assert GENRE_WEIGHT == 2.0
    assert MOOD_WEIGHT == 1.5
    assert SIMILAR_MOOD_WEIGHT == 0.75
    assert NUMERIC_WEIGHTS == {"energy": 1.0, "valence": 0.5, "acousticness": 0.5}
    assert SIMILAR_MOODS == {"chill": {"relaxed", "peaceful", "focused"}}


def test_catalog_has_20_songs(songs):
    assert len(songs) == 20
    assert [s["id"] for s in songs] == list(range(1, 21))


# ---------------------------------------------------------------------------
# 1-5. Top-five regression for the default and stress-test profiles
# ---------------------------------------------------------------------------

def test_default_profile_top5(songs):
    assert_ranking(top5(DEFAULT_PROFILE, songs), [
        ("Sunrise City", 4.48),
        ("Gym Hero", 2.87),
        ("Rooftop Lights", 2.46),
        ("Concrete Crown", 0.98),
        ("Night Drive Loop", 0.95),
    ])


def test_default_profile_via_main_cli(monkeypatch, capsys):
    """main() uses its built-in default profile; --mode standard is the VibeFinder 1.0 ranking.

    VibeFinder 2.0 defaults to diverse mode, so the original-ranking snapshot
    now selects standard mode explicitly. All assertions below are unchanged.
    """
    monkeypatch.setattr(sys, "argv", ["src.main", "--mode", "standard"])
    main_module.main()
    out = capsys.readouterr().out
    assert "Loaded 20 songs." in out
    expected_lines = [
        "1. Sunrise City - Neon Echo",
        "2. Gym Hero - Max Pulse",
        "3. Rooftop Lights - Indigo Parade",
        "4. Concrete Crown - Kid Meridian",
        "5. Night Drive Loop - Neon Echo",
    ]
    positions = [out.index(line) for line in expected_lines]
    assert positions == sorted(positions)
    for score in ("4.48", "2.87", "2.46", "0.98", "0.95"):
        assert f"Score: {score}" in out


def test_stress_profiles_are_the_original_four():
    assert list(STRESS_PROFILES) == [
        "High-Energy Pop",
        "Chill Lofi",
        "Intense Rock",
        "Conflicting Preferences",
    ]


def test_high_energy_pop_top5(songs):
    assert_ranking(top5(STRESS_PROFILES["High-Energy Pop"], songs), [
        ("Sunrise City", 4.42),
        ("Gym Hero", 2.97),
        ("Rooftop Lights", 2.36),
        ("Storm Runner", 0.99),
        ("Neon Pulse", 0.95),
    ])


def test_chill_lofi_top5(songs):
    # Unrounded values; the CLI prints them as 5.47, 5.37, 4.69, 3.35, 2.63.
    assert_ranking(top5(STRESS_PROFILES["Chill Lofi"], songs), [
        ("Library Rain", 5.47),
        ("Midnight Coding", 5.365),
        ("Focus Flow", 4.685),
        ("Spacewalk Thoughts", 3.345),
        ("Coffee Shop Stories", 2.63),
    ])


def test_intense_rock_top5(songs):
    assert_ranking(top5(STRESS_PROFILES["Intense Rock"], songs), [
        ("Storm Runner", 4.46),
        ("Gym Hero", 2.48),
        ("Neon Pulse", 1.00),
        ("Iron Tempest", 0.98),
        ("Sunrise City", 0.87),
    ])


def test_conflicting_preferences_top5(songs):
    assert_ranking(top5(STRESS_PROFILES["Conflicting Preferences"], songs), [
        ("Iron Tempest", 2.93),
        ("Winter Nocturne", 1.78),
        ("Midnight Coding", 1.27),
        ("Library Rain", 1.20),
        ("Spacewalk Thoughts", 1.13),
    ])


# ---------------------------------------------------------------------------
# 6-7. Genre matching
# ---------------------------------------------------------------------------

def test_exact_genre_match_scores_genre_weight():
    score, reasons = score_song({"genre": "rock"}, make_song(genre="rock"))
    assert score == pytest.approx(GENRE_WEIGHT)
    assert reasons == ["genre match (+2.0)"]


def test_genre_match_is_exact_not_partial():
    # "indie pop" is not "pop": no partial genre credit exists.
    score, reasons = score_song({"genre": "pop"}, make_song(genre="indie pop"))
    assert score == 0.0
    assert reasons == []


@pytest.mark.parametrize("user_genre", ["POP", "Pop", "  pop  ", "pOp"])
def test_genre_match_is_case_and_whitespace_insensitive(user_genre):
    score, _ = score_song({"genre": user_genre}, make_song(genre="Pop "))
    assert score == pytest.approx(GENRE_WEIGHT)


# ---------------------------------------------------------------------------
# 8-9. Mood matching
# ---------------------------------------------------------------------------

def test_exact_mood_match_scores_mood_weight():
    score, reasons = score_song({"mood": "Happy"}, make_song(mood="happy"))
    assert score == pytest.approx(MOOD_WEIGHT)
    assert reasons == ["mood match (+1.5)"]


def test_different_mood_scores_nothing():
    score, reasons = score_song({"mood": "happy"}, make_song(mood="sad"))
    assert score == 0.0
    assert reasons == []


@pytest.mark.parametrize("song_mood", ["relaxed", "peaceful", "focused"])
def test_similar_mood_gives_partial_credit(song_mood):
    score, reasons = score_song({"mood": "chill"}, make_song(mood=song_mood))
    assert score == pytest.approx(SIMILAR_MOOD_WEIGHT)
    assert reasons == ["similar mood (+0.75)"]


@pytest.mark.parametrize("user_mood", ["relaxed", "peaceful", "focused"])
def test_similar_mood_is_symmetric(user_mood):
    score, _ = score_song({"mood": user_mood}, make_song(mood="chill"))
    assert score == pytest.approx(SIMILAR_MOOD_WEIGHT)


def test_moods_similar_to_chill_are_not_similar_to_each_other():
    # Similarity only goes through "chill"; it is not transitive.
    score, _ = score_song({"mood": "relaxed"}, make_song(mood="peaceful"))
    assert score == 0.0


# ---------------------------------------------------------------------------
# 10-11. Numeric similarity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "user_energy, song_energy, expected",
    [(0.8, 0.8, 1.0), (0.8, 0.82, 0.98), (0.9, 0.4, 0.5), (0.0, 1.0, 0.0)],
)
def test_energy_closeness(user_energy, song_energy, expected):
    score, reasons = score_song({"energy": user_energy}, make_song(energy=song_energy))
    assert score == pytest.approx(expected, abs=TOL)
    assert reasons == [f"energy closeness (+{expected:.2f})"]


def test_valence_and_acousticness_use_half_weight():
    song = make_song(valence=0.4, acousticness=0.9)
    score, reasons = score_song({"valence": 0.6, "acousticness": 0.8}, song)
    # 0.5 * (1 - 0.2) + 0.5 * (1 - 0.1) = 0.40 + 0.45
    assert score == pytest.approx(0.85, abs=TOL)
    assert reasons == ["valence closeness (+0.40)", "acousticness closeness (+0.45)"]


@pytest.mark.parametrize("missing", [{}, {"valence": None, "acousticness": None}])
def test_missing_optional_features_are_not_scored(missing):
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.5, **missing}
    score, reasons = score_song(prefs, make_song())
    assert score == pytest.approx(4.5)
    assert not any("valence" in r or "acousticness" in r for r in reasons)


# ---------------------------------------------------------------------------
# 12. Maximum possible scores
# ---------------------------------------------------------------------------

PERFECT_SONG = make_song(genre="lofi", mood="chill", energy=0.3, valence=0.6, acousticness=0.9)
BASE_PREFS = {"genre": "lofi", "mood": "chill", "energy": 0.3}


@pytest.mark.parametrize(
    "extra, expected_max",
    [
        ({}, 4.5),
        ({"valence": 0.6}, 5.0),
        ({"acousticness": 0.9}, 5.0),
        ({"valence": 0.6, "acousticness": 0.9}, 5.5),
    ],
)
def test_maximum_possible_scores(extra, expected_max):
    score, _ = score_song({**BASE_PREFS, **extra}, PERFECT_SONG)
    assert score == pytest.approx(expected_max)


def test_catalog_scores_never_exceed_profile_maximum(songs):
    for prefs in [DEFAULT_PROFILE, *STRESS_PROFILES.values()]:
        maximum = 4.5 + sum(0.5 for f in ("valence", "acousticness") if prefs.get(f) is not None)
        for song in songs:
            score, _ = score_song(prefs, song)
            assert 0.0 <= score <= maximum + TOL


# ---------------------------------------------------------------------------
# 13. Ranking
# ---------------------------------------------------------------------------

def test_ranking_is_sorted_descending(songs):
    scores = [score for _, score, _ in recommend_songs(DEFAULT_PROFILE, songs, k=len(songs))]
    assert scores == sorted(scores, reverse=True)


def test_tied_scores_keep_catalog_order():
    catalog = [
        make_song(id=1, title="Low", genre="jazz"),
        make_song(id=2, title="Tie A", genre="pop"),
        make_song(id=3, title="Tie B", genre="pop"),
        make_song(id=4, title="Tie C", genre="pop"),
    ]
    ranked = recommend_songs({"genre": "pop"}, catalog, k=4)
    assert [song["title"] for song, _, _ in ranked] == ["Tie A", "Tie B", "Tie C", "Low"]

    # Reversing the catalog reverses the tie order, proving the sort is stable.
    ranked = recommend_songs({"genre": "pop"}, list(reversed(catalog)), k=4)
    assert [song["title"] for song, _, _ in ranked] == ["Tie C", "Tie B", "Tie A", "Low"]


def test_recommend_songs_does_not_mutate_catalog(songs):
    before = [s["id"] for s in songs]
    recommend_songs(DEFAULT_PROFILE, songs, k=5)
    assert [s["id"] for s in songs] == before


@pytest.mark.parametrize("k, expected_len", [(0, 0), (-1, 0), (3, 3), (100, 20)])
def test_k_controls_result_length(songs, k, expected_len):
    assert len(recommend_songs(DEFAULT_PROFILE, songs, k=k)) == expected_len


# ---------------------------------------------------------------------------
# 14. Explanations
# ---------------------------------------------------------------------------

def test_explanation_lists_reasons_in_scoring_order(songs):
    song, score, explanation = recommend_songs(STRESS_PROFILES["Chill Lofi"], songs, k=1)[0]
    assert song["title"] == "Library Rain"
    assert explanation == (
        "genre match (+2.0); mood match (+1.5); energy closeness (+1.00); "
        "valence closeness (+0.50); acousticness closeness (+0.47)"
    )


def test_explanation_for_similar_mood(songs):
    ranked = recommend_songs(STRESS_PROFILES["Chill Lofi"], songs, k=3)
    song, _, explanation = ranked[2]
    assert song["title"] == "Focus Flow"
    assert explanation.split("; ")[:2] == ["genre match (+2.0)", "similar mood (+0.75)"]


def test_explanation_matches_score_song_reasons(songs):
    for song, score, explanation in recommend_songs(DEFAULT_PROFILE, songs, k=5):
        expected_score, reasons = score_song(DEFAULT_PROFILE, song)
        assert score == pytest.approx(expected_score)
        assert explanation == "; ".join(reasons)


def test_recommender_class_explanation_format():
    song = Song(1, "Sunrise City", "Neon Echo", "pop", "happy", 0.82, 118, 0.84, 0.79, 0.18)
    user = UserProfile("pop", "happy", 0.8, likes_acoustic=False)
    explanation = Recommender([song]).explain_recommendation(user, song)
    assert explanation == "Score 4.48: genre match (+2.0); mood match (+1.5); energy closeness (+0.98)"


def test_recommender_class_explanation_with_no_matches():
    song = Song(1, "X", "Y", "metal", "angry", 0.5, 100, 0.5, 0.5, 0.5)
    user = UserProfile("", "", None, likes_acoustic=True)
    explanation = Recommender([song]).explain_recommendation(user, song)
    assert explanation == "Score 0.00: no matching preferences"
