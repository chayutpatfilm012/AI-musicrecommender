"""Tests for src/evaluate.py, the evaluation harness."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src import evaluate as ev
from src.evaluator import DIVERSE_POLICY, STANDARD_POLICY
from src.recommender import load_songs, recommend_songs

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def catalog():
    return load_songs("data/songs.csv")


@pytest.fixture(scope="module")
def report(catalog):
    return ev.build_report(catalog)


def run_of(report, profile, policy):
    return next(r for r in report["runs"] if r["profile"] == profile and r["policy"] == policy)


# ---------------------------------------------------------------------------
# Metric calculations
# ---------------------------------------------------------------------------

def test_artist_counting_uses_agent_normalization():
    recs = [({"id": 1, "artist": "LoRoom"}, 1.0, ""), ({"id": 2, "artist": " loroom "}, 1.0, ""),
            ({"id": 3, "artist": "Other"}, 1.0, "")]
    assert ev.count_unique_artists(recs) == 2


def test_songs_replaced_counts_removed_initial_songs():
    initial = [({"id": i}, 0, "") for i in (1, 2, 3)]
    final = [({"id": i}, 0, "") for i in (1, 3, 9)]
    assert ev.songs_replaced(initial, final) == 1


def test_run_metrics_match_the_underlying_results(catalog):
    record = ev.run_profile("Chill Lofi", ev.PROFILES["Chill Lofi"], STANDARD_POLICY, catalog)
    ref = recommend_songs(ev.PROFILES["Chill Lofi"], catalog, k=5)
    scores = [e[1] for e in ref]
    assert record.song_ids == [e[0]["id"] for e in ref]
    assert record.scores == scores
    assert record.max_score == 5.5
    assert record.avg_raw_score == pytest.approx(sum(scores) / 5)
    # Normalized from unrounded scores (e.g. 5.365, not the printed 5.37).
    assert record.avg_match_pct == pytest.approx(sum(s / 5.5 * 100 for s in scores) / 5)
    assert record.top_match_pct == pytest.approx(scores[0] / 5.5 * 100)
    assert record.low_match_count == sum(1 for s in scores if s / 5.5 < 0.6)
    assert record.unique_artists == 4 and record.returned == 5
    assert "repeated_artist" in record.warning_codes


# ---------------------------------------------------------------------------
# Standard vs diverse, using the real agent and evaluator
# ---------------------------------------------------------------------------

def test_every_profile_is_run_under_both_policies(report):
    keys = [(r["profile"], r["policy"]) for r in report["runs"]]
    assert keys == [(p, pol) for p in ev.PROFILES for pol in (STANDARD_POLICY, DIVERSE_POLICY)]
    assert all(r["status"] == "ok" and r["integrity_passed"] for r in report["runs"])
    assert {r["checks"] for r in report["runs"] if r["policy"] == STANDARD_POLICY} == {9}
    assert {r["checks"] for r in report["runs"] if r["policy"] == DIVERSE_POLICY} == {10}


def test_comparison_deltas_agree_with_runs(report):
    for comparison in report["comparisons"]:
        std = run_of(report, comparison["profile"], STANDARD_POLICY)
        div = run_of(report, comparison["profile"], DIVERSE_POLICY)
        assert comparison["unique_artists_delta"] == div["unique_artists"] - std["unique_artists"]
        assert comparison["avg_raw_score_delta"] == pytest.approx(div["avg_raw_score"] - std["avg_raw_score"])
        assert comparison["songs_changed"] == len(set(std["song_ids"]) - set(div["song_ids"]))
        assert comparison["diverse_corrected"] == div["corrected"]
    corrected = {c["profile"] for c in report["comparisons"] if c["diverse_corrected"]}
    assert corrected == {"Default", "Chill Lofi"}


def test_blocked_and_invalid_runs_are_recorded_not_raised(catalog):
    blocked = ev.run_profile("x", ev.PROFILES["Default"], DIVERSE_POLICY, catalog,
                             scorer=ev._CountingScorer(corrupt=ev._inflate_top_score))
    invalid = ev.run_profile("y", {"genre": "pop"}, DIVERSE_POLICY, catalog)
    assert blocked.status == "blocked" and blocked.trace[-1].startswith("BLOCK")
    assert invalid.status == "invalid" and "energy is required" in invalid.error
    rows = ev.compare_policies([blocked, invalid])
    assert all(not row["comparable"] for row in rows)


# ---------------------------------------------------------------------------
# Scenarios: expected rejections pass, unexpected outcomes fail
# ---------------------------------------------------------------------------

def test_all_predefined_scenarios_pass(report):
    results = report["scenarios"]
    assert len(results) == 12
    failed = [s for s in results if not s["passed"]]
    assert failed == []
    rejections = [s for s in results if s["expected"] == "rejected before scoring"]
    assert len(rejections) == 3 and all(s["passed"] for s in rejections)
    assert [s["number"] for s in results if s["simulated"]] == [10, 11]


def test_accepted_invalid_input_is_reported_as_failure(catalog):
    # If validation let bad input through, the rejection scenario must FAIL.
    passed, observed = ev._rejection({"genre": "pop", "mood": "happy", "energy": 0.5}, catalog, "energy")
    assert not passed and "expected rejection, got status=ok" in observed


def test_unexpected_scenario_failures_and_crashes_are_reported(catalog, report):
    def crash(c, r):
        raise RuntimeError("boom")

    scenarios = [
        ev.Scenario("always fails", "pass", lambda c, r: (False, "observed something else")),
        ev.Scenario("crashes", "pass", crash),
    ]
    runs = [ev.RunRecord(**r) for r in report["runs"]]
    results = ev.run_scenarios(catalog, runs, scenarios)
    assert [r.passed for r in results] == [False, False]
    assert results[1].observed == "unexpected RuntimeError: boom"
    summary = ev.summarize(runs, results)
    assert summary["scenarios"]["failed"] == 2 and summary["scenarios"]["pass_rate_pct"] == 0.0
    assert ev.exit_code_for(runs, results) == ev.EXIT_UNEXPECTED


def test_blocked_normal_run_gives_nonzero_exit_code(report):
    runs = [ev.RunRecord(**r) for r in report["runs"]]
    runs[0] = ev.RunRecord(runs[0].profile, runs[0].policy, "blocked", error="simulated")
    assert ev.exit_code_for(runs, []) == ev.EXIT_UNEXPECTED
    assert ev.exit_code_for([ev.RunRecord(**r) for r in report["runs"]], []) == ev.EXIT_OK


# ---------------------------------------------------------------------------
# Aggregates and denominators
# ---------------------------------------------------------------------------

def test_summary_uses_separate_denominators(report):
    summary = report["summary"]
    assert summary["profiles_evaluated"] == 5
    assert summary["recommendation_runs"] == 10 and summary["valid_recommendation_runs"] == 10
    for policy in (STANDARD_POLICY, DIVERSE_POLICY):
        p = summary["policies"][policy]
        own = [r for r in report["runs"] if r["policy"] == policy]
        assert p["runs"] == 5 and p["integrity_passed"] == 5
        assert p["songs_returned"] == sum(r["returned"] for r in own)
        assert p["low_match_songs"] == sum(r["low_match_count"] for r in own)
        assert p["avg_unique_artists"] == pytest.approx(sum(r["unique_artists"] for r in own) / 5)
        assert p["mean_avg_match_pct"] == pytest.approx(sum(r["avg_match_pct"] for r in own) / 5)
        assert "mean_avg_raw_score" not in p  # raw scores are not aggregated across profiles
    diverse = summary["policies"][DIVERSE_POLICY]
    assert diverse["corrected_runs"] == 2 and diverse["corrected_pct"] == pytest.approx(40.0)
    assert diverse["lists_with_repeated_artists"] == 0
    assert summary["policies"][STANDARD_POLICY]["lists_with_repeated_artists"] == 2
    scenarios = summary["scenarios"]
    assert (scenarios["total"], scenarios["passed"], scenarios["failed"]) == (12, 12, 0)
    assert "not a measure of recommendation accuracy" in scenarios["note"]


# ---------------------------------------------------------------------------
# Determinism, JSON, and the CLI
# ---------------------------------------------------------------------------

def test_reports_are_deterministic(catalog, report):
    assert ev.to_json(ev.build_report(catalog)) == ev.to_json(report)


def test_json_is_valid_and_free_of_volatile_or_private_data(report):
    text = ev.to_json(report)
    data = json.loads(text)
    assert data["catalog"] == {"path": "data/songs.csv", "songs": 20, "distinct_artists": 18}
    assert data["exit_code"] == 0
    assert str(PROJECT_ROOT) not in text and "Users" not in text
    assert "timestamp" not in text and "asctime" not in text


def test_text_report_labels_metrics_honestly(report):
    text = ev.render_text(report)
    assert "not confidence, accuracy, or predicted satisfaction" in text
    assert "expected rejections and blocks count as PASS" in text
    assert "SIMULATED: corrupted score is blocked" in text
    assert "Scenarios: 12/12 passed, 0 failed (100%; 2 simulated)" in text


@pytest.mark.parametrize("args", [[], ["--format", "json"]])
def test_cli_runs_end_to_end(args):
    result = subprocess.run([sys.executable, "-m", "src.evaluate", *args], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    if args:
        data = json.loads(result.stdout)  # stdout is pure JSON; progress and logs are on stderr
        assert data["summary"]["scenarios"]["passed"] == 12
        assert "Loading songs from" in result.stderr
    else:
        assert result.stdout.startswith("VibeFinder 2.0 evaluation harness")
        assert "Exit code: 0" in result.stdout


def test_cli_returns_catalog_error_code(monkeypatch, capsys):
    def missing(*_args, **_kwargs):
        raise ev.DatasetError([("catalog", "song catalog not found: data/songs.csv")])

    monkeypatch.setattr(ev, "load_validated_songs", missing)
    assert ev.main([]) == ev.EXIT_CATALOG_ERROR
    assert "song catalog not found" in capsys.readouterr().err
