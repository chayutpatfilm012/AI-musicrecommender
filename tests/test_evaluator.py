"""Tests for src/evaluator.py: integrity checks, normalized match scores, and quality warnings."""

import math

import pytest

from src.evaluator import (
    CRITICAL,
    INTEGRITY_CHECKS,
    LOW_MATCH,
    MODERATE_MATCH,
    STRONG_MATCH,
    WARNING,
    EvaluationConfig,
    RecommendationBlockedError,
    classify_match,
    evaluate_recommendations,
    max_possible_score,
    mood_relation,
    normalized_match,
)
from src.main import DEFAULT_PROFILE, STRESS_PROFILES
from src.recommender import load_songs, recommend_songs

ALL_PROFILES = {"Default": DEFAULT_PROFILE, **STRESS_PROFILES}


@pytest.fixture(scope="module")
def catalog():
    return load_songs("data/songs.csv")


def fresh(prefs, catalog, k=5):
    """A recommend_songs() result with copied song dicts, safe to corrupt."""
    return [(dict(song), score, explanation) for song, score, explanation in recommend_songs(prefs, catalog, k=k)]


def codes(result, severity=None):
    return [i.code for i in result.issues if severity is None or i.severity == severity]


def make_song(song_id, **fields):
    song = {
        "id": song_id, "title": f"Song {song_id}", "artist": f"Artist {song_id}", "genre": "pop",
        "mood": "happy", "energy": 0.5, "tempo_bpm": 100.0, "valence": 0.5, "danceability": 0.5,
        "acousticness": 0.5,
    }
    song.update(fields)
    return song


def evaluate_small(prefs, songs, k=5):
    return evaluate_recommendations(prefs, recommend_songs(prefs, songs, k=k), songs, k)


# ---------------------------------------------------------------------------
# Normalized match scoring
# ---------------------------------------------------------------------------

BASE = {"genre": "pop", "mood": "happy", "energy": 0.8}


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({}, 4.5),
        ({"valence": 0.5}, 5.0),
        ({"acousticness": 0.5}, 5.0),
        ({"valence": 0.5, "acousticness": 0.5}, 5.5),
        ({"valence": None, "acousticness": None}, 4.5),  # None means "not given"
    ],
)
def test_max_possible_score(extra, expected):
    assert max_possible_score({**BASE, **extra}) == pytest.approx(expected)


@pytest.mark.parametrize("name, expected", [
    ("Default", 4.5), ("High-Energy Pop", 4.5), ("Chill Lofi", 5.5),
    ("Intense Rock", 4.5), ("Conflicting Preferences", 4.5),
])
def test_max_possible_score_for_app_profiles(name, expected):
    assert max_possible_score(ALL_PROFILES[name]) == pytest.approx(expected)


def test_normalized_match_uses_unrounded_raw_score(catalog):
    result = evaluate_recommendations(STRESS_PROFILES["Chill Lofi"], fresh(STRESS_PROFILES["Chill Lofi"], catalog), catalog, 5)
    midnight = result.songs[1]
    assert midnight.title == "Midnight Coding"
    assert midnight.raw_score == pytest.approx(5.365)  # printed as 5.37
    assert midnight.match_fraction == pytest.approx(5.365 / 5.5)
    assert midnight.match_percent == pytest.approx(97.5454545, abs=1e-6)


def test_normalized_match_with_zero_maximum():
    assert normalized_match(0.0, 0.0) == 0.0
    assert normalized_match(4.48, 4.5) == pytest.approx(0.995555, abs=1e-6)


@pytest.mark.parametrize(
    "fraction, level",
    [
        (1.0, STRONG_MATCH),
        (0.80, STRONG_MATCH),
        (3.6 / 4.5, STRONG_MATCH),  # 0.7999999999999999 in floating point
        (0.7999, MODERATE_MATCH),
        (0.60, MODERATE_MATCH),
        (2.7 / 4.5, MODERATE_MATCH),
        (0.5999, LOW_MATCH),
        (0.0, LOW_MATCH),
    ],
)
def test_match_classification_boundaries(fraction, level):
    assert classify_match(fraction) == level


def test_thresholds_are_configurable():
    config = EvaluationConfig(strong_threshold=0.9, moderate_threshold=0.5)
    assert classify_match(0.85, config) == MODERATE_MATCH
    assert classify_match(0.55, config) == MODERATE_MATCH
    assert classify_match(0.45, config) == LOW_MATCH


@pytest.mark.parametrize("kwargs", [
    {"strong_threshold": 0.5, "moderate_threshold": 0.6},
    {"strong_threshold": 1.2},
    {"moderate_threshold": -0.1},
    {"score_tolerance": -1},
])
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        EvaluationConfig(**kwargs)


@pytest.mark.parametrize("user, song, expected", [
    ("chill", "chill", "exact"),
    (" Chill ", "CHILL", "exact"),
    ("chill", "focused", "similar"),
    ("peaceful", "chill", "similar"),
    ("relaxed", "peaceful", "none"),
    ("happy", "sad", "none"),
])
def test_mood_relation_follows_original_rules(user, song, expected):
    assert mood_relation(user, song) == expected


# ---------------------------------------------------------------------------
# Valid results
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(ALL_PROFILES))
def test_real_profiles_pass_every_integrity_check(name, catalog):
    prefs = ALL_PROFILES[name]
    recs = recommend_songs(prefs, catalog, k=5)
    snapshot = [(s["id"], score, explanation) for s, score, explanation in recs]

    result = evaluate_recommendations(prefs, recs, catalog, 5)

    assert result.passed and result.critical == []
    assert [s.rank for s in result.songs] == [1, 2, 3, 4, 5]
    assert [s.raw_score for s in result.songs] == [score for _, score, _ in snapshot]
    # Read-only: the result list is untouched.
    assert [(s["id"], score, e) for s, score, e in recs] == snapshot
    assert tuple(result.checks) == INTEGRITY_CHECKS


# ---------------------------------------------------------------------------
# Critical integrity failures
# ---------------------------------------------------------------------------

def _set_score(recs, index, value):
    song, _, explanation = recs[index]
    recs[index] = (song, value, explanation)


def _set_field(recs, index, field, value):
    recs[index][0][field] = value


CORRUPTIONS = {
    "negative score": (lambda r: _set_score(r, 4, -0.5), "score_out_of_range"),
    "excessive score": (lambda r: _set_score(r, 0, 9.0), "score_out_of_range"),
    "just above max": (lambda r: _set_score(r, 0, 4.5 + 1e-6), "score_out_of_range"),
    "nan score": (lambda r: _set_score(r, 0, math.nan), "invalid_score"),
    "positive infinity": (lambda r: _set_score(r, 0, math.inf), "invalid_score"),
    "negative infinity": (lambda r: _set_score(r, 4, -math.inf), "invalid_score"),
    "boolean score": (lambda r: _set_score(r, 0, True), "invalid_score"),
    "string score": (lambda r: _set_score(r, 0, "4.48"), "invalid_score"),
    "wrong order": (lambda r: r.__setitem__(slice(0, 2), [r[1], r[0]]), "not_sorted"),
    "duplicate id": (lambda r: r.__setitem__(1, (dict(r[0][0]), r[0][1], r[0][2])), "duplicate_song"),
    "unknown song": (lambda r: _set_field(r, 2, "id", 999), "unknown_song"),
    "altered title": (lambda r: _set_field(r, 0, "title", "Fake Hit"), "metadata_mismatch"),
    "altered genre": (lambda r: _set_field(r, 1, "genre", "lofi"), "metadata_mismatch"),
    "altered energy": (lambda r: _set_field(r, 3, "energy", 0.1), "metadata_mismatch"),
    "wrong score": (lambda r: _set_score(r, 2, 2.40), "score_mismatch"),
    "wrong explanation": (
        lambda r: r.__setitem__(0, (r[0][0], r[0][1], "genre match (+2.0)")), "explanation_mismatch"
    ),
}


@pytest.mark.parametrize("corrupt, expected_code", CORRUPTIONS.values(), ids=list(CORRUPTIONS))
def test_corrupted_results_fail_integrity(corrupt, expected_code, catalog):
    recs = fresh(DEFAULT_PROFILE, catalog)
    corrupt(recs)
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5)
    assert not result.passed
    assert expected_code in codes(result, CRITICAL)
    # Quality warnings are not produced for an unreliable list.
    assert result.warnings == []


def test_metadata_mismatch_names_changed_fields(catalog):
    recs = fresh(DEFAULT_PROFILE, catalog)
    recs[0][0]["artist"] = "Someone Else"
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5)
    assert "rank 1: song id 1 differs from the catalog in artist" in result.failure_summary()


def test_score_recomputed_from_trusted_catalog_record(catalog):
    # Metadata and score altered together so they agree with each other but not the catalog.
    recs = fresh(DEFAULT_PROFILE, catalog)
    song, _, _ = recs[3]  # Concrete Crown, hip hop
    song["genre"] = "pop"
    recs[3] = (song, 2.98, "genre match (+2.0); energy closeness (+0.98)")
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5)
    assert {"metadata_mismatch", "score_mismatch", "explanation_mismatch"} <= set(codes(result, CRITICAL))


def test_omitted_higher_scoring_song_is_detected(catalog):
    six = fresh(DEFAULT_PROFILE, catalog, k=6)
    recs = six[:4] + [six[5]]  # skip the real rank 5
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5)
    assert codes(result, CRITICAL) == ["better_song_omitted"]


def test_omitted_song_check_can_be_disabled(catalog):
    six = fresh(DEFAULT_PROFILE, catalog, k=6)
    recs = six[:4] + [six[5]]
    config = EvaluationConfig(require_top_scores=False)
    assert evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5, config).passed


@pytest.mark.parametrize(
    "recs_factory, k, expected_code",
    [
        (lambda r: [], 5, "empty_result"),
        (lambda r: r[:3], 5, "result_truncated"),
        (lambda r: r, 3, "too_many_results"),
        (lambda r: None, 5, "malformed_result"),
        (lambda r: "not a list", 5, "malformed_result"),
        (lambda r: [r[0][:2]] + r[1:], 5, "malformed_item"),
        (lambda r: [("song", 4.48, "x")] + r[1:], 5, "malformed_item"),
        (lambda r: [(r[0][0], r[0][1], None)] + r[1:], 5, "malformed_item"),
    ],
    ids=["empty", "truncated", "too-many", "none", "string", "short-tuple", "song-not-dict", "explanation-not-str"],
)
def test_empty_and_malformed_results_fail_safely(recs_factory, k, expected_code, catalog):
    recs = recs_factory(fresh(DEFAULT_PROFILE, catalog))
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, k)
    assert not result.passed
    assert expected_code in codes(result, CRITICAL)


def test_empty_result_is_fine_when_nothing_was_requested(catalog):
    assert evaluate_recommendations(DEFAULT_PROFILE, [], catalog, 0).passed


def test_blocked_error_carries_the_evaluation(catalog):
    recs = fresh(DEFAULT_PROFILE, catalog)
    _set_score(recs, 0, 9.0)
    result = evaluate_recommendations(DEFAULT_PROFILE, recs, catalog, 5)
    error = RecommendationBlockedError(result)
    assert error.evaluation is result
    assert str(error).startswith("Recommendations blocked: ")
    assert "rank 1: score 9.00 is outside 0-4.50 for this profile" in str(error)


# ---------------------------------------------------------------------------
# Quality warnings (real catalog)
# ---------------------------------------------------------------------------

def test_default_profile_warnings(catalog):
    result = evaluate_recommendations(DEFAULT_PROFILE, fresh(DEFAULT_PROFILE, catalog), catalog, 5)
    assert result.passed
    assert [(i.code, i.ranks) for i in result.warnings] == [
        ("low_match", (3, 4, 5)),
        ("repeated_artist", (1, 5)),
    ]
    assert [s.match_level for s in result.songs] == [
        STRONG_MATCH, MODERATE_MATCH, LOW_MATCH, LOW_MATCH, LOW_MATCH,
    ]
    assert all(i.severity == WARNING for i in result.warnings)


def test_chill_lofi_repeated_artist(catalog):
    prefs = STRESS_PROFILES["Chill Lofi"]
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    repeated = [i for i in result.warnings if i.code == "repeated_artist"]
    assert len(repeated) == 1
    assert repeated[0].ranks == (2, 3)
    assert repeated[0].message == "Repeated artist: LoRoom appears at ranks 2 and 3."


def test_conflicting_profile_has_no_strong_match_and_top_mood_mismatch(catalog):
    prefs = STRESS_PROFILES["Conflicting Preferences"]
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    assert result.passed
    assert codes(result, WARNING) == ["low_match", "no_strong_match", "top_mood_mismatch"]
    assert result.top.match_level == MODERATE_MATCH
    assert result.top.mood_relation == "none"


def test_unknown_genre_is_warned_without_redundant_mismatch(catalog):
    prefs = {"genre": "k-pop", "mood": "happy", "energy": 0.8}
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    assert result.passed
    assert "unknown_genre" in codes(result)
    assert "top_genre_mismatch" not in codes(result)
    assert "no_strong_match" in codes(result)  # 2.48 / 4.5 at best


def test_unknown_mood_without_similar_moods(catalog):
    prefs = {"genre": "pop", "mood": "euphoric", "energy": 0.8}
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    unknown = [i for i in result.warnings if i.code == "unknown_mood"]
    assert unknown and "No similar mood is available" in unknown[0].message
    assert "top_mood_mismatch" not in codes(result)


def test_known_genre_and_mood_match_case_insensitively(catalog):
    prefs = {"genre": " POP ", "mood": "Happy", "energy": 0.8}
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    assert not {"unknown_genre", "unknown_mood", "top_genre_mismatch", "top_mood_mismatch"} & set(codes(result))


def test_strong_profile_has_no_top_mismatch_warnings(catalog):
    prefs = STRESS_PROFILES["Intense Rock"]
    result = evaluate_recommendations(prefs, fresh(prefs, catalog), catalog, 5)
    assert codes(result) == ["low_match"]
    assert result.top.genre_match and result.top.mood_relation == "exact"


# ---------------------------------------------------------------------------
# Quality warnings (small catalogs for cases the real catalog cannot produce)
# ---------------------------------------------------------------------------

def test_unknown_mood_with_similar_moods_mentions_partial_credit():
    songs = [make_song(1, genre="lofi", mood="relaxed"), make_song(2, genre="jazz", mood="sad")]
    result = evaluate_small({"genre": "lofi", "mood": "chill", "energy": 0.5}, songs, k=2)
    unknown = [i for i in result.warnings if i.code == "unknown_mood"]
    assert unknown and "similar mood (relaxed) can still earn partial credit" in unknown[0].message


def test_top_recommendation_with_only_similar_mood():
    songs = [make_song(1, genre="lofi", mood="focused"), make_song(2, genre="jazz", mood="chill", energy=0.0)]
    result = evaluate_small({"genre": "lofi", "mood": "chill", "energy": 0.5}, songs, k=2)
    # Song 1: 2.0 + 0.75 (similar) + 1.0 = 3.75 beats song 2: 1.5 (exact) + 0.5 = 2.0.
    assert result.top.title == "Song 1"
    assert result.top.mood_relation == "similar"
    assert "top_mood_similar" in codes(result)
    assert "top_mood_mismatch" not in codes(result)


def test_top_recommendation_genre_mismatch():
    songs = [make_song(1, genre="rock", mood="happy", energy=0.8), make_song(2, genre="pop", mood="sad", energy=0.0)]
    result = evaluate_small({"genre": "pop", "mood": "happy", "energy": 0.8}, songs, k=2)
    # Rock song: 1.5 + 1.0 = 2.5 beats the pop song: 2.0 + 0.2 = 2.2.
    assert result.top.title == "Song 1"
    assert "top_genre_mismatch" in codes(result)


def test_fewer_songs_than_requested_is_a_warning_not_a_failure():
    songs = [make_song(1), make_song(2)]
    result = evaluate_small({"genre": "pop", "mood": "happy", "energy": 0.5}, songs, k=5)
    assert result.passed
    assert "fewer_than_requested" in codes(result, WARNING)
    assert result.returned == 2 and result.requested == 5


def test_repeated_artist_is_case_insensitive():
    songs = [make_song(1, artist="The Band"), make_song(2, artist="the band "), make_song(3)]
    result = evaluate_small({"genre": "pop", "mood": "happy", "energy": 0.5}, songs, k=3)
    repeated = [i for i in result.warnings if i.code == "repeated_artist"]
    assert len(repeated) == 1 and repeated[0].ranks == (1, 2)
