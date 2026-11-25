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
    monkeypatch.setattr(sys, "argv", ["src.main"])
    assert main_module.main() == 0
    assert "1. Sunrise City - Neon Echo" in capsys.readouterr().out
    assert events(logs) == [
        "app_started",
        "dataset_loaded",
        "dataset_validation_completed",
        "preferences_validated",
        "scoring_completed",
        "app_finished",
    ]
    assert all(r.levelno == logging.INFO for r in logs.records if r.name == LOGGER_NAME)


def test_stress_mode_validates_every_profile_before_scoring(capsys, logs, scoring_spy):
    assert main_module.main(["--stress"]) == 0
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

    assert main_module.main(["--stress"]) == main_module.EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert len(scoring_spy) == 4
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
