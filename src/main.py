"""
Command line runner for the Music Recommender Simulation.

Loads the song catalog, scores every song against a listener profile using
the functions in recommender.py, and prints the top 5 recommendations with
the reasons for each score.

The catalog and every listener profile are validated (see validation.py)
before anything is scored. Recommendations go to stdout; structured logs and
error messages go to stderr.

Usage:
    python -m src.main                    # default profile (pop, happy, energy 0.8)
    python -m src.main --stress           # four stress-test profiles
    python -m src.main --log-level ERROR  # hide INFO/WARNING logs
"""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

try:
    # Works with `python -m src.main` from the project root.
    from src.logging_config import configure_logging, get_logger, log_event
    from src.recommender import recommend_songs
    from src.validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs
except ImportError:
    # Works with `python src/main.py`.
    from logging_config import configure_logging, get_logger, log_event
    from recommender import recommend_songs
    from validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs


WIDTH = 60
CATALOG_PATH = "data/songs.csv"

EXIT_OK = 0
EXIT_INVALID_INPUT = 1
EXIT_UNEXPECTED_ERROR = 2

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


def print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def recommend_for_profile(user_prefs: Dict, songs: List[Dict], k: int = 5, profile_name: str = "default") -> list:
    """Validate a profile, then score it with the unchanged recommend_songs()."""
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
    return recommendations


def run_stress_test(songs: list) -> int:
    """Run every stress profile; an invalid profile is reported and skipped."""
    failures = 0
    for number, (name, user_prefs) in enumerate(STRESS_PROFILES.items(), start=1):
        title = f"STRESS TEST {number}: {name}"
        try:
            recommendations = recommend_for_profile(user_prefs, songs, k=5, profile_name=name)
        except ValidationError as exc:
            failures += 1
            print_error(f"{title}: {exc}")
            continue
        print_profile(user_prefs, title=title)
        print_recommendations(recommendations)
        print()
    return EXIT_INVALID_INPUT if failures else EXIT_OK


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
        recommendations = recommend_for_profile(prefs, songs, k=5)
    except ValidationError as exc:
        print_error(str(exc))
        return EXIT_INVALID_INPUT

    print_profile(prefs)
    print_recommendations(recommendations)
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
