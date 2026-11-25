"""
Evaluation harness for VibeFinder 2.0.

Runs the real application path (catalog validation, preference validation,
recommendation agent, reliability evaluator) for every predefined listener
profile under both ranking policies, then runs a fixed set of behavioral
scenarios with explicit expected outcomes.

    python -m src.evaluate                 # readable terminal report
    python -m src.evaluate --format json   # machine-readable JSON on stdout

Everything reported is computed from the runs made here; nothing is copied
from earlier reports. Output is deterministic: no timestamps, no absolute
paths. Logs go to stderr (default level ERROR; use --log-level INFO for all).

Metric notes
------------
* "Match %" is raw score / maximum possible score for the profile's active
  preferences (4.5, 5.0, or 5.5). It is a heuristic share of the weighted
  preferences a song meets, not a confidence, accuracy, or prediction of
  listener satisfaction.
* Raw scores are only compared within a profile (standard vs diverse), where
  the maximum is the same. Cross-profile aggregates use match % instead.
* Integrity checks (is the list trustworthy?) are reported separately from
  quality metrics (how good a fit is it?).

Exit codes: 0 when every recommendation run passes integrity and every
scenario behaves as expected; 1 when anything unexpected happens; 2 when the
catalog cannot be loaded.
"""

import argparse
import contextlib
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from statistics import mean
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

try:
    from src.agent import AgentBlockedError, AgentResult
    from src.evaluator import (
        DIVERSE_POLICY, LOW_MATCH, RANKING_POLICIES, STANDARD_POLICY, RecommendationBlockedError, artist_key,
    )
    from src.logging_config import configure_logging
    from src.main import CATALOG_PATH, DEFAULT_PROFILE, STRESS_PROFILES, recommend_for_profile
    from src.recommender import recommend_songs
    from src.validation import DatasetError, ValidationError, load_validated_songs, validate_songs
except ImportError:
    from agent import AgentBlockedError, AgentResult
    from evaluator import (
        DIVERSE_POLICY, LOW_MATCH, RANKING_POLICIES, STANDARD_POLICY, RecommendationBlockedError, artist_key,
    )
    from logging_config import configure_logging
    from main import CATALOG_PATH, DEFAULT_PROFILE, STRESS_PROFILES, recommend_for_profile
    from recommender import recommend_songs
    from validation import DatasetError, ValidationError, load_validated_songs, validate_songs


K = 5
PROFILES: Dict[str, Dict] = {"Default": DEFAULT_PROFILE, **STRESS_PROFILES}
POLICIES = (STANDARD_POLICY, DIVERSE_POLICY)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CATALOG_ERROR = 2

SCENARIO_PASS_NOTE = (
    "A 100% scenario pass rate means every predefined scenario behaved as expected; "
    "it is not a measure of recommendation accuracy."
)
MATCH_NOTE = (
    "Match % = raw score / maximum possible score for the profile (a heuristic share of "
    "weighted preferences met; not confidence, accuracy, or predicted satisfaction)."
)


# ---------------------------------------------------------------------------
# Recommendation runs
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    profile: str
    policy: str
    status: str  # "ok", "blocked", or "invalid"
    song_ids: List[Any] = field(default_factory=list)
    titles: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    returned: int = 0
    unique_artists: int = 0
    max_score: float = 0.0
    avg_raw_score: float = 0.0
    avg_match_pct: float = 0.0
    top_match_pct: float = 0.0
    low_match_count: int = 0
    corrected: bool = False
    replaced: int = 0
    integrity_passed: bool = False
    checks: int = 0
    warning_codes: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)  # "STAGE: action" per step
    error: str = ""


def count_unique_artists(recommendations: Sequence) -> int:
    """Distinct artists under the agent's normalization (case/whitespace-insensitive)."""
    return len({artist_key(entry[0]["artist"]) for entry in recommendations})


def songs_replaced(initial: Sequence, final: Sequence) -> int:
    final_ids = {entry[0]["id"] for entry in final}
    return sum(1 for entry in initial if entry[0]["id"] not in final_ids)


def record_from_result(profile: str, policy: str, result: AgentResult) -> RunRecord:
    recs, evaluation = result.recommendations, result.evaluation
    match_pcts = [song.match_percent for song in evaluation.songs]  # from unrounded raw scores
    return RunRecord(
        profile=profile,
        policy=policy,
        status="ok",
        song_ids=[e[0]["id"] for e in recs],
        titles=[e[0]["title"] for e in recs],
        scores=[e[1] for e in recs],
        returned=len(recs),
        unique_artists=count_unique_artists(recs),
        max_score=evaluation.max_score,
        avg_raw_score=mean(e[1] for e in recs) if recs else 0.0,
        avg_match_pct=mean(match_pcts) if match_pcts else 0.0,
        top_match_pct=match_pcts[0] if match_pcts else 0.0,
        low_match_count=sum(1 for s in evaluation.songs if s.match_level == LOW_MATCH),
        corrected=result.corrected,
        replaced=songs_replaced(result.initial_recommendations, recs),
        integrity_passed=evaluation.passed,
        checks=len(evaluation.checks),
        warning_codes=[i.code for i in evaluation.warnings],
        trace=[f"{e.stage}: {e.action}" for e in result.trace],
    )


def run_profile(
    profile: str, prefs: Mapping, policy: str, catalog: Sequence, scorer: Optional[Callable] = None,
) -> RunRecord:
    """One run through the real application path; never raises for expected failures."""
    try:
        result = recommend_for_profile(dict(prefs), catalog, k=K, profile_name=profile, mode=policy, scorer=scorer)
    except ValidationError as exc:
        return RunRecord(profile, policy, "invalid", error=str(exc))
    except RecommendationBlockedError as exc:
        trace = [f"{e.stage}: {e.action}" for e in exc.trace] if isinstance(exc, AgentBlockedError) else []
        return RunRecord(profile, policy, "blocked", error=str(exc), trace=trace,
                         checks=len(exc.evaluation.checks))
    return record_from_result(profile, policy, result)


def run_all_profiles(catalog: Sequence, profiles: Mapping[str, Mapping] = PROFILES) -> List[RunRecord]:
    return [run_profile(name, prefs, policy, catalog) for name, prefs in profiles.items() for policy in POLICIES]


def compare_policies(runs: Sequence[RunRecord]) -> List[Dict[str, Any]]:
    """Per-profile standard vs diverse deltas (raw scores share a maximum within a profile)."""
    by_key = {(r.profile, r.policy): r for r in runs}
    rows = []
    for profile in dict.fromkeys(r.profile for r in runs):
        std, div = by_key.get((profile, STANDARD_POLICY)), by_key.get((profile, DIVERSE_POLICY))
        if not std or not div or std.status != "ok" or div.status != "ok":
            rows.append({"profile": profile, "comparable": False})
            continue
        rows.append({
            "profile": profile,
            "comparable": True,
            "max_score": std.max_score,
            "unique_artists_delta": div.unique_artists - std.unique_artists,
            "avg_raw_score_delta": div.avg_raw_score - std.avg_raw_score,
            "avg_match_pct_delta": div.avg_match_pct - std.avg_match_pct,
            "songs_changed": len(set(std.song_ids) - set(div.song_ids)),
            "diverse_corrected": div.corrected,
        })
    return rows


# ---------------------------------------------------------------------------
# Behavioral scenarios
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    number: int
    name: str
    expected: str
    observed: str
    passed: bool
    simulated: bool = False


@dataclass(frozen=True)
class Scenario:
    name: str
    expected: str
    check: Callable[[Sequence, Mapping[str, RunRecord]], "tuple[bool, str]"]
    simulated: bool = False


class _CountingScorer:
    """Wraps the real engine, counting calls and optionally corrupting the output."""

    def __init__(self, corrupt: Optional[Callable] = None):
        self.calls = 0
        self.corrupt = corrupt

    def __call__(self, prefs, songs, k=5):
        self.calls += 1
        recs = recommend_songs(prefs, songs, k=k)
        return self.corrupt(recs) if self.corrupt else recs


def _inflate_top_score(recs):
    song, _, explanation = recs[0]
    return [(song, 99.0, explanation)] + list(recs[1:])


def _rejection(prefs: Mapping, catalog, expected_field: str) -> "tuple[bool, str]":
    scorer = _CountingScorer()
    record = run_profile("scenario: invalid input", prefs, DIVERSE_POLICY, catalog, scorer=scorer)
    if record.status != "invalid":
        return False, f"expected rejection, got status={record.status}"
    if scorer.calls:
        return False, f"rejected, but the scoring engine was called {scorer.calls} time(s)"
    if expected_field not in record.error:
        return False, f"rejected for the wrong reason: {record.error}"
    return True, f"rejected before scoring: {record.error.split(': ', 1)[-1]}"


def _s_standard_preserves(catalog, runs):
    mismatched = [
        name for name, prefs in PROFILES.items()
        if runs[(name, STANDARD_POLICY)].status != "ok"
        or runs[(name, STANDARD_POLICY)].song_ids != [e[0]["id"] for e in recommend_songs(prefs, catalog, k=K)]
        or runs[(name, STANDARD_POLICY)].scores != [e[1] for e in recommend_songs(prefs, catalog, k=K)]
        or runs[(name, STANDARD_POLICY)].corrected
    ]
    if mismatched:
        return False, f"differs from recommend_songs() for: {', '.join(mismatched)}"
    return True, f"{len(PROFILES)}/{len(PROFILES)} lists identical to recommend_songs() (ids and raw scores), no correction"


def _s_diverse_unique(catalog, runs):
    bad = [name for name in PROFILES if runs[(name, DIVERSE_POLICY)].status != "ok"
           or runs[(name, DIVERSE_POLICY)].unique_artists != runs[(name, DIVERSE_POLICY)].returned
           or not runs[(name, DIVERSE_POLICY)].integrity_passed]
    if bad:
        return False, f"repeated artists or failed integrity for: {', '.join(bad)}"
    return True, f"{len(PROFILES)}/{len(PROFILES)} diverse lists have one song per artist and pass integrity"


def _correction(profile: str, expect: bool):
    def check(catalog, runs):
        run = runs[(profile, DIVERSE_POLICY)]
        if run.status != "ok":
            return False, f"run status {run.status}"
        if run.corrected != expect:
            return False, f"corrected={run.corrected}"
        if expect:
            return True, f"corrected once: {run.replaced} song(s) replaced, artists {run.unique_artists}/{run.returned}"
        return True, "no correction; trace stages: " + " > ".join(t.split(":")[0] for t in run.trace)
    return check


def _s_conflicting_warnings(catalog, runs):
    run = runs[("Conflicting Preferences", DIVERSE_POLICY)]
    needed = {"no_strong_match", "top_mood_mismatch"}
    if run.status != "ok" or not run.integrity_passed:
        return False, f"run status {run.status}"
    if not needed <= set(run.warning_codes):
        return False, f"warnings were {run.warning_codes}"
    return True, f"shown with warnings: {', '.join(run.warning_codes)} (top match {run.top_match_pct:.1f}%)"


def _s_corrupted_blocked(catalog, runs):
    scorer = _CountingScorer(corrupt=_inflate_top_score)
    record = run_profile("SIMULATED corrupted score", DEFAULT_PROFILE, DIVERSE_POLICY, catalog, scorer=scorer)
    if record.status != "blocked":
        return False, f"expected block, got status={record.status}"
    if "score_out_of_range" not in record.error and "outside" not in record.error:
        return False, f"blocked for an unexpected reason: {record.error}"
    if scorer.calls != 1:
        return False, f"scoring called {scorer.calls} times; corrupted lists must not be re-ranked"
    return True, "blocked at " + record.trace[-2].split(":")[0] + " with no re-ranking; no list returned"


SYNTHETIC_FEW_ARTISTS = [
    {"id": 1, "title": "Synthetic A1", "artist": "Artist A", "genre": "pop", "mood": "happy", "energy": 0.8,
     "tempo_bpm": 120.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5},
    {"id": 2, "title": "Synthetic A2", "artist": " artist a ", "genre": "pop", "mood": "happy", "energy": 0.7,
     "tempo_bpm": 120.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5},
    {"id": 3, "title": "Synthetic B1", "artist": "Artist B", "genre": "rock", "mood": "sad", "energy": 0.2,
     "tempo_bpm": 120.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5},
]


def _s_few_artists(catalog, runs):
    synthetic = validate_songs([dict(s) for s in SYNTHETIC_FEW_ARTISTS])  # in-memory; real catalog untouched
    record = run_profile("SIMULATED few artists", DEFAULT_PROFILE, DIVERSE_POLICY, synthetic)
    if record.status != "ok" or not record.integrity_passed:
        return False, f"run status {record.status}: {record.error}"
    if record.returned != 2 or record.unique_artists != 2 or "fewer_than_requested" not in record.warning_codes:
        return False, f"returned {record.returned} songs, warnings {record.warning_codes}"
    return True, f"valid list of {record.returned}/{K} songs (ids {record.song_ids}) with fewer_than_requested warning"


def _fingerprint(runs: Sequence[RunRecord]) -> List[tuple]:
    return [(r.profile, r.policy, r.status, tuple(r.song_ids), tuple(r.scores), r.corrected,
             tuple(r.warning_codes), tuple(r.trace)) for r in runs]


def _s_deterministic(catalog, runs):
    first = _fingerprint(runs.values())
    second = _fingerprint(run_all_profiles(catalog))
    if first != second:
        diff = [a[:2] for a, b in zip(first, second) if a != b]
        return False, f"results differed between runs for: {diff}"
    return True, f"second full run identical for {len(first)} runs (ids, raw scores, decisions, warnings, traces)"


SCENARIOS: List[Scenario] = [
    Scenario("Standard mode preserves the original ranking",
             "lists equal recommend_songs() top 5", _s_standard_preserves),
    Scenario("Diverse mode returns unique artists",
             "one song per artist, integrity passes", _s_diverse_unique),
    Scenario("Default profile triggers diversity correction",
             "corrected=True", _correction("Default", True)),
    Scenario("Chill Lofi triggers diversity correction",
             "corrected=True", _correction("Chill Lofi", True)),
    Scenario("Intense Rock needs no correction",
             "corrected=False", _correction("Intense Rock", False)),
    Scenario("Conflicting preferences produce quality warnings",
             "shown with no_strong_match + top_mood_mismatch", _s_conflicting_warnings),
    Scenario("Energy above 1 is rejected",
             "rejected before scoring",
             lambda c, r: _rejection({"genre": "pop", "mood": "happy", "energy": 1.5}, c, "energy")),
    Scenario("NaN preference is rejected",
             "rejected before scoring",
             lambda c, r: _rejection({"genre": "pop", "mood": "happy", "energy": float("nan")}, c, "energy")),
    Scenario("Empty preferences are rejected",
             "rejected before scoring", lambda c, r: _rejection({}, c, "empty")),
    Scenario("SIMULATED: corrupted score is blocked",
             "blocked, not re-ranked", _s_corrupted_blocked, simulated=True),
    Scenario("SIMULATED: too few unique artists",
             "valid shorter list + warning", _s_few_artists, simulated=True),
    Scenario("Repeated execution is deterministic",
             "identical second run", _s_deterministic),
]


def run_scenarios(catalog: Sequence, runs: Sequence[RunRecord],
                  scenarios: Sequence[Scenario] = SCENARIOS) -> List[ScenarioResult]:
    by_key = {(r.profile, r.policy): r for r in runs}
    results = []
    for number, scenario in enumerate(scenarios, start=1):
        try:
            passed, observed = scenario.check(catalog, by_key)
        except Exception as exc:  # an unexpected crash is a scenario failure, not a harness crash
            passed, observed = False, f"unexpected {type(exc).__name__}: {exc}"
        results.append(ScenarioResult(number, scenario.name, scenario.expected, observed, bool(passed),
                                      scenario.simulated))
    return results


# ---------------------------------------------------------------------------
# Summary and report
# ---------------------------------------------------------------------------

def _avg(values: Sequence[float]) -> Optional[float]:
    values = list(values)
    return float(mean(values)) if values else None  # float even when every value is an int


def summarize(runs: Sequence[RunRecord], scenarios: Sequence[ScenarioResult]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "profiles_evaluated": len({r.profile for r in runs}),
        "recommendation_runs": len(runs),
        "valid_recommendation_runs": sum(1 for r in runs if r.status == "ok" and r.integrity_passed),
        "policies": {},
    }
    for policy in POLICIES:
        own = [r for r in runs if r.policy == policy]
        ok = [r for r in own if r.status == "ok"]
        songs_total = sum(r.returned for r in ok)
        low_total = sum(r.low_match_count for r in ok)
        summary["policies"][policy] = {
            "runs": len(own),
            "integrity_passed": sum(1 for r in ok if r.integrity_passed),
            "avg_unique_artists": _avg(r.unique_artists for r in ok),
            "lists_with_repeated_artists": sum(1 for r in ok if r.unique_artists < r.returned),
            "corrected_runs": sum(1 for r in ok if r.corrected),
            "corrected_pct": (100 * sum(1 for r in ok if r.corrected) / len(ok)) if ok else None,
            # Normalized metrics only: raw scores are not comparable across profiles.
            "mean_avg_match_pct": _avg(r.avg_match_pct for r in ok),
            "mean_top_match_pct": _avg(r.top_match_pct for r in ok),
            "low_match_songs": low_total,
            "songs_returned": songs_total,
            "low_match_pct": (100 * low_total / songs_total) if songs_total else None,
        }
    passed = sum(1 for s in scenarios if s.passed)
    summary["scenarios"] = {
        "total": len(scenarios),
        "passed": passed,
        "failed": len(scenarios) - passed,
        "pass_rate_pct": (100 * passed / len(scenarios)) if scenarios else None,
        "simulated": sum(1 for s in scenarios if s.simulated),
        "note": SCENARIO_PASS_NOTE,
    }
    return summary


def exit_code_for(runs: Sequence[RunRecord], scenarios: Sequence[ScenarioResult]) -> int:
    runs_ok = all(r.status == "ok" and r.integrity_passed for r in runs)
    scenarios_ok = all(s.passed for s in scenarios)
    return EXIT_OK if runs_ok and scenarios_ok else EXIT_UNEXPECTED


def _round(value: Any, digits: int = 4) -> Any:
    """Round floats for stable, readable JSON (metrics are computed unrounded)."""
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v, digits) for v in value]
    return value


def build_report(catalog: Sequence, scenarios: Sequence[Scenario] = SCENARIOS,
                 catalog_label: str = CATALOG_PATH) -> Dict[str, Any]:
    runs = run_all_profiles(catalog)
    scenario_results = run_scenarios(catalog, runs, scenarios)
    return {
        "harness": "VibeFinder 2.0 evaluation harness",
        "catalog": {
            "path": catalog_label,
            "songs": len(catalog),
            "distinct_artists": len({artist_key(s["artist"]) for s in catalog}),
        },
        "k": K,
        "notes": {"match_pct": MATCH_NOTE, "scenarios": SCENARIO_PASS_NOTE},
        "runs": [asdict(r) for r in runs],
        "comparisons": compare_policies(runs),
        "scenarios": [asdict(s) for s in scenario_results],
        "summary": summarize(runs, scenario_results),
        "exit_code": exit_code_for(runs, scenario_results),
    }


def to_json(report: Mapping) -> str:
    return json.dumps(_round(dict(report)), indent=2, sort_keys=False)


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def _fmt(value: Optional[float], spec: str, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:{spec}}{suffix}"


def render_text(report: Mapping) -> str:
    out: List[str] = []
    line = "-" * 100
    cat = report["catalog"]
    out.append(report["harness"])
    out.append(f"Catalog: {cat['path']} ({cat['songs']} songs, {cat['distinct_artists']} distinct artists) | k={report['k']}")
    out.append(report["notes"]["match_pct"])
    out.append("")

    out.append("RECOMMENDATION RUNS (quality metrics; integrity shown separately)")
    out.append(line)
    out.append(f"{'Profile':<24}{'Policy':<10}{'Song ids':<18}{'Artists':>8}{'Avg raw':>9}{'/max':>6}"
               f"{'Avg match':>11}{'Low':>5}  {'Corrected':<10}{'Integrity':<11}Warnings")
    for r in report["runs"]:
        if r["status"] != "ok":
            out.append(f"{r['profile']:<24}{r['policy']:<10}{r['status'].upper()}: {r['error']}")
            continue
        ids = ",".join(map(str, r["song_ids"]))
        corrected = f"yes ({r['replaced']})" if r["corrected"] else "no"
        integrity = f"PASS ({r['checks']})" if r["integrity_passed"] else "FAIL"
        out.append(f"{r['profile']:<24}{r['policy']:<10}{ids:<18}{r['unique_artists']:>4}/{r['returned']:<3}"
                   f"{r['avg_raw_score']:>9.2f}{r['max_score']:>6.1f}{r['avg_match_pct']:>10.1f}%"
                   f"{r['low_match_count']:>5}  {corrected:<10}{integrity:<11}{','.join(r['warning_codes']) or '-'}")
    out.append(line)

    out.append("")
    out.append("RECOMMENDED SONGS")
    out.append(line)
    for r in report["runs"]:
        if r["status"] == "ok":
            songs = "; ".join(f"#{i} {t}" for i, t in zip(r["song_ids"], r["titles"]))
            out.append(f"{r['profile']:<24}{r['policy']:<10}{songs}")
    out.append(line)

    out.append("")
    out.append("STANDARD -> DIVERSE (same profile, so raw scores share a maximum)")
    out.append(line)
    out.append(f"{'Profile':<24}{'Artists':>9}{'Avg raw':>10}{'Avg match':>12}{'Songs changed':>15}")
    for c in report["comparisons"]:
        if not c["comparable"]:
            out.append(f"{c['profile']:<24}not comparable (a run did not complete)")
            continue
        out.append(f"{c['profile']:<24}{c['unique_artists_delta']:>+9d}{c['avg_raw_score_delta']:>+10.3f}"
                   f"{c['avg_match_pct_delta']:>+11.1f}%{c['songs_changed']:>15}")
    out.append(line)

    out.append("")
    out.append("BEHAVIORAL SCENARIOS (expected rejections and blocks count as PASS)")
    out.append(line)
    for s in report["scenarios"]:
        out.append(f"{s['number']:>2}. {'PASS' if s['passed'] else 'FAIL'}  {s['name']}")
        out.append(f"          expected: {s['expected']}")
        out.append(f"          observed: {s['observed']}")
    out.append(line)

    summary = report["summary"]
    out.append("")
    out.append("SUMMARY")
    out.append(line)
    out.append(f"Profiles evaluated: {summary['profiles_evaluated']} | recommendation runs: "
               f"{summary['recommendation_runs']} | valid runs (integrity passed): "
               f"{summary['valid_recommendation_runs']}/{summary['recommendation_runs']}")
    for policy, p in summary["policies"].items():
        out.append(
            f"{policy:<9} integrity {p['integrity_passed']}/{p['runs']} | avg unique artists "
            f"{_fmt(p['avg_unique_artists'], '.1f')} | lists with repeated artists "
            f"{p['lists_with_repeated_artists']}/{p['runs']} | corrected {p['corrected_runs']}/{p['runs']} "
            f"({_fmt(p['corrected_pct'], '.0f', '%')})"
        )
        out.append(
            f"{'':<9} mean avg match {_fmt(p['mean_avg_match_pct'], '.1f', '%')} | mean top match "
            f"{_fmt(p['mean_top_match_pct'], '.1f', '%')} | low-match songs {p['low_match_songs']}/"
            f"{p['songs_returned']} ({_fmt(p['low_match_pct'], '.0f', '%')})"
        )
    sc = summary["scenarios"]
    out.append(f"Scenarios: {sc['passed']}/{sc['total']} passed, {sc['failed']} failed "
               f"({_fmt(sc['pass_rate_pct'], '.0f', '%')}; {sc['simulated']} simulated)")
    out.append(sc["note"])
    out.append(f"Exit code: {report['exit_code']}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_catalog_quietly(csv_path: str = CATALOG_PATH) -> List[Dict]:
    """Load and validate the catalog; load_songs()'s progress line goes to stderr, not stdout."""
    with contextlib.redirect_stdout(sys.stderr):
        return load_validated_songs(csv_path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="VibeFinder 2.0 evaluation harness")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="report format (default: text)")
    parser.add_argument("--log-level", default="ERROR", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="minimum level of logs on stderr (default: ERROR)")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        catalog = load_catalog_quietly()
    except DatasetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_CATALOG_ERROR

    report = build_report(catalog)
    print(to_json(report) if args.format == "json" else render_text(report))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
