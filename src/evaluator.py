"""
Runtime reliability evaluator for VibeFinder.

Every recommendation list is checked after scoring and before it is shown.

* Critical integrity failures (bad scores, wrong order, songs that do not
  match the trusted catalog, explanations that disagree with the scoring
  rules, ...) mean the list is unreliable and must not be displayed.
* Quality warnings (low match scores, unknown genre or mood, repeated
  artists, ...) describe a reliable list that may still be a weak fit.

The evaluator is read-only: it never changes preferences, scores, rankings,
or artist selections. It reuses the original weights and score_song(), so
"consistent with the scoring rules" means "identical to what VibeFinder 1.0
would compute from the trusted catalog record".

Match percentages are raw score / maximum possible score for the profile.
They are a heuristic summary of how many weighted preferences a song meets,
not a calibrated confidence, probability, or prediction of user enjoyment.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    from src.recommender import (
        GENRE_WEIGHT, MOOD_WEIGHT, NUMERIC_WEIGHTS, _moods_similar, score_song,
    )
except ImportError:
    from recommender import GENRE_WEIGHT, MOOD_WEIGHT, NUMERIC_WEIGHTS, _moods_similar, score_song


CRITICAL = "critical"
WARNING = "warning"

STRONG_MATCH = "Strong Match"
MODERATE_MATCH = "Moderate Match"
LOW_MATCH = "Low Match"

# Absorbs float rounding, e.g. 3.6 / 4.5 == 0.7999999999999999.
_CLASSIFY_EPSILON = 1e-9

INTEGRITY_CHECKS = (
    "well_formed",
    "result_count",
    "finite_scores",
    "score_range",
    "descending_order",
    "unique_ids",
    "catalog_match",
    "scoring_consistency",
    "top_scores_returned",
)


@dataclass(frozen=True)
class EvaluationConfig:
    """Tunable heuristics. Thresholds are fractions of the profile's maximum score."""

    strong_threshold: float = 0.80
    moderate_threshold: float = 0.60
    score_tolerance: float = 1e-9
    # Require that no omitted catalog song outscores the lowest returned song.
    require_top_scores: bool = True

    def __post_init__(self):
        if not 0 <= self.moderate_threshold <= self.strong_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= moderate_threshold <= strong_threshold <= 1")
        if self.score_tolerance < 0:
            raise ValueError("score_tolerance must not be negative")


DEFAULT_CONFIG = EvaluationConfig()


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # CRITICAL or WARNING
    message: str
    ranks: tuple = ()  # 1-based ranks the issue refers to, if any


@dataclass(frozen=True)
class SongEvaluation:
    rank: int
    song_id: Any
    title: str
    artist: str
    raw_score: float
    max_score: float
    match_fraction: float
    match_level: str
    genre_match: bool
    mood_relation: str  # "exact", "similar", or "none"

    @property
    def match_percent(self) -> float:
        return self.match_fraction * 100


@dataclass
class EvaluationResult:
    max_score: float
    requested: int
    returned: int
    catalog_size: int
    songs: List[SongEvaluation] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    checks: Sequence[str] = INTEGRITY_CHECKS

    @property
    def critical(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == CRITICAL]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def passed(self) -> bool:
        """True when there are no critical integrity failures (warnings are allowed)."""
        return not self.critical

    @property
    def top(self) -> Optional[SongEvaluation]:
        return self.songs[0] if self.songs else None

    def failure_summary(self) -> str:
        return "; ".join(i.message for i in self.critical)


class RecommendationBlockedError(Exception):
    """Raised when recommendations fail integrity checks and must not be shown."""

    def __init__(self, evaluation: EvaluationResult):
        self.evaluation = evaluation
        count = len(evaluation.critical)
        super().__init__(
            f"Recommendations blocked: {count} integrity check failure(s): {evaluation.failure_summary()}"
        )


# ---------------------------------------------------------------------------
# Normalized match scoring
# ---------------------------------------------------------------------------

def _norm(value: Any) -> str:
    """Normalize text exactly as score_song() does."""
    return str(value if value is not None else "").strip().lower()


def max_possible_score(user_prefs: Mapping) -> float:
    """
    Highest score score_song() can award for these preferences.

    Genre and mood count when non-empty; each numeric feature counts when it is
    not None. For validated profiles this is 4.5, 5.0, or 5.5.
    """
    total = 0.0
    if _norm(user_prefs.get("genre")):
        total += GENRE_WEIGHT
    if _norm(user_prefs.get("mood")):
        total += MOOD_WEIGHT
    for feature, weight in NUMERIC_WEIGHTS.items():
        if user_prefs.get(feature) is not None:
            total += weight
    return total


def normalized_match(raw_score: float, max_score: float) -> float:
    """Raw score as a fraction of the maximum (0 when the maximum is 0)."""
    return raw_score / max_score if max_score > 0 else 0.0


def classify_match(fraction: float, config: EvaluationConfig = DEFAULT_CONFIG) -> str:
    if fraction + _CLASSIFY_EPSILON >= config.strong_threshold:
        return STRONG_MATCH
    if fraction + _CLASSIFY_EPSILON >= config.moderate_threshold:
        return MODERATE_MATCH
    return LOW_MATCH


def mood_relation(user_mood: Any, song_mood: Any) -> str:
    """'exact', 'similar' (SIMILAR_MOODS partial credit), or 'none'."""
    a, b = _norm(user_mood), _norm(song_mood)
    if a and a == b:
        return "exact"
    if a and _moods_similar(a, b):
        return "similar"
    return "none"


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _ranks_text(ranks: Sequence[int]) -> str:
    ranks = list(ranks)
    if len(ranks) == 1:
        return f"rank {ranks[0]}"
    return "ranks " + ", ".join(str(r) for r in ranks[:-1]) + f" and {ranks[-1]}"


def evaluate_recommendations(
    user_prefs: Mapping,
    recommendations: Any,
    catalog: Sequence[Mapping],
    k: int,
    config: EvaluationConfig = DEFAULT_CONFIG,
) -> EvaluationResult:
    """
    Check a recommend_songs() result against the trusted, validated catalog.

    `recommendations` is expected to be a list of (song_dict, score, explanation).
    Returns an EvaluationResult; callers must not display the list when
    `result.passed` is False.
    """
    tol = config.score_tolerance
    max_score = max_possible_score(user_prefs)
    catalog_by_id = {song["id"]: song for song in catalog}
    result = EvaluationResult(
        max_score=max_score,
        requested=k,
        returned=len(recommendations) if isinstance(recommendations, (list, tuple)) else 0,
        catalog_size=len(catalog),
    )

    def fail(code: str, message: str, ranks=()):
        result.issues.append(Issue(code, CRITICAL, message, tuple(ranks)))

    def warn(code: str, message: str, ranks=()):
        result.issues.append(Issue(code, WARNING, message, tuple(ranks)))

    # --- well_formed -------------------------------------------------------
    if not isinstance(recommendations, (list, tuple)):
        fail("malformed_result", f"recommendations must be a list, got {type(recommendations).__name__}")
        return result

    items = []  # (rank, song, score, explanation) for well-formed entries
    for rank, item in enumerate(recommendations, start=1):
        if (
            not isinstance(item, (list, tuple)) or len(item) != 3
            or not isinstance(item[0], Mapping) or not isinstance(item[2], str)
        ):
            fail("malformed_item", f"rank {rank}: expected (song, score, explanation)", [rank])
            continue
        items.append((rank, item[0], item[1], item[2]))

    # --- result_count ------------------------------------------------------
    expected_count = max(0, min(k, len(catalog)))
    if len(recommendations) > max(k, 0):
        fail("too_many_results", f"{len(recommendations)} recommendations returned but only {k} requested")
    elif not recommendations and expected_count > 0:
        fail("empty_result", "no recommendations were produced from a non-empty catalog")
    elif len(recommendations) < expected_count:
        fail(
            "result_truncated",
            f"only {len(recommendations)} of {expected_count} expected recommendations were returned",
        )

    # --- finite_scores / score_range ---------------------------------------
    scored = []  # entries with a usable numeric score
    for rank, song, score, explanation in items:
        if not _is_number(score) or not math.isfinite(score):
            fail("invalid_score", f"rank {rank}: score must be a finite number, got {score!r}", [rank])
            continue
        if score < -tol or score > max_score + tol:
            fail(
                "score_out_of_range",
                f"rank {rank}: score {score:.2f} is outside 0-{max_score:.2f} for this profile",
                [rank],
            )
        scored.append((rank, song, score, explanation))

    # --- descending_order --------------------------------------------------
    for (rank_a, _, score_a, _), (rank_b, _, score_b, _) in zip(scored, scored[1:]):
        if score_b > score_a + tol:
            fail(
                "not_sorted",
                f"rank {rank_b} ({score_b:.2f}) scores higher than rank {rank_a} ({score_a:.2f})",
                [rank_a, rank_b],
            )

    # --- unique_ids --------------------------------------------------------
    first_rank: Dict[Any, int] = {}
    for rank, song, _, _ in items:
        song_id = song.get("id")
        if song_id in first_rank:
            fail("duplicate_song", f"rank {rank}: song id {song_id!r} already appears at rank {first_rank[song_id]}",
                 [first_rank[song_id], rank])
        else:
            first_rank[song_id] = rank

    # --- catalog_match / scoring_consistency -------------------------------
    trusted_items = []  # (rank, trusted_song, score) for entries that match the catalog
    for rank, song, score, explanation in items:
        song_id = song.get("id")
        trusted = catalog_by_id.get(song_id)
        if trusted is None:
            fail("unknown_song", f"rank {rank}: song id {song_id!r} is not in the catalog", [rank])
            continue
        changed = [f for f in trusted if song.get(f) != trusted[f]]
        if changed:
            fail(
                "metadata_mismatch",
                f"rank {rank}: song id {song_id!r} differs from the catalog in {', '.join(changed)}",
                [rank],
            )
        expected_score, reasons = score_song(user_prefs, trusted)
        if _is_number(score) and math.isfinite(score) and abs(score - expected_score) > tol:
            fail(
                "score_mismatch",
                f"rank {rank}: score {score:.2f} does not match the scoring rules ({expected_score:.2f})",
                [rank],
            )
        if explanation != "; ".join(reasons):
            fail("explanation_mismatch", f"rank {rank}: explanation does not match the scoring rules", [rank])
        trusted_items.append((rank, trusted, expected_score))

    # --- top_scores_returned -----------------------------------------------
    if config.require_top_scores and trusted_items and not result.critical:
        returned_ids = {song["id"] for _, song, _ in trusted_items}
        lowest = min(score for _, _, score in trusted_items)
        omitted = [
            song for song in catalog
            if song["id"] not in returned_ids and score_song(user_prefs, song)[0] > lowest + tol
        ]
        if omitted:
            fail(
                "better_song_omitted",
                f"{len(omitted)} catalog song(s) outscore the lowest recommendation but were left out",
            )

    # --- per-song match scores (from the unrounded raw scores) -------------
    for rank, song, score, _ in scored:
        fraction = normalized_match(score, max_score)
        result.songs.append(SongEvaluation(
            rank=rank,
            song_id=song.get("id"),
            title=str(song.get("title", "")),
            artist=str(song.get("artist", "")),
            raw_score=score,
            max_score=max_score,
            match_fraction=fraction,
            match_level=classify_match(fraction, config),
            genre_match=bool(_norm(user_prefs.get("genre"))) and _norm(user_prefs.get("genre")) == _norm(song.get("genre")),
            mood_relation=mood_relation(user_prefs.get("mood"), song.get("mood")),
        ))

    if result.critical:
        return result  # quality warnings are meaningless for an unreliable list

    _add_quality_warnings(result, user_prefs, catalog, config, warn)
    return result


def _add_quality_warnings(result, user_prefs, catalog, config, warn) -> None:
    moderate_pct = config.moderate_threshold * 100
    strong_pct = config.strong_threshold * 100

    # Unknown genre / mood (case- and whitespace-insensitive, like score_song).
    genre = _norm(user_prefs.get("genre"))
    mood = _norm(user_prefs.get("mood"))
    catalog_genres = {_norm(s["genre"]) for s in catalog}
    catalog_moods = {_norm(s["mood"]) for s in catalog}
    genre_unknown = bool(genre) and genre not in catalog_genres
    mood_unknown = bool(mood) and mood not in catalog_moods
    if genre_unknown:
        warn("unknown_genre", f"No song in the catalog has the genre '{user_prefs.get('genre')}', "
                              f"so no recommendation can earn genre points.")
    if mood_unknown:
        similar = sorted(m for m in catalog_moods if _moods_similar(mood, m))
        detail = (f" Songs with a similar mood ({', '.join(similar)}) can still earn partial credit."
                  if similar else " No similar mood is available either.")
        warn("unknown_mood", f"No song in the catalog has the mood '{user_prefs.get('mood')}'.{detail}")

    if not result.songs:
        return

    # Fewer songs than requested (only possible when the catalog is smaller than k).
    if result.returned < result.requested:
        warn("fewer_than_requested",
             f"Only {result.returned} recommendation(s) available; {result.requested} were requested.")

    # Low match scores.
    low = [s.rank for s in result.songs if s.match_level == LOW_MATCH]
    if low:
        warn("low_match",
             f"Low match: {_ranks_text(low)} scored below {moderate_pct:.0f}% of the maximum possible score.",
             low)
    if not any(s.match_level == STRONG_MATCH for s in result.songs):
        warn("no_strong_match",
             f"No strong match: the best recommendation reaches only {result.top.match_percent:.1f}% "
             f"(strong is {strong_pct:.0f}% or more).", [result.top.rank])

    # Top recommendation preference mismatches (skipped when already explained as unknown).
    top = result.top
    if genre and not genre_unknown and not top.genre_match:
        warn("top_genre_mismatch",
             f"Top recommendation '{top.title}' does not match the requested genre.", [top.rank])
    if mood and not mood_unknown:
        if top.mood_relation == "similar":
            warn("top_mood_similar",
                 f"Top recommendation '{top.title}' only has a similar mood, not an exact match "
                 f"(partial credit).", [top.rank])
        elif top.mood_relation == "none":
            warn("top_mood_mismatch",
                 f"Top recommendation '{top.title}' does not match the requested mood.", [top.rank])

    # Repeated artists (warning only; diversity correction is a later phase).
    by_artist = defaultdict(list)
    for s in result.songs:
        by_artist[_norm(s.artist)].append(s)
    for entries in by_artist.values():
        if len(entries) > 1:
            ranks = [s.rank for s in entries]
            warn("repeated_artist",
                 f"Repeated artist: {entries[0].artist} appears at {_ranks_text(ranks)}.", ranks)
