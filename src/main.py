"""
Command line runner for the Music Recommender Simulation (VibeFinder 2.0).

Loads the song catalog, validates it, and runs each listener profile through
the recommendation agent (see agent.py):

    validate preferences -> PLAN -> ACT (original scoring) -> CHECK (evaluator)
    -> DECIDE -> CORRECT (artist diversity, at most once) -> RECHECK -> OUTPUT

A list that fails an integrity check is blocked; quality warnings are shown
with it. Recommendations go to stdout; structured logs and errors go to stderr.

Usage:
    python -m src.main                            # default profile, diverse mode
    python -m src.main --mode standard            # original VibeFinder 1.0 ranking
    python -m src.main --mode diverse --trace     # show the agent's execution trace
    python -m src.main --stress [--mode ...]      # four stress-test profiles
    python -m src.main --log-level ERROR          # hide INFO/WARNING logs
"""

import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

try:
    # Works with `python -m src.main` from the project root.
    from src.agent import AgentBlockedError, AgentResult, RecommendationAgent
    from src.evaluator import DIVERSE_POLICY, RANKING_POLICIES, STANDARD_POLICY, RecommendationBlockedError
    from src.logging_config import configure_logging, get_logger, log_event
    from src.recommender import recommend_songs
    from src.validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs
except ImportError:
    # Works with `python src/main.py`.
    from agent import AgentBlockedError, AgentResult, RecommendationAgent
    from evaluator import DIVERSE_POLICY, RANKING_POLICIES, STANDARD_POLICY, RecommendationBlockedError
    from logging_config import configure_logging, get_logger, log_event
    from recommender import recommend_songs
    from validation import DatasetError, ValidationError, load_validated_songs, validate_user_prefs


WIDTH = 60
CATALOG_PATH = "data/songs.csv"
DEFAULT_MODE = DIVERSE_POLICY

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

POLICY_DESCRIPTIONS = {
    STANDARD_POLICY: "standard (original VibeFinder 1.0 top-5 ranking)",
    DIVERSE_POLICY: "diverse (highest-ranked songs, at most one per artist)",
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


def _describe_song(entry) -> str:
    song = entry[0]
    return f"#{song['id']} {song['title']} ({song['artist']}, {entry[1]:.2f})"


def print_evaluation(result: AgentResult) -> None:
    """Print the policy, any correction, and the reliability summary after the list."""
    evaluation = result.evaluation
    print("Reliability check")
    print("-" * WIDTH)
    print(f"Ranking policy: {POLICY_DESCRIPTIONS[result.policy]}")
    if result.corrected:
        final_ids = {entry[0]["id"] for entry in result.recommendations}
        initial_ids = {entry[0]["id"] for entry in result.initial_recommendations}
        removed = [e for e in result.initial_recommendations if e[0]["id"] not in final_ids]
        added = [e for e in result.recommendations if e[0]["id"] not in initial_ids]
        print(f"Diversity correction: {len(removed)} song(s) replaced to avoid repeated artists")
        for entry in removed:
            print(f"  - removed {_describe_song(entry)}")
        for entry in added:
            print(f"  + added   {_describe_song(entry)}")
    elif result.policy == DIVERSE_POLICY:
        print("Diversity correction: not needed (every artist is already unique)")
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


def print_trace(trace) -> None:
    print("Execution trace (actual agent steps)")
    print("-" * WIDTH)
    for event in trace:
        print(f"  {event.format()}")
    print("-" * WIDTH)


def print_error(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def recommend_for_profile(
    user_prefs: Dict,
    songs: List[Dict],
    k: int = 5,
    profile_name: str = "default",
    mode: str = DEFAULT_MODE,
) -> AgentResult:
    """
    Validate a profile, then run it through the recommendation agent.

    Raises ValidationError for bad input and AgentBlockedError (a
    RecommendationBlockedError) when a list fails an integrity check.
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

    # recommend_songs is looked up here so tests can substitute a faulty engine.
    agent = RecommendationAgent(songs, policy=mode, k=k, scorer=recommend_songs)
    return agent.run(prefs, profile_name=profile_name)


def present(result: AgentResult, prefs: Dict, title: str, show_trace: bool) -> None:
    print_profile(prefs, title=title)
    print_recommendations(result.recommendations)
    print_evaluation(result)
    if show_trace:
        print_trace(result.trace)


def report_blocked(exc: RecommendationBlockedError, prefix: str, show_trace: bool) -> None:
    print_error(f"{prefix}{exc}")
    if show_trace and isinstance(exc, AgentBlockedError):
        print_trace(exc.trace)


def run_stress_test(songs: list, mode: str = DEFAULT_MODE, show_trace: bool = False) -> int:
    """Run every stress profile; an invalid or blocked profile is reported and skipped."""
    exit_code = EXIT_OK
    for number, (name, user_prefs) in enumerate(STRESS_PROFILES.items(), start=1):
        title = f"STRESS TEST {number}: {name}"
        try:
            result = recommend_for_profile(user_prefs, songs, k=5, profile_name=name, mode=mode)
        except ValidationError as exc:
            exit_code = max(exit_code, EXIT_INVALID_INPUT)
            print_error(f"{title}: {exc}")
            continue
        except RecommendationBlockedError as exc:
            exit_code = max(exit_code, EXIT_RECOMMENDATION_BLOCKED)
            report_blocked(exc, f"{title}: ", show_trace)
            continue
        present(result, user_prefs, title, show_trace)
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


def run(
    stress: bool,
    csv_path: str = CATALOG_PATH,
    user_prefs: Optional[Dict] = None,
    mode: str = DEFAULT_MODE,
    show_trace: bool = False,
) -> int:
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
        return run_stress_test(songs, mode=mode, show_trace=show_trace)

    prefs = DEFAULT_PROFILE if user_prefs is None else user_prefs
    try:
        result = recommend_for_profile(prefs, songs, k=5, mode=mode)
    except ValidationError as exc:
        print_error(str(exc))
        return EXIT_INVALID_INPUT
    except RecommendationBlockedError as exc:
        report_blocked(exc, "", show_trace)
        return EXIT_RECOMMENDATION_BLOCKED

    present(result, prefs, "MUSIC RECOMMENDER", show_trace)
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Music Recommender Simulation (VibeFinder 2.0)")
    parser.add_argument(
        "--stress",
        action="store_true",
        help="run the top 5 for each stress-test profile instead of the default profile",
    )
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        choices=list(RANKING_POLICIES),
        help="ranking policy: 'diverse' (default; at most one song per artist) or "
             "'standard' (original VibeFinder 1.0 ranking)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print the agent's execution trace (plan, act, check, decide, correct, recheck)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="minimum level of log messages written to stderr (default: INFO)",
    )
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    log_event(logger, logging.INFO, "app_started", mode="stress" if args.stress else "default", policy=args.mode)

    try:
        exit_code = run(args.stress, mode=args.mode, show_trace=args.trace)
    except Exception as exc:  # last-resort guard: no raw traceback in normal CLI use
        log_event(logger, logging.ERROR, "app_error", error_type=type(exc).__name__)
        logger.debug("Traceback for unexpected error", exc_info=True)
        print_error("an unexpected error occurred; rerun with --log-level DEBUG for details")
        return EXIT_UNEXPECTED_ERROR

    log_event(logger, logging.INFO, "app_finished", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
