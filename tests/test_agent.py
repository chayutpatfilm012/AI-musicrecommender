"""Tests for src/agent.py and the diverse-policy checks in src/evaluator.py."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src import main as main_module
from src.agent import (
    ACT, BLOCK, CHECK, CORRECT, DECIDE, MAX_CORRECTIONS, OUTPUT, PLAN, RECHECK,
    AgentBlockedError, RecommendationAgent, select_diverse, trace_to_json,
)
from src.evaluator import (
    DIVERSE_INTEGRITY_CHECKS, DIVERSE_POLICY, INTEGRITY_CHECKS, STANDARD_POLICY,
    EvaluationConfig, evaluate_recommendations,
)
from src.main import DEFAULT_PROFILE, STRESS_PROFILES
from src.recommender import load_songs, recommend_songs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALL_PROFILES = {"Default": DEFAULT_PROFILE, **STRESS_PROFILES}
DIVERSE = EvaluationConfig(ranking_policy=DIVERSE_POLICY)

# Actual diverse results (catalog ids), verified against the real catalog.
EXPECTED_DIVERSE_IDS = {
    "Default": [1, 5, 10, 17, 3],                  # Night Drive Loop (#8, Neon Echo) -> Storm Runner (#3)
    "High-Energy Pop": [1, 5, 10, 3, 19],          # already diverse
    "Chill Lofi": [4, 2, 6, 7, 15],                # Focus Flow (#9, LoRoom) -> Winter Nocturne (#15)
    "Intense Rock": [3, 5, 19, 13, 1],             # already diverse
    "Conflicting Preferences": [13, 15, 2, 4, 6],  # already diverse
}
CORRECTED_PROFILES = {"Default", "Chill Lofi"}


@pytest.fixture(scope="module")
def catalog():
    return load_songs("data/songs.csv")


def ids(recs):
    return [entry[0]["id"] for entry in recs]


def stages(trace):
    return [event.stage for event in trace]


def make_song(song_id, artist, energy=0.5, **fields):
    song = {"id": song_id, "title": f"Song {song_id}", "artist": artist, "genre": "pop", "mood": "happy",
            "energy": energy, "tempo_bpm": 100.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5}
    song.update(fields)
    return song


class CountingScorer:
    """Wraps recommend_songs; optionally corrupts specific calls."""

    def __init__(self, corrupt=None):
        self.calls = []
        self.corrupt = corrupt

    def __call__(self, prefs, songs, k=5):
        self.calls.append(k)
        recs = recommend_songs(prefs, songs, k=k)
        return self.corrupt(recs, k, len(songs)) if self.corrupt else recs


def inflate_top(recs, k, n):
    song, _, explanation = recs[0]
    return [(song, 99.0, explanation)] + recs[1:]


# ---------------------------------------------------------------------------
# 1-2, 5. Standard vs diverse results on the real catalog
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(ALL_PROFILES))
def test_standard_mode_preserves_original_rankings(name, catalog):
    prefs = ALL_PROFILES[name]
    result = RecommendationAgent(catalog, STANDARD_POLICY).run(prefs, name)
    assert result.recommendations == recommend_songs(prefs, catalog, k=5)
    assert not result.corrected
    assert result.evaluation.passed and tuple(result.evaluation.checks) == INTEGRITY_CHECKS


@pytest.mark.parametrize("name", list(ALL_PROFILES))
def test_diverse_mode_returns_expected_unique_artists(name, catalog):
    result = RecommendationAgent(catalog, DIVERSE_POLICY).run(ALL_PROFILES[name], name)
    assert ids(result.recommendations) == EXPECTED_DIVERSE_IDS[name]
    artists = [e[0]["artist"].strip().lower() for e in result.recommendations]
    assert len(artists) == len(set(artists)) == 5
    assert result.corrected == (name in CORRECTED_PROFILES)
    assert result.evaluation.passed and tuple(result.evaluation.checks) == DIVERSE_INTEGRITY_CHECKS
    assert "repeated_artist" not in [i.code for i in result.evaluation.warnings]


@pytest.mark.parametrize("name", sorted(CORRECTED_PROFILES))
def test_correction_keeps_original_scores_explanations_and_order(name, catalog):
    prefs = ALL_PROFILES[name]
    full = {e[0]["id"]: e for e in recommend_songs(prefs, catalog, k=len(catalog))}
    result = RecommendationAgent(catalog, DIVERSE_POLICY).run(prefs, name)
    for song, score, explanation in result.recommendations:
        assert (song, score, explanation) == full[song["id"]]  # identical, not recomputed or rounded
    scores = [score for _, score, _ in result.recommendations]
    assert scores == sorted(scores, reverse=True)


def test_correction_selects_songs_from_outside_the_initial_top_five(catalog):
    result = RecommendationAgent(catalog, DIVERSE_POLICY).run(DEFAULT_PROFILE)
    assert 3 not in ids(result.initial_recommendations)  # Storm Runner is standard rank 6
    assert ids(recommend_songs(DEFAULT_PROFILE, catalog, k=6))[5] == 3
    assert 3 in ids(result.recommendations) and 8 not in ids(result.recommendations)


def test_agent_does_not_mutate_preferences_or_catalog(catalog):
    prefs = dict(STRESS_PROFILES["Chill Lofi"])
    catalog_copy = copy.deepcopy(catalog)
    RecommendationAgent(catalog, DIVERSE_POLICY).run(prefs)
    assert prefs == STRESS_PROFILES["Chill Lofi"]
    assert catalog == catalog_copy


def test_invalid_policy_is_rejected(catalog):
    with pytest.raises(ValueError, match="policy must be one of"):
        RecommendationAgent(catalog, "random")


# ---------------------------------------------------------------------------
# 3, 12-13. Diversity policy details (small catalogs)
# ---------------------------------------------------------------------------

def test_artist_names_are_compared_case_insensitively():
    songs = [make_song(1, "The Band", 0.5), make_song(2, "  the BAND ", 0.5), make_song(3, "Other", 0.4)]
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.5}
    result = RecommendationAgent(songs, DIVERSE_POLICY, k=2).run(prefs)
    assert ids(result.recommendations) == [1, 3]
    assert result.corrected


def test_insufficient_unique_artists_returns_shorter_list_with_warning():
    songs = [make_song(1, "A", 0.5), make_song(2, "A", 0.6), make_song(3, "B", 0.7), make_song(4, "b ", 0.4)]
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.5}
    result = RecommendationAgent(songs, DIVERSE_POLICY, k=5).run(prefs)
    # Best song of each artist: A -> #1 (4.5); "B"/"b " -> #4 (4.4) beats #3 (4.3). Nothing invented.
    assert ids(result.recommendations) == [1, 4]
    assert result.evaluation.passed
    warning = [i for i in result.evaluation.warnings if i.code == "fewer_than_requested"]
    assert warning and "only 2 distinct artist(s)" in warning[0].message


def test_tied_scores_keep_catalog_order():
    songs = [make_song(1, "A"), make_song(2, "A"), make_song(3, "B"), make_song(4, "C")]
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.5}  # every song scores 4.5
    assert ids(RecommendationAgent(songs, DIVERSE_POLICY, k=3).run(prefs).recommendations) == [1, 3, 4]
    reversed_songs = list(reversed(songs))
    assert ids(RecommendationAgent(reversed_songs, DIVERSE_POLICY, k=3).run(prefs).recommendations) == [4, 3, 2]


def test_select_diverse_keeps_entries_unchanged():
    ranked = [({"id": 1, "artist": "A"}, 3.0, "x"), ({"id": 2, "artist": "a"}, 2.0, "y"),
              ({"id": 3, "artist": "B"}, 1.0, "z")]
    selected = select_diverse(ranked, k=5)
    assert selected == [ranked[0], ranked[2]]
    assert selected[0] is ranked[0]


# ---------------------------------------------------------------------------
# 6-8, 16. Decisions and execution traces
# ---------------------------------------------------------------------------

def test_no_correction_when_list_is_already_diverse(catalog):
    scorer = CountingScorer()
    result = RecommendationAgent(catalog, DIVERSE_POLICY, scorer=scorer).run(STRESS_PROFILES["Intense Rock"])
    assert not result.corrected
    assert result.recommendations is result.initial_recommendations
    assert scorer.calls == [5]  # no full-catalog re-ranking
    assert stages(result.trace) == [PLAN, ACT, CHECK, DECIDE, RECHECK, OUTPUT]
    decide = result.trace[3]
    assert decide.details == {"correction": False, "reason": "every artist is already unique"}


def test_repeated_artists_trigger_one_correction_and_a_recheck(catalog):
    scorer = CountingScorer()
    result = RecommendationAgent(catalog, DIVERSE_POLICY, scorer=scorer).run(DEFAULT_PROFILE)
    assert stages(result.trace) == [PLAN, ACT, CHECK, DECIDE, CORRECT, RECHECK, OUTPUT]
    assert scorer.calls == [5, len(catalog)]  # ACT, then one full ranking for CORRECT

    check, decide, correct, recheck = result.trace[2], result.trace[3], result.trace[4], result.trace[5]
    assert check.details["passed"] is True and check.details["repeated_artist_ranks"] == [1, 5]
    assert decide.details["correction"] is True
    assert correct.details["removed_ids"] == [8] and correct.details["added_ids"] == [3]
    assert correct.details["pass_number"] == 1
    assert recheck.details == {"passed": True, "critical": [], "warnings": ["low_match"]}

    # The corrected list was evaluated again, under the diverse rules.
    assert result.evaluation is not result.initial_evaluation
    assert result.evaluation.policy == DIVERSE_POLICY
    assert "repeated_artist" in [i.code for i in result.initial_evaluation.warnings]


def test_standard_mode_trace_has_no_correction(catalog):
    result = RecommendationAgent(catalog, STANDARD_POLICY).run(DEFAULT_PROFILE)
    assert stages(result.trace) == [PLAN, ACT, CHECK, DECIDE, OUTPUT]
    assert result.trace[3].details["reason"] == "standard policy keeps the original ranking"


def test_trace_serializes_to_json_without_preference_values(catalog):
    result = RecommendationAgent(catalog, DIVERSE_POLICY).run({"genre": "zz-genre", "mood": "zz-mood", "energy": 0.8})
    data = json.loads(trace_to_json(result.trace))
    assert [e["stage"] for e in data] == stages(result.trace)
    assert [e["step"] for e in data] == list(range(1, len(data) + 1))
    text = json.dumps(data) + "\n".join(e.format() for e in result.trace)
    assert "zz-" not in text and "0.8" not in text


# ---------------------------------------------------------------------------
# 9-11. Blocking and the one-pass limit
# ---------------------------------------------------------------------------

def test_corrupted_initial_list_is_blocked_without_re_ranking(catalog):
    scorer = CountingScorer(corrupt=inflate_top)
    with pytest.raises(AgentBlockedError) as exc_info:
        RecommendationAgent(catalog, DIVERSE_POLICY, scorer=scorer).run(DEFAULT_PROFILE)
    error = exc_info.value
    assert error.stage == CHECK
    assert stages(error.trace) == [PLAN, ACT, CHECK, BLOCK]
    assert scorer.calls == [5]  # never tried to hide the bad score by re-ranking
    assert {"score_out_of_range", "score_mismatch"} <= {i.code for i in error.evaluation.critical}


def test_failed_correction_is_blocked_after_exactly_one_pass(catalog):
    def corrupt_full_ranking(recs, k, n):
        if k != n:
            return recs
        song, score, _ = recs[0]
        return [(song, score, "fabricated explanation")] + recs[1:]

    scorer = CountingScorer(corrupt=corrupt_full_ranking)
    with pytest.raises(AgentBlockedError) as exc_info:
        RecommendationAgent(catalog, DIVERSE_POLICY, scorer=scorer).run(DEFAULT_PROFILE)
    error = exc_info.value
    assert error.stage == RECHECK
    assert stages(error.trace) == [PLAN, ACT, CHECK, DECIDE, CORRECT, RECHECK, BLOCK]
    assert stages(error.trace).count(CORRECT) == MAX_CORRECTIONS == 1
    assert scorer.calls == [5, len(catalog)]  # no second correction attempt
    assert "explanation_mismatch" in [i.code for i in error.evaluation.critical]
    assert "correction limit reached" in error.trace[-1].details["reason"]


def test_malformed_full_ranking_is_blocked_not_crashed(catalog):
    scorer = CountingScorer(corrupt=lambda recs, k, n: recs if k != n else [("bad",)])
    with pytest.raises(AgentBlockedError) as exc_info:
        RecommendationAgent(catalog, DIVERSE_POLICY, scorer=scorer).run(DEFAULT_PROFILE)
    assert exc_info.value.stage == RECHECK
    assert "malformed_item" in [i.code for i in exc_info.value.evaluation.critical]


# ---------------------------------------------------------------------------
# 14-15. Policy-aware evaluator
# ---------------------------------------------------------------------------

def _diverse_list(prefs, catalog):
    return RecommendationAgent(catalog, DIVERSE_POLICY).run(prefs).recommendations


def test_diverse_evaluator_accepts_the_correct_selection(catalog):
    result = evaluate_recommendations(DEFAULT_PROFILE, _diverse_list(DEFAULT_PROFILE, catalog), catalog, 5, DIVERSE)
    assert result.passed and result.policy == DIVERSE_POLICY


def test_diverse_evaluator_rejects_repeated_artists(catalog):
    standard = recommend_songs(DEFAULT_PROFILE, catalog, k=5)  # Neon Echo at ranks 1 and 5
    result = evaluate_recommendations(DEFAULT_PROFILE, standard, catalog, 5, DIVERSE)
    assert not result.passed
    issue = [i for i in result.critical if i.code == "repeated_artist_in_diverse_list"]
    assert issue and issue[0].ranks == (1, 5)


def test_diverse_evaluator_rejects_omitted_eligible_song(catalog):
    full = recommend_songs(DEFAULT_PROFILE, catalog, k=len(catalog))
    good = _diverse_list(DEFAULT_PROFILE, catalog)
    lower = next(e for e in full if e[0]["id"] not in ids(good) and e[0]["artist"] not in
                 {g[0]["artist"] for g in good} and e[1] < good[-1][1])
    result = evaluate_recommendations(DEFAULT_PROFILE, good[:4] + [lower], catalog, 5, DIVERSE)
    codes = [i.code for i in result.critical]
    assert "eligible_song_omitted" in codes and "ineligible_song_selected" in codes
    assert "id(s) 3 were left out" in result.failure_summary()


def test_diverse_evaluator_rejects_non_best_song_of_an_artist(catalog):
    prefs = STRESS_PROFILES["Chill Lofi"]
    full = {e[0]["id"]: e for e in recommend_songs(prefs, catalog, k=len(catalog))}
    # LoRoom's best is Midnight Coding (#2, 5.365); swap in Focus Flow (#9, 4.685).
    recs = [full[4], full[9], full[6], full[7], full[15]]
    result = evaluate_recommendations(prefs, recs, catalog, 5, DIVERSE)
    assert {"eligible_song_omitted", "ineligible_song_selected"} <= {i.code for i in result.critical}


def test_diverse_evaluator_rejects_list_shorter_than_available_artists(catalog):
    result = evaluate_recommendations(DEFAULT_PROFILE, _diverse_list(DEFAULT_PROFILE, catalog)[:4], catalog, 5, DIVERSE)
    assert "result_truncated" in [i.code for i in result.critical]


def test_diverse_omission_check_cannot_be_silently_skipped(catalog):
    # require_top_scores still gates the policy-aware check, as it does in standard mode.
    good = _diverse_list(DEFAULT_PROFILE, catalog)
    swapped = good[:4] + [recommend_songs(DEFAULT_PROFILE, catalog, k=20)[-1]]
    strict = evaluate_recommendations(DEFAULT_PROFILE, swapped, catalog, 5, DIVERSE)
    assert "eligible_song_omitted" in [i.code for i in strict.critical]
    assert DIVERSE.require_top_scores is True


def test_invalid_ranking_policy_config_is_rejected():
    with pytest.raises(ValueError, match="ranking_policy"):
        EvaluationConfig(ranking_policy="shuffle")


# ---------------------------------------------------------------------------
# 17-18. Application integration
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_runs(monkeypatch):
    """Record every agent run made by the application."""
    runs = []
    real = main_module.RecommendationAgent

    class SpyAgent(real):
        def run(self, user_prefs, profile_name="default"):
            runs.append((profile_name, self.policy))
            return super().run(user_prefs, profile_name)

    monkeypatch.setattr(main_module, "RecommendationAgent", SpyAgent)
    return runs


def test_default_workflow_uses_agent_in_diverse_mode_by_default(agent_runs, capsys):
    assert main_module.main(["--log-level", "ERROR"]) == 0
    assert agent_runs == [("default", DIVERSE_POLICY)]
    out = capsys.readouterr().out
    assert "5. Storm Runner - Voltline" in out
    assert "  - removed #8 Night Drive Loop (Neon Echo, 0.95)" in out
    assert "  + added   #3 Storm Runner (Voltline, 0.89)" in out
    assert "Integrity: PASSED (10 checks)" in out


def test_stress_workflow_uses_agent_for_every_profile(agent_runs, capsys):
    assert main_module.main(["--stress", "--mode", "standard", "--log-level", "ERROR"]) == 0
    assert agent_runs == [(name, STANDARD_POLICY) for name in STRESS_PROFILES]
    out = capsys.readouterr().out
    assert out.count("Ranking policy: standard") == 4
    assert "Execution trace" not in out  # only with --trace


def test_stress_diverse_trace_shows_each_profile(capsys):
    assert main_module.main(["--stress", "--mode", "diverse", "--trace", "--log-level", "ERROR"]) == 0
    out = capsys.readouterr().out
    assert out.count("Execution trace (actual agent steps)") == 4
    assert out.count("[CORRECT]") == 1  # only Chill Lofi repeats an artist
    assert "removed_ids=9 added_ids=15" in out
    assert out.count("Diversity correction: not needed") == 3


def test_blocked_run_prints_trace_but_not_the_list(monkeypatch, capsys):
    real = main_module.recommend_songs
    monkeypatch.setattr(main_module, "recommend_songs", lambda p, s, k=5: inflate_top(real(p, s, k=k), k, len(s)))
    assert main_module.main(["--trace", "--log-level", "ERROR"]) == main_module.EXIT_RECOMMENDATION_BLOCKED
    captured = capsys.readouterr()
    assert "Top 5 recommendations" not in captured.out
    assert "[BLOCK] block recommendations" in captured.out
    assert "Error: Recommendations blocked:" in captured.err


@pytest.mark.parametrize(
    "args, expected_rank5",
    [
        (["--mode", "standard"], "5. Night Drive Loop - Neon Echo"),
        (["--mode", "diverse", "--trace"], "5. Storm Runner - Voltline"),
    ],
)
def test_cli_modes_end_to_end(args, expected_rank5):
    result = subprocess.run(
        [sys.executable, "-m", "src.main", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert expected_rank5 in result.stdout
    assert "1. Sunrise City - Neon Echo" in result.stdout
    assert ("[RECHECK]" in result.stdout) == ("--trace" in args)
    assert "event=app_finished exit_code=0" in result.stderr
