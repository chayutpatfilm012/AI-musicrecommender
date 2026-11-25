"""
Command line runner for the Music Recommender Simulation.

Loads the song catalog, scores every song against a listener profile using
the functions in recommender.py, and prints the top 5 recommendations with
the reasons for each score.

The catalog and every listener profile are validated (see validation.py)
before anything is scored, and every recommendation list is checked by the
reliability evaluator (see evaluator.py) before it is shown. A list that
fails an integrity check is blocked; quality warnings are shown with it.
Recommendations go to stdout; structured logs and error messages go to stderr.

Usage:
    python -m src.main                    # default profile (pop, happy, energy 0.8)
    python -m src.main --stress           # four stress-test profiles
    python -m src.main --log-level ERROR  # hide INFO/WARNING logs
"""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

try:
    # Works with `python -m src.main` from the project root.
    from src.evaluator import EvaluationResult, RecommendationBlockedError, evaluate_recommendations
    from src.logging_config import configure_logging, get_logger, log_event
    from src.recommender import recommend_songs
    from src.validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs
except ImportError:
    # Works with `python src/main.py`.
    from evaluator import EvaluationResult, RecommendationBlockedError, evaluate_recommendations
    from logging_config import configure_logging, get_logger, log_event
    from recommender import recommend_songs
    from validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs


WIDTH = 60
CATALOG_PATH = "data/songs.csv"

EXIT_OK = 0
EXIT_INVALID_INPUT = 1
EXIT_UNEXPECTED_ERROR = 2
EXIT_RECOMMENDATION_BLOCKED = 3

# Starter example profile used when no flag is given.
DEFAULT_PROFILE = {"genre": "pop", "mood": "happy", "energy": 0.8}

# Profiles used by `--stress` to probe the scoring logic.
STRESS_PROFILES = {
    "High-Energy Pop": {"genre": "pop", "mood": "happy", "energy": 0.90},
    "Chill Lofi": {
        "genre": "lofi",
        "mood": "chill",
        "energy": 0.35,
        "valence": 0.60,
        "acousticness": 0.80,
    },
    "Intense Rock": {"genre": "rock", "mood": "intense", "energy": 0.95},
    "Conflicting Preferences": {"genre": "metal", "mood": "peaceful", "energy": 0.90},
}

# Quality-warning codes that get their own log event name.
WARNING_EVENTS = {
    "low_match": "low_match_detected",
    "no_strong_match": "low_match_detected",
    "repeated_artist": "repeated_artist_detected",
}

logger = get_logger()


def print_profile(user_prefs: dict, title: str = "MUSIC RECOMMENDER") -> None:
    print("=" * WIDTH)
    print(f"  {title}".center(WIDTH))
    print("=" * WIDTH)
    print("User profile:")
    for key, value in user_prefs.items():
        print(f"  - {key:<13}: {value}")
    print()


def print_recommendations(recommendations: list) -> None:
    print(f"Top {len(recommendations)} recommendations")
    print("-" * WIDTH)
    if not recommendations:
        print("  No songs to recommend.")
    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        print(f"{rank}. {song['title']} - {song['artist']}")
        print(f"   Genre: {song['genre']} | Mood: {song['mood']}")
        print(f"   Score: {score:.2f}")
        print("   Reasons:")
        for reason in explanation.split("; "):
            if reason:
                print(f"     * {reason}")
        print("-" * WIDTH)


def print_evaluation(evaluation: EvaluationResult) -> None:
    """Print the reliability summary after the (unchanged) recommendation list."""
    print("Reliability check")
    print("-" * WIDTH)
    print(f"Integrity: PASSED ({len(evaluation.checks)} checks)")
    print(f"Match scores (raw score / max possible {evaluation.max_score:.2f} for this profile):")
    for song in evaluation.songs:
        print(
            f"  {song.rank}. {song.title:<22} {song.raw_score:>5.2f} / {song.max_score:.2f}"
            f"  {song.match_percent:5.1f}%  {song.match_level}"
        )
    print("  (Match % is a heuristic share of the maximum score,")
    print("   not a confidence level or a prediction of enjoyment.)")
    warnings = evaluation.warnings
    print(f"Warnings: {len(warnings) if warnings else 'none'}")
    for issue in warnings:
        print(f"  ! {issue.message}")
    print("-" * WIDTH)


def print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def log_evaluation(evaluation: EvaluationResult, profile_name: str) -> None:
    for issue in evaluation.critical:
        log_event(
            logger, logging.ERROR, "integrity_check_failed",
            profile=profile_name, code=issue.code, ranks=list(issue.ranks) or "-",
        )
    for issue in evaluation.warnings:
        event = WARNING_EVENTS.get(issue.code, "quality_warning_detected")
        log_event(
            logger, logging.WARNING, event,
            profile=profile_name, code=issue.code, ranks=list(issue.ranks) or "-",
        )
    # Match stats from a list that failed integrity checks are untrustworthy; don't log them.
    top = evaluation.top if evaluation.passed else None
    log_event(
        logger, logging.INFO, "evaluation_completed",
        profile=profile_name, passed=evaluation.passed,
        critical=len(evaluation.critical), warnings=len(evaluation.warnings),
        max_score=evaluation.max_score,
        top_match_pct=top.match_percent if top else "-",
        top_level=top.match_level if top else "-",
    )


def recommend_for_profile(
    user_prefs: Dict, songs: List[Dict], k: int = 5, profile_name: str = "default"
) -> Tuple[list, EvaluationResult]:
    """
    Validate a profile, score it with the unchanged recommend_songs(), then
    evaluate the result. Raises ValidationError for bad input and
    RecommendationBlockedError when the result fails an integrity check.
    """
    try:
        prefs = validate_user_prefs(user_prefs)
    except ValidationError as exc:
        log_event(
            logger, logging.WARNING, "validation_failed",
            profile=profile_name, fields=exc.fields, problems=len(exc.problems),
        )
        raise
    # Log which preferences were given, not their values.
    log_event(logger, logging.INFO, "preferences_validated", profile=profile_name, fields=list(prefs))

    recommendations = recommend_songs(prefs, songs, k=k)
    log_event(
        logger, logging.INFO, "scoring_completed",
        profile=profile_name, candidates=len(songs), returned=len(recommendations),
        top_score=recommendations[0][1] if recommendations else 0.0,
    )

    log_event(
        logger, logging.INFO, "evaluation_started",
        profile=profile_name, returned=len(recommendations), requested=k,
    )
    evaluation = evaluate_recommendations(prefs, recommendations, songs, k)
    log_evaluation(evaluation, profile_name)
    if not evaluation.passed:
        log_event(
            logger, logging.ERROR, "recommendation_blocked",
            profile=profile_name, failures=len(evaluation.critical),
            codes=sorted({i.code for i in evaluation.critical}),
        )
        raise RecommendationBlockedError(evaluation)
    return recommendations, evaluation


def run_stress_test(songs: list) -> int:
    """Run every stress profile; an invalid or blocked profile is reported and skipped."""
    exit_code = EXIT_OK
    for number, (name, user_prefs) in enumerate(STRESS_PROFILES.items(), start=1):
        title = f"STRESS TEST {number}: {name}"
        try:
            recommendations, evaluation = recommend_for_profile(user_prefs, songs, k=5, profile_name=name)
        except ValidationError as exc:
            exit_code = max(exit_code, EXIT_INVALID_INPUT)
            print_error(f"{title}: {exc}")
            continue
        except RecommendationBlockedError as exc:
            exit_code = max(exit_code, EXIT_RECOMMENDATION_BLOCKED)
            print_error(f"{title}: {exc}")
            continue
        print_profile(user_prefs, title=title)
        print_recommendations(recommendations)
        print_evaluation(evaluation)
        print()
    return exit_code


def log_safe_path(csv_path: str) -> str:
    """Relative paths are logged as given; absolute ones by file name only (they can contain a username)."""
    return os.path.basename(csv_path) if os.path.isabs(csv_path) else csv_path


def load_catalog(csv_path: str = CATALOG_PATH) -> List[Dict]:
    songs = load_validated_songs(csv_path)
    log_event(logger, logging.INFO, "dataset_loaded", path=log_safe_path(csv_path), songs=len(songs))
    log_event(logger, logging.INFO, "dataset_validation_completed", songs=len(songs), problems=0)
    return songs


def run(stress: bool, csv_path: str = CATALOG_PATH, user_prefs: Optional[Dict] = None) -> int:
    """Run one application session and return its exit code."""
    try:
        songs = load_catalog(csv_path)
    except DatasetError as exc:
        log_event(
            logger, logging.ERROR, "dataset_validation_failed",
            path=log_safe_path(csv_path), problems=len(exc.problems),
        )
        print_error(str(exc))
        return EXIT_INVALID_INPUT
    print(f"Loaded {len(songs)} songs.\n")

    if stress:
        return run_stress_test(songs)

    prefs = DEFAULT_PROFILE if user_prefs is None else user_prefs
    try:
        recommendations, evaluation = recommend_for_profile(prefs, songs, k=5)
    except ValidationError as exc:
        print_error(str(exc))
        return EXIT_INVALID_INPUT
    except RecommendationBlockedError as exc:
        print_error(str(exc))
        return EXIT_RECOMMENDATION_BLOCKED

    print_profile(prefs)
    print_recommendations(recommendations)
    print_evaluation(evaluation)
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Music Recommender Simulation")
    parser.add_argument(
        "--stress",
        action="store_true",
        help="run the top 5 for each stress-test profile instead of the default profile",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="minimum level of log messages written to stderr (default: INFO)",
    )
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    log_event(logger, logging.INFO, "app_started", mode="stress" if args.stress else "default")

    try:
        exit_code = run(args.stress)
    except Exception as exc:  # last-resort guard: no raw traceback in normal CLI use
        log_event(logger, logging.ERROR, "app_error", error_type=type(exc).__name__)
        logger.debug("Traceback for unexpected error", exc_info=True)
        print_error("an unexpected error occurred; rerun with --log-level DEBUG for details")
        return EXIT_UNEXPECTED_ERROR

    log_event(logger, logging.INFO, "app_finished", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
