"""
Input and data validation for VibeFinder.

Validation sits at the application boundary, in front of the original scoring
engine in recommender.py. score_song() and recommend_songs() are unchanged:
anything that reaches them through the main workflow has already passed the
checks below.

Validators never clamp, coerce, or rewrite values. They either return the
input unchanged (as a shallow copy for preferences) or raise ValidationError
listing every problem found.
"""

import csv
import math
import os
from numbers import Real
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

try:
    # Works with `python -m src.main` and pytest from the project root.
    from src.recommender import load_songs
except ImportError:
    # Works with `python src/main.py`.
    from recommender import load_songs


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

Problem = Tuple[str, str]  # (field, message)

MAX_REPORTED_PROBLEMS = 10


class ValidationError(ValueError):
    """Raised when input fails validation. Carries every problem found."""

    def __init__(self, context: str, problems: Iterable[Problem]):
        self.context = context
        self.problems: List[Problem] = list(problems)
        super().__init__(self._format())

    @property
    def fields(self) -> List[str]:
        """Distinct field names with problems, in the order first seen."""
        return list(dict.fromkeys(field for field, _ in self.problems))

    def _format(self) -> str:
        shown = [message for _, message in self.problems[:MAX_REPORTED_PROBLEMS]]
        hidden = len(self.problems) - len(shown)
        if hidden > 0:
            shown.append(f"...and {hidden} more problem(s)")
        return f"Invalid {self.context}: " + "; ".join(shown)


class DatasetError(ValidationError):
    """Raised when the song catalog cannot be read or fails validation."""

    def __init__(self, problems: Iterable[Problem]):
        super().__init__("song catalog", problems)


# ---------------------------------------------------------------------------
# Listener preferences
# ---------------------------------------------------------------------------

REQUIRED_TEXT_PREFS = ("genre", "mood")
REQUIRED_NUMERIC_PREFS = ("energy",)
OPTIONAL_NUMERIC_PREFS = ("valence", "acousticness")
ALLOWED_PREFS = REQUIRED_TEXT_PREFS + REQUIRED_NUMERIC_PREFS + OPTIONAL_NUMERIC_PREFS


def _describe(value: Any) -> str:
    return f"{type(value).__name__} {value!r}"


def _check_unit_number(field: str, value: Any, owner: str = "") -> Optional[str]:
    """Return an error message if value is not a finite real number in [0, 1]."""
    label = f"{owner}{field}"
    if isinstance(value, bool) or not isinstance(value, Real):
        hint = " (use a number such as 0.5, not text)" if isinstance(value, str) else ""
        return f"{label} must be a number between 0 and 1, got {_describe(value)}{hint}"
    if not math.isfinite(value):
        return f"{label} must be a finite number between 0 and 1, got {value!r}"
    if not 0 <= value <= 1:
        return f"{label} must be between 0 and 1, got {value!r}"
    return None


def _check_text(field: str, value: Any, owner: str = "") -> Optional[str]:
    label = f"{owner}{field}"
    if not isinstance(value, str):
        return f"{label} must be text, got {_describe(value)}"
    if not value.strip():
        return f"{label} must not be empty"
    return None


def validate_user_prefs(user_prefs: Any) -> Dict[str, Any]:
    """
    Validate a listener's preference dict for the main application workflow.

    Required: genre and mood (non-empty text) and energy (number in [0, 1]).
    Optional: valence and acousticness (number in [0, 1], or None / omitted).

    Values are returned unchanged in a shallow copy. Case and surrounding
    whitespace in genre and mood are left for score_song() to normalize, and
    genres or moods absent from the catalog are allowed.
    """
    context = "listener preferences"
    if not isinstance(user_prefs, Mapping):
        raise ValidationError(
            context, [("profile", f"preferences must be a dictionary, got {type(user_prefs).__name__}")]
        )
    if not user_prefs:
        raise ValidationError(
            context,
            [("profile", "preferences are empty; provide at least genre, mood, and energy")],
        )

    problems: List[Problem] = []

    unknown = [key for key in user_prefs if key not in ALLOWED_PREFS]
    for key in unknown:
        problems.append(
            (str(key), f"unknown preference {key!r}; allowed: {', '.join(ALLOWED_PREFS)}")
        )

    for field in REQUIRED_TEXT_PREFS:
        if user_prefs.get(field) is None:
            problems.append((field, f"{field} is required"))
        else:
            error = _check_text(field, user_prefs[field])
            if error:
                problems.append((field, error))

    for field in REQUIRED_NUMERIC_PREFS:
        if user_prefs.get(field) is None:
            problems.append((field, f"{field} is required (a number between 0 and 1)"))
        else:
            error = _check_unit_number(field, user_prefs[field])
            if error:
                problems.append((field, error))

    for field in OPTIONAL_NUMERIC_PREFS:
        if user_prefs.get(field) is not None:
            error = _check_unit_number(field, user_prefs[field])
            if error:
                problems.append((field, error))

    if problems:
        raise ValidationError(context, problems)
    return dict(user_prefs)


# ---------------------------------------------------------------------------
# Song catalog
# ---------------------------------------------------------------------------

SONG_FIELDS = (
    "id", "title", "artist", "genre", "mood",
    "energy", "tempo_bpm", "valence", "danceability", "acousticness",
)
TEXT_SONG_FIELDS = ("title", "artist", "genre", "mood")
NUMERIC_SONG_FIELDS = ("energy", "tempo_bpm", "valence", "danceability", "acousticness")
UNIT_SONG_FIELDS = ("energy", "valence", "acousticness")  # used by score_song()


def _song_label(index: int, song: Mapping) -> str:
    song_id = song.get("id") if isinstance(song, Mapping) else None
    return f"song #{index + 1}" + (f" (id {song_id!r})" if song_id not in (None, "") else "")


def validate_songs(songs: Any) -> List[Dict]:
    """
    Validate loaded song dicts (as returned by load_songs) and return them unchanged.

    Checks: non-empty list, every SONG_FIELDS key present, ids are unique
    positive integers, text fields are non-empty, numeric fields are finite
    numbers, energy/valence/acousticness are in [0, 1], and tempo_bpm is
    positive (no 0-1 limit on tempo).
    """
    if not isinstance(songs, list):
        raise DatasetError([("catalog", f"songs must be a list, got {type(songs).__name__}")])
    if not songs:
        raise DatasetError([("catalog", "the catalog contains no songs")])

    problems: List[Problem] = []
    seen_ids: Dict[int, int] = {}

    for index, song in enumerate(songs):
        if not isinstance(song, Mapping):
            problems.append(("song", f"song #{index + 1} must be a dictionary, got {type(song).__name__}"))
            continue
        owner = _song_label(index, song) + ": "

        missing = [field for field in SONG_FIELDS if field not in song]
        for field in missing:
            problems.append((field, f"{owner}missing field {field!r}"))

        if "id" in song:
            song_id = song["id"]
            if isinstance(song_id, bool) or not isinstance(song_id, int) or song_id < 1:
                problems.append(("id", f"{owner}id must be a positive integer, got {_describe(song_id)}"))
            elif song_id in seen_ids:
                problems.append(("id", f"{owner}duplicate id {song_id} (first used by song #{seen_ids[song_id] + 1})"))
            else:
                seen_ids[song_id] = index

        for field in TEXT_SONG_FIELDS:
            if field in song:
                error = _check_text(field, song[field], owner)
                if error:
                    problems.append((field, error))

        for field in UNIT_SONG_FIELDS:
            if field in song:
                error = _check_unit_number(field, song[field], owner)
                if error:
                    problems.append((field, error))

        for field in ("tempo_bpm", "danceability"):
            if field not in song:
                continue
            value = song[field]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                problems.append((field, f"{owner}{field} must be a finite number, got {_describe(value)}"))
            elif field == "tempo_bpm" and value <= 0:
                problems.append((field, f"{owner}tempo_bpm must be greater than 0, got {value!r}"))

    if problems:
        raise DatasetError(problems)
    return songs


def resolve_csv_path(csv_path: str) -> str:
    """Resolve a catalog path the same way load_songs() does."""
    if not os.path.isabs(csv_path) and not os.path.exists(csv_path):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, csv_path)
    return csv_path


def _check_csv_structure(csv_path: str, display_path: str) -> None:
    """Check that the CSV can be read and parsed before load_songs() converts it."""
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if not header:
                raise DatasetError([("catalog", f"{display_path} is empty (no header row)")])

            missing_columns = [column for column in SONG_FIELDS if column not in header]
            if missing_columns:
                raise DatasetError([
                    ("columns", f"{display_path} is missing required column(s): {', '.join(missing_columns)}")
                ])

            problems: List[Problem] = []
            row_count = 0
            for row in reader:
                row_count += 1
                owner = f"line {reader.line_num}: "
                if row.get(None):
                    problems.append(("row", f"{owner}has {len(row[None])} more value(s) than the header"))
                for field in SONG_FIELDS:
                    raw = row.get(field)
                    if raw is None:
                        problems.append((field, f"{owner}missing value for {field!r} (row is too short)"))
                    elif field == "id":
                        try:
                            int(raw)
                        except ValueError:
                            problems.append(("id", f"{owner}id must be an integer, got {raw!r}"))
                    elif field in NUMERIC_SONG_FIELDS:
                        try:
                            float(raw)
                        except ValueError:
                            problems.append((field, f"{owner}{field} must be a number, got {raw!r}"))

            if row_count == 0:
                raise DatasetError([("catalog", f"{display_path} has a header but no songs")])
            if problems:
                raise DatasetError(problems)
    except FileNotFoundError:
        raise DatasetError([("catalog", f"song catalog not found: {display_path}")]) from None
    except UnicodeDecodeError:
        raise DatasetError([("catalog", f"{display_path} is not valid UTF-8 text")]) from None
    except csv.Error as exc:
        raise DatasetError([("catalog", f"{display_path} is not a valid CSV file: {exc}")]) from None
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise DatasetError([("catalog", f"could not read {display_path}: {reason}")]) from None


def load_validated_songs(csv_path: str) -> List[Dict]:
    """
    Load the catalog with the original load_songs() after checking it is safe to.

    1. Check the file exists and parses as a CSV with every required column and
       convertible values (so load_songs() cannot raise a raw traceback).
    2. Load it with the unchanged load_songs().
    3. Validate the converted records with validate_songs().

    Raises DatasetError with a readable message for any problem.
    """
    resolved = resolve_csv_path(csv_path)
    _check_csv_structure(resolved, csv_path)
    # Pass the caller's path so load_songs() prints exactly what it always has.
    return validate_songs(load_songs(csv_path))
