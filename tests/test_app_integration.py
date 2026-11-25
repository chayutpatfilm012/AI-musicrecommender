"""Integration tests for src/main.py: validation before scoring, safe errors, and logging."""

import logging
import math
import subprocess
import sys
from pathlib import Path

import pytest

from src import main as main_module
from src.logging_config import LOGGER_NAME, configure_logging, log_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DEFAULT = {"genre": "pop", "mood": "happy", "energy": 0.8}


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    return caplog


def events(caplog, level=None):
    return [
        r.getMessage().split()[0].removeprefix("event=")
        for r in caplog.records
        if r.name == LOGGER_NAME and (level is None or r.levelno == level)
    ]


@pytest.fixture
def scoring_spy(monkeypatch):
    """Replace the scoring engine so tests can prove whether it was called."""
    calls = []
    real = main_module.recommend_songs

    def spy(prefs, songs, k=5):
        calls.append(prefs)
        return real(prefs, songs, k=k)

    monkeypatch.setattr(main_module, "recommend_songs", spy)
    return calls


def write_bad_csv(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "id,title,artist,genre,mood,energy,tempo_bpm,valence,danceability,acousticness\n"
        "1,Song,Artist,pop,happy,loud,120,0.5,0.5,0.5\n",
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# Valid runs are unchanged
# ---------------------------------------------------------------------------

def test_default_profile_constant_matches_baseline():
    assert main_module.DEFAULT_PROFILE == BASELINE_DEFAULT


def test_main_returns_zero_and_logs_lifecycle(monkeypatch, capsys, logs):
    # Phase 5: pinned to standard mode (the VibeFinder 1.0 ranking); the agent's
    # PLAN/ACT/CHECK/DECIDE/OUTPUT steps are logged as agent_step events.
    monkeypatch.setattr(sys, "argv", ["src.main", "--mode", "standard"])
    assert main_module.main() == 0
    assert "1. Sunrise City - Neon Echo" in capsys.readouterr().out
    assert events(logs) == [
        "app_started",
        "dataset_loaded",
        "dataset_validation_completed",
        "preferences_validated",
        "agent_step",  # PLAN
        "scoring_completed",
        "agent_step",  # ACT
        # Phase 4: the evaluator runs after scoring. The default list has
        # low-match ranks and Neon Echo twice, which are WARNING-level quality notes.
        "evaluation_started",
        "low_match_detected",
        "repeated_artist_detected",
        "evaluation_completed",
        "agent_step",  # CHECK
        "agent_step",  # DECIDE (standard policy: no correction)
        "agent_step",  # OUTPUT
        "app_finished",
    ]
    assert not [r for r in logs.records if r.name == LOGGER_NAME and r.levelno >= logging.ERROR]
    assert events(logs, logging.WARNING) == ["low_match_detected", "repeated_artist_detected"]


def test_stress_mode_validates_every_profile_before_scoring(capsys, logs, scoring_spy):
    # Standard mode scores each profile exactly once (diverse mode adds one
    # full-catalog scoring call per corrected profile; see test_agent.py).
    assert main_module.main(["--stress", "--mode", "standard"]) == 0
    assert len(scoring_spy) == 4
    assert events(logs).count("preferences_validated") == 4
    assert events(logs).count("scoring_completed") == 4
    assert capsys.readouterr().out.count("STRESS TEST") == 4


def test_logs_go_to_stderr_not_stdout(capsys):
    assert main_module.main([]) == 0
    captured = capsys.readouterr()
    assert "event=" not in captured.out
    assert "INFO vibefinder event=app_started mode=default" in captured.err
    assert "event=scoring_completed profile=default candidates=20 returned=5 top_score=4.48" in captured.err


def test_log_level_flag_hides_info_logs(capsys):
    assert main_module.main(["--log-level", "ERROR"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Sunrise City" in captured.out


def test_preference_values_are_not_logged(logs):
    main_module.run(stress=False, user_prefs={"genre": "secret-genre", "mood": "secret-mood", "energy": 0.123})
    text = "\n".join(r.getMessage() for r in logs.records)
    assert "secret" not in text
    assert "0.123" not in text
    assert "fields=genre,mood,energy" in text


# ---------------------------------------------------------------------------
# Invalid preferences never reach the scoring engine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prefs",
    [
        {},
        {"genre": "pop", "mood": "happy"},
        {"genre": "", "mood": "happy", "energy": 0.8},
        {"genre": "pop", "mood": "happy", "energy": 1.5},
        {"genre": "pop", "mood": "happy", "energy": "high"},
        {"genre": "pop", "mood": "happy", "energy": math.nan},
        {"genre": "pop", "mood": "happy", "energy": True},
        {"genre": "pop", "mood": "happy", "energy": 0.8, "valence": -math.inf},
    ],
)
def test_invalid_preferences_are_blocked_before_scoring(prefs, capsys, logs, scoring_spy):
    exit_code = main_module.run(stress=False, user_prefs=prefs)
    captured = capsys.readouterr()

    assert exit_code == main_module.EXIT_INVALID_INPUT
    assert scoring_spy == []
    assert "Error: Invalid listener preferences:" in captured.err
    assert "Top 5 recommendations" not in captured.out
    assert "Traceback" not in captured.err
    assert events(logs, logging.WARNING) == ["validation_failed"]
    assert "scoring_completed" not in events(logs)


def test_invalid_stress_profile_is_reported_and_others_still_run(monkeypatch, capsys, logs, scoring_spy):
    profiles = dict(main_module.STRESS_PROFILES)
    profiles["Broken"] = {"genre": "pop", "mood": "happy", "energy": 2.0}
    monkeypatch.setattr(main_module, "STRESS_PROFILES", profiles)

    assert main_module.main(["--stress", "--mode", "standard"]) == main_module.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert len(scoring_spy) == 4  # the invalid profile never reaches scoring
    assert "Error: STRESS TEST 5: Broken: Invalid listener preferences: energy must be between 0 and 1, got 2.0" in captured.err
    assert captured.out.count("STRESS TEST") == 4
    failure = [r for r in logs.records if "validation_failed" in r.getMessage()]
    assert len(failure) == 1
    assert 'profile=Broken fields=energy problems=1' in failure[0].getMessage()


# ---------------------------------------------------------------------------
# Dataset errors are handled safely
# ---------------------------------------------------------------------------

def test_missing_catalog_is_handled_safely(tmp_path, capsys, logs, scoring_spy):
    exit_code = main_module.run(stress=False, csv_path=str(tmp_path / "missing.csv"))
    captured = capsys.readouterr()
    assert exit_code == main_module.EXIT_INVALID_INPUT
    assert scoring_spy == []
    assert "Error: Invalid song catalog: song catalog not found:" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert events(logs, logging.ERROR) == ["dataset_validation_failed"]
    # Absolute paths are logged by file name only (they may contain a username).
    message = logs.records[-1].getMessage()
    assert "path=missing.csv " in message
    assert str(tmp_path) not in message


def test_malformed_catalog_is_handled_safely(tmp_path, capsys, logs, scoring_spy):
    exit_code = main_module.run(stress=True, csv_path=write_bad_csv(tmp_path))
    captured = capsys.readouterr()
    assert exit_code == main_module.EXIT_INVALID_INPUT
    assert scoring_spy == []
    assert "line 2: energy must be a number, got 'loud'" in captured.err
    assert events(logs, logging.ERROR) == ["dataset_validation_failed"]


def test_unexpected_error_is_logged_without_traceback_on_console(monkeypatch, capsys, logs):
    def boom(*_args, **_kwargs):
        raise RuntimeError("internal detail")

    monkeypatch.setattr(main_module, "load_validated_songs", boom)
    assert main_module.main([]) == main_module.EXIT_UNEXPECTED_ERROR
    captured = capsys.readouterr()
    assert "Error: an unexpected error occurred" in captured.err
    assert "Traceback" not in captured.err  # INFO level: traceback only logged at DEBUG
    assert "internal detail" not in captured.err
    assert "app_error" in events(logs, logging.ERROR)
    assert not [r for r in logs.records if r.levelno == logging.DEBUG]

    # With --log-level DEBUG the traceback is available for troubleshooting.
    logs.clear()
    assert main_module.main(["--log-level", "DEBUG"]) == main_module.EXIT_UNEXPECTED_ERROR
    debug = [r for r in logs.records if r.levelno == logging.DEBUG]
    assert len(debug) == 1 and debug[0].exc_info[0] is RuntimeError
    assert "Traceback" in capsys.readouterr().err


def test_cli_subprocess_reports_missing_catalog_cleanly(tmp_path):
    """Real process run: the catalog path is relative to the cwd, so run from an empty folder."""
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from src import main; sys.exit(main.run(stress=False, csv_path='nowhere/songs.csv'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(PROJECT_ROOT)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "Error: Invalid song catalog: song catalog not found: nowhere/songs.csv" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_subprocess_default_run_matches_baseline():
    result = subprocess.run(
        [sys.executable, "-m", "src.main"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "event=" not in result.stdout
    assert "Score: 4.48" in result.stdout
    assert "event=app_finished exit_code=0" in result.stderr


# ---------------------------------------------------------------------------
# Phase 4: reliability evaluation in the application workflow
# ---------------------------------------------------------------------------

ORIGINAL_DEFAULT_LINES = [
    "1. Sunrise City - Neon Echo",
    "   Score: 4.48",
    "     * genre match (+2.0)",
    "5. Night Drive Loop - Neon Echo",
    "   Score: 0.95",
]


def corrupt_scores(real):
    """A scoring engine that inflates the top score beyond the profile maximum."""
    def broken(prefs, songs, k=5):
        recs = real(prefs, songs, k=k)
        song, _, explanation = recs[0]
        return [(song, 99.0, explanation)] + recs[1:]
    return broken


def test_default_output_shows_evaluation_after_original_list(capsys):
    # Standard mode: the original VibeFinder 1.0 list, with Neon Echo repeated as a warning.
    assert main_module.run(stress=False, mode="standard") == main_module.EXIT_OK
    out = capsys.readouterr().out
    for line in ORIGINAL_DEFAULT_LINES:
        assert line in out.splitlines()
    assert out.index("5. Night Drive Loop") < out.index("Reliability check")
    assert "Integrity: PASSED (9 checks)" in out
    assert "  1. Sunrise City            4.48 / 4.50   99.6%  Strong Match" in out
    assert "  ! Repeated artist: Neon Echo appears at ranks 1 and 5." in out
    assert "not a confidence level" in out


def test_stress_mode_evaluates_every_profile(capsys, logs):
    # Standard mode evaluates each list once; diverse mode adds a policy recheck.
    assert main_module.main(["--stress", "--mode", "standard"]) == main_module.EXIT_OK
    out = capsys.readouterr().out
    assert out.count("Reliability check") == 4
    assert out.count("Integrity: PASSED") == 4
    assert "max possible 5.50 for this profile" in out  # Chill Lofi
    assert "No strong match: the best recommendation reaches only 65.1%" in out  # Conflicting
    assert events(logs).count("evaluation_started") == 4
    assert events(logs).count("evaluation_completed") == 4
    assert "recommendation_blocked" not in events(logs)


def test_invalid_recommendations_are_blocked_in_default_mode(monkeypatch, capsys, logs):
    monkeypatch.setattr(main_module, "recommend_songs", corrupt_scores(main_module.recommend_songs))

    exit_code = main_module.run(stress=False)
    captured = capsys.readouterr()

    assert exit_code == main_module.EXIT_RECOMMENDATION_BLOCKED
    assert "Top 5 recommendations" not in captured.out
    assert "Sunrise City" not in captured.out
    assert "Error: Recommendations blocked: 2 integrity check failure(s):" in captured.err
    assert "rank 1: score 99.00 is outside 0-4.50 for this profile" in captured.err
    assert "rank 1: score 99.00 does not match the scoring rules (4.48)" in captured.err
    assert "Traceback" not in captured.err
    # Phase 5: the agent also records its CHECK and BLOCK steps at ERROR level.
    assert events(logs, logging.ERROR) == [
        "integrity_check_failed", "integrity_check_failed",
        "agent_step",  # CHECK failed
        "agent_step",  # BLOCK
        "recommendation_blocked",
    ]
    blocked = [r.getMessage() for r in logs.records if "recommendation_blocked" in r.getMessage()][0]
    assert "codes=score_mismatch,score_out_of_range" in blocked
    # Match stats computed from the corrupted score are not logged as if meaningful.
    completed = [r.getMessage() for r in logs.records if "evaluation_completed" in r.getMessage()][0]
    assert "passed=False" in completed and "top_match_pct=- top_level=-" in completed


def test_blocked_profile_in_stress_mode_does_not_stop_the_others(monkeypatch, capsys):
    real = main_module.recommend_songs

    def broken_for_rock(prefs, songs, k=5):
        recs = real(prefs, songs, k=k)
        return list(reversed(recs)) if prefs["genre"] == "rock" else recs

    monkeypatch.setattr(main_module, "recommend_songs", broken_for_rock)
    assert main_module.main(["--stress"]) == main_module.EXIT_RECOMMENDATION_BLOCKED
    captured = capsys.readouterr()
    assert captured.out.count("Reliability check") == 3
    assert "STRESS TEST 3: Intense Rock" not in captured.out
    assert "Error: STRESS TEST 3: Intense Rock: Recommendations blocked:" in captured.err
    assert "scores higher than rank" in captured.err


def test_invalid_input_and_blocked_results_keep_distinct_exit_codes(monkeypatch, capsys):
    profiles = dict(main_module.STRESS_PROFILES)
    profiles["Broken"] = {"genre": "pop", "mood": "happy", "energy": 2.0}
    monkeypatch.setattr(main_module, "STRESS_PROFILES", profiles)
    assert main_module.main(["--stress"]) == main_module.EXIT_INVALID_INPUT

    monkeypatch.setattr(main_module, "recommend_songs", corrupt_scores(main_module.recommend_songs))
    assert main_module.main(["--stress"]) == main_module.EXIT_RECOMMENDATION_BLOCKED  # blocked outranks invalid
    capsys.readouterr()


def test_quality_warning_logs_omit_preference_values(logs):
    prefs = {"genre": "secret-genre", "mood": "secret-mood", "energy": 0.5}
    assert main_module.run(stress=False, user_prefs=prefs) == main_module.EXIT_OK
    messages = [r.getMessage() for r in logs.records]
    assert any("code=unknown_genre" in m for m in messages)
    assert any("code=unknown_mood" in m for m in messages)
    assert not any("secret" in m for m in messages)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def test_log_event_formats_key_value_pairs(logs):
    logger = logging.getLogger(LOGGER_NAME)
    log_event(logger, logging.WARNING, "demo", name="Chill Lofi", fields=["genre", "mood"], score=5.4699, n=3, empty="")
    record = logs.records[-1]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == 'event=demo name="Chill Lofi" fields=genre,mood score=5.47 n=3 empty=""'


def test_configure_logging_is_idempotent():
    logger = configure_logging("INFO")
    configure_logging("WARNING")
    ours = [h for h in logger.handlers if type(h).__name__ == "_CurrentStderrHandler"]
    assert len(ours) == 1
    assert logger.level == logging.WARNING
    configure_logging("INFO")
