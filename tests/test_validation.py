"""Tests for src/validation.py: listener preferences and the song catalog."""

import csv
import math

import pytest

from src.main import DEFAULT_PROFILE, STRESS_PROFILES
from src.recommender import load_songs, score_song
from src.validation import (
    SONG_FIELDS,
    DatasetError,
    ValidationError,
    load_validated_songs,
    validate_songs,
    validate_user_prefs,
)

VALID_FULL = {"genre": "lofi", "mood": "chill", "energy": 0.35, "valence": 0.6, "acousticness": 0.8}
VALID_MINIMAL = {"genre": "pop", "mood": "happy", "energy": 0.8}


def prefs_with(**changes):
    prefs = dict(VALID_MINIMAL)
    for key, value in changes.items():
        if value is _REMOVE:
            prefs.pop(key, None)
        else:
            prefs[key] = value
    return prefs


_REMOVE = object()


def problem_fields(exc_info):
    return exc_info.value.fields


# ---------------------------------------------------------------------------
# 1-2, 13-14. Valid preferences
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prefs", [VALID_FULL, VALID_MINIMAL, DEFAULT_PROFILE, *STRESS_PROFILES.values()])
def test_valid_preferences_are_returned_unchanged(prefs):
    result = validate_user_prefs(prefs)
    assert result == prefs
    assert result is not prefs  # a copy, so callers cannot be surprised by mutation


def test_optional_fields_may_be_none():
    prefs = prefs_with(valence=None, acousticness=None)
    assert validate_user_prefs(prefs) == prefs


@pytest.mark.parametrize("field", ["energy", "valence", "acousticness"])
@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0])
def test_boundary_values_zero_and_one_are_valid(field, value):
    prefs = prefs_with(**{field: value})
    assert validate_user_prefs(prefs)[field] == value


@pytest.mark.parametrize("genre", ["k-pop", "Vaporwave", "  polka  "])
def test_unknown_genre_is_allowed(genre):
    # Genres not in the catalog are not rejected (low-match warnings come later).
    assert validate_user_prefs(prefs_with(genre=genre))["genre"] == genre


def test_unknown_mood_is_allowed():
    assert validate_user_prefs(prefs_with(mood="euphoric"))["mood"] == "euphoric"


def test_case_and_whitespace_are_preserved_and_still_matched():
    prefs = validate_user_prefs(prefs_with(genre="  POP ", mood="Happy"))
    assert prefs["genre"] == "  POP "  # not rewritten by validation
    song = {"genre": "pop", "mood": "happy", "energy": 0.8, "valence": 0.5, "acousticness": 0.5}
    score, _ = score_song(prefs, song)
    assert score == pytest.approx(4.5)  # score_song still normalizes case/whitespace


# ---------------------------------------------------------------------------
# 3-5. Empty profile, missing fields, empty text
# ---------------------------------------------------------------------------

def test_empty_preferences_are_rejected():
    with pytest.raises(ValidationError, match="preferences are empty"):
        validate_user_prefs({})


@pytest.mark.parametrize("not_a_dict", [None, [], "pop", 0.8])
def test_non_dict_preferences_are_rejected(not_a_dict):
    with pytest.raises(ValidationError, match="must be a dictionary"):
        validate_user_prefs(not_a_dict)


@pytest.mark.parametrize("field", ["genre", "mood", "energy"])
@pytest.mark.parametrize("how", ["omitted", "none"])
def test_missing_required_field_is_rejected(field, how):
    prefs = prefs_with(**{field: _REMOVE if how == "omitted" else None})
    with pytest.raises(ValidationError, match=f"{field} is required") as exc_info:
        validate_user_prefs(prefs)
    assert problem_fields(exc_info) == [field]


def test_all_missing_problems_are_reported_together():
    with pytest.raises(ValidationError) as exc_info:
        validate_user_prefs({"valence": 0.5})
    assert problem_fields(exc_info) == ["genre", "mood", "energy"]


@pytest.mark.parametrize("field", ["genre", "mood"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_empty_genre_or_mood_is_rejected(field, value):
    with pytest.raises(ValidationError, match=f"{field} must not be empty"):
        validate_user_prefs(prefs_with(**{field: value}))


@pytest.mark.parametrize("field", ["genre", "mood"])
@pytest.mark.parametrize("value", [5, 0.5, True, ["pop"]])
def test_non_text_genre_or_mood_is_rejected(field, value):
    with pytest.raises(ValidationError, match=f"{field} must be text"):
        validate_user_prefs(prefs_with(**{field: value}))


def test_unknown_preference_key_is_rejected():
    with pytest.raises(ValidationError, match="unknown preference 'enrgy'") as exc_info:
        validate_user_prefs(prefs_with(enrgy=0.5))
    assert problem_fields(exc_info) == ["enrgy"]


# ---------------------------------------------------------------------------
# 6-12. Invalid numeric values (required energy and optional features)
# ---------------------------------------------------------------------------

NUMERIC_FIELDS = ["energy", "valence", "acousticness"]

INVALID_NUMBERS = [
    pytest.param(-0.01, "between 0 and 1", id="below-zero"),
    pytest.param(-1, "between 0 and 1", id="negative-int"),
    pytest.param(1.01, "between 0 and 1", id="above-one"),
    pytest.param(1.5, "between 0 and 1", id="one-point-five"),
    pytest.param("high", "not text", id="word-string"),
    pytest.param("0.5", "not text", id="numeric-string"),
    pytest.param("", "not text", id="empty-string"),
    pytest.param(math.nan, "finite", id="nan"),
    pytest.param(math.inf, "finite", id="positive-infinity"),
    pytest.param(-math.inf, "finite", id="negative-infinity"),
    pytest.param(True, "must be a number", id="bool-true"),
    pytest.param(False, "must be a number", id="bool-false"),
    pytest.param([0.5], "must be a number", id="list"),
]


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value, message", INVALID_NUMBERS)
def test_invalid_numeric_preferences_are_rejected(field, value, message):
    with pytest.raises(ValidationError, match=message) as exc_info:
        validate_user_prefs(prefs_with(**{field: value}))
    assert problem_fields(exc_info) == [field]
    assert field in str(exc_info.value)


def test_out_of_range_value_is_not_clamped():
    prefs = prefs_with(energy=1.5)
    with pytest.raises(ValidationError, match="got 1.5"):
        validate_user_prefs(prefs)
    assert prefs["energy"] == 1.5  # input left untouched


def test_validation_does_not_mutate_input():
    prefs = {"genre": " Pop ", "mood": "HAPPY", "energy": 0.8, "valence": None}
    snapshot = dict(prefs)
    validate_user_prefs(prefs)
    assert prefs == snapshot


def test_error_message_lists_every_problem():
    with pytest.raises(ValidationError) as exc_info:
        validate_user_prefs({"genre": "", "mood": "happy", "energy": math.nan, "valence": 2})
    message = str(exc_info.value)
    assert message.startswith("Invalid listener preferences: ")
    assert "genre must not be empty" in message
    assert "energy must be a finite number" in message
    assert "valence must be between 0 and 1, got 2" in message


# ---------------------------------------------------------------------------
# 15-18. Song records (validate_songs)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def catalog():
    return load_songs("data/songs.csv")


def good_song(**changes):
    song = {
        "id": 1, "title": "Song", "artist": "Artist", "genre": "pop", "mood": "happy",
        "energy": 0.5, "tempo_bpm": 120.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5,
    }
    song.update(changes)
    return song


def test_real_catalog_is_valid_and_returned_unchanged(catalog):
    assert validate_songs(catalog) is catalog
    assert len(catalog) == 20


def test_empty_dataset_is_rejected():
    with pytest.raises(DatasetError, match="contains no songs"):
        validate_songs([])


def test_non_list_dataset_is_rejected():
    with pytest.raises(DatasetError, match="must be a list"):
        validate_songs({"id": 1})


@pytest.mark.parametrize("field", SONG_FIELDS)
def test_missing_song_field_is_rejected(field):
    song = good_song()
    del song[field]
    with pytest.raises(DatasetError, match=f"missing field '{field}'") as exc_info:
        validate_songs([song])
    assert exc_info.value.fields == [field]


def test_duplicate_song_ids_are_rejected():
    songs = [good_song(id=1), good_song(id=2), good_song(id=1)]
    with pytest.raises(DatasetError, match=r"song #3 \(id 1\): duplicate id 1 \(first used by song #1\)"):
        validate_songs(songs)


@pytest.mark.parametrize("bad_id", [0, -3, "7", 1.0, True, None])
def test_invalid_song_ids_are_rejected(bad_id):
    with pytest.raises(DatasetError, match="id must be a positive integer"):
        validate_songs([good_song(id=bad_id)])


@pytest.mark.parametrize("field", ["title", "artist", "genre", "mood"])
@pytest.mark.parametrize("value", ["", "  ", None])
def test_empty_song_text_fields_are_rejected(field, value):
    with pytest.raises(DatasetError, match=field):
        validate_songs([good_song(**{field: value})])


@pytest.mark.parametrize("field", ["energy", "valence", "acousticness"])
@pytest.mark.parametrize("value", [-0.1, 1.2, math.nan, math.inf, -math.inf, "0.5", True])
def test_invalid_scoring_feature_values_are_rejected(field, value):
    with pytest.raises(DatasetError) as exc_info:
        validate_songs([good_song(**{field: value})])
    assert exc_info.value.fields == [field]


@pytest.mark.parametrize("value", [60.0, 200, 168.0])
def test_tempo_is_not_limited_to_zero_one(value):
    assert validate_songs([good_song(tempo_bpm=value)])[0]["tempo_bpm"] == value


@pytest.mark.parametrize("value", [0, -10.0, math.nan, math.inf, "fast"])
def test_invalid_tempo_is_rejected(value):
    with pytest.raises(DatasetError, match="tempo_bpm"):
        validate_songs([good_song(tempo_bpm=value)])


def test_dataset_errors_are_collected_across_songs():
    songs = [good_song(id=1, energy=2.0), good_song(id=2, title=""), good_song(id=2)]
    with pytest.raises(DatasetError) as exc_info:
        validate_songs(songs)
    assert len(exc_info.value.problems) == 3
    assert exc_info.value.fields == ["energy", "title", "id"]


def test_long_error_lists_are_truncated_in_message():
    songs = [good_song(id=i, energy=5.0) for i in range(1, 16)]
    with pytest.raises(DatasetError) as exc_info:
        validate_songs(songs)
    assert len(exc_info.value.problems) == 15
    assert "...and 5 more problem(s)" in str(exc_info.value)


def test_dataset_error_is_a_validation_error():
    assert issubclass(DatasetError, ValidationError)
    assert issubclass(ValidationError, ValueError)


# ---------------------------------------------------------------------------
# 19-20. CSV loading (load_validated_songs)
# ---------------------------------------------------------------------------

HEADER = list(SONG_FIELDS)
GOOD_ROW = ["1", "Song", "Artist", "pop", "happy", "0.5", "120", "0.5", "0.5", "0.5"]


def write_csv(path, rows, header=HEADER):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header is not None:
            writer.writerow(header)
        writer.writerows(rows)
    return str(path)


def test_real_catalog_loads_identically_to_load_songs(catalog):
    assert load_validated_songs("data/songs.csv") == catalog


def test_valid_temp_csv_loads(tmp_path):
    path = write_csv(tmp_path / "songs.csv", [GOOD_ROW, ["2", *GOOD_ROW[1:]]])
    songs = load_validated_songs(path)
    assert [s["id"] for s in songs] == [1, 2]
    assert songs[0]["energy"] == 0.5


def test_missing_csv_file_gives_clear_error(tmp_path):
    missing = str(tmp_path / "nope.csv")
    with pytest.raises(DatasetError, match="song catalog not found") as exc_info:
        load_validated_songs(missing)
    assert exc_info.value.__cause__ is None  # no chained FileNotFoundError traceback


def test_missing_relative_csv_reports_the_given_path():
    with pytest.raises(DatasetError, match="song catalog not found: data/does_not_exist.csv"):
        load_validated_songs("data/does_not_exist.csv")


def test_directory_instead_of_file_gives_clear_error(tmp_path):
    with pytest.raises(DatasetError, match="could not read"):
        load_validated_songs(str(tmp_path))


def test_completely_empty_csv_is_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetError, match="is empty"):
        load_validated_songs(str(path))


def test_header_only_csv_is_rejected(tmp_path):
    path = write_csv(tmp_path / "header.csv", [])
    with pytest.raises(DatasetError, match="has a header but no songs"):
        load_validated_songs(path)


def test_csv_missing_columns_is_rejected(tmp_path):
    header = [c for c in HEADER if c not in ("energy", "mood")]
    path = write_csv(tmp_path / "cols.csv", [GOOD_ROW[:8]], header=header)
    with pytest.raises(DatasetError, match="missing required column\\(s\\): mood, energy"):
        load_validated_songs(path)


@pytest.mark.parametrize(
    "row, message",
    [
        pytest.param(["abc", *GOOD_ROW[1:]], "id must be an integer, got 'abc'", id="bad-id"),
        pytest.param(["", *GOOD_ROW[1:]], "id must be an integer, got ''", id="blank-id"),
        pytest.param(GOOD_ROW[:5] + ["high"] + GOOD_ROW[6:], "energy must be a number, got 'high'", id="bad-energy"),
        pytest.param(GOOD_ROW[:9] + [""], "acousticness must be a number, got ''", id="blank-acousticness"),
        pytest.param(GOOD_ROW[:7], "row is too short", id="short-row"),
        pytest.param(GOOD_ROW + ["extra"], "more value\\(s\\) than the header", id="long-row"),
    ],
)
def test_malformed_csv_rows_are_rejected(tmp_path, row, message):
    path = write_csv(tmp_path / "bad.csv", [row])
    with pytest.raises(DatasetError, match=message) as exc_info:
        load_validated_songs(path)
    assert "line 2" in str(exc_info.value)


@pytest.mark.parametrize(
    "position, value, message",
    [
        (5, "nan", "energy must be a finite number"),
        (7, "inf", "valence must be a finite number"),
        (9, "1.5", "acousticness must be between 0 and 1"),
        (6, "0", "tempo_bpm must be greater than 0"),
        (1, " ", "title must not be empty"),
    ],
)
def test_parseable_but_invalid_csv_values_are_rejected(tmp_path, position, value, message):
    row = list(GOOD_ROW)
    row[position] = value
    path = write_csv(tmp_path / "values.csv", [row])
    with pytest.raises(DatasetError, match=message):
        load_validated_songs(path)


def test_duplicate_ids_in_csv_are_rejected(tmp_path):
    path = write_csv(tmp_path / "dupes.csv", [GOOD_ROW, GOOD_ROW])
    with pytest.raises(DatasetError, match="duplicate id 1"):
        load_validated_songs(path)


def test_non_utf8_csv_is_rejected(tmp_path):
    path = tmp_path / "latin1.csv"
    path.write_bytes((",".join(HEADER) + "\n1,Caf\xe9,A,pop,happy,0.5,120,0.5,0.5,0.5\n").encode("latin-1"))
    with pytest.raises(DatasetError, match="not valid UTF-8"):
        load_validated_songs(str(path))
