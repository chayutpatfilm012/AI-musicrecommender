"""
Deterministic recommendation agent for VibeFinder 2.0.

The agent wraps the unchanged scoring engine in a plan-act-check-correct loop:

    PLAN     decide k and the ranking policy (standard or diverse)
    ACT      score the catalog with recommend_songs() (unchanged)
    CHECK    run the reliability evaluator on the initial top-k list
    DECIDE   choose whether artist-diversity correction is needed, and why
    CORRECT  (at most once) select each top-ranked artist's best song from the
             full ranked catalog
    RECHECK  evaluate the final list against the active ranking policy
    OUTPUT   return the verified list, its evaluation, and the trace
    BLOCK    raised instead of OUTPUT when any check fails

Corrupted results are never "fixed" by re-ranking: if the initial list fails an
integrity check, the agent blocks immediately. Preferences are never changed.

The trace records what the program actually did (stages, decisions, song ids,
check results). It is an execution log, not a model's reasoning.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

try:
    from src.evaluator import (
        DIVERSE_POLICY, RANKING_POLICIES, STANDARD_POLICY, EvaluationConfig, EvaluationResult,
        RecommendationBlockedError, artist_key, evaluate_recommendations,
    )
    from src.logging_config import format_fields, get_logger, log_event
    from src.recommender import recommend_songs
except ImportError:
    from evaluator import (
        DIVERSE_POLICY, RANKING_POLICIES, STANDARD_POLICY, EvaluationConfig, EvaluationResult,
        RecommendationBlockedError, artist_key, evaluate_recommendations,
    )
    from logging_config import format_fields, get_logger, log_event
    from recommender import recommend_songs


MAX_CORRECTIONS = 1

PLAN, ACT, CHECK, DECIDE, CORRECT, RECHECK, OUTPUT, BLOCK = (
    "PLAN", "ACT", "CHECK", "DECIDE", "CORRECT", "RECHECK", "OUTPUT", "BLOCK",
)

# Quality-warning codes that get their own log event name.
WARNING_EVENTS = {
    "low_match": "low_match_detected",
    "no_strong_match": "low_match_detected",
    "repeated_artist": "repeated_artist_detected",
}

Scorer = Callable[..., list]
logger = get_logger()


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceEvent:
    step: int
    stage: str
    action: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def format(self) -> str:
        details = format_fields(**{k: ("-" if v in ([], ()) else v) for k, v in self.details.items()})
        return f"{self.step:>2}. [{self.stage}] {self.action}" + (f" | {details}" if details else "")


def trace_to_json(trace: Sequence[TraceEvent]) -> str:
    return json.dumps([event.to_dict() for event in trace], indent=2)


@dataclass
class AgentResult:
    recommendations: list
    evaluation: EvaluationResult
    policy: str
    corrected: bool
    initial_recommendations: list
    initial_evaluation: EvaluationResult
    trace: List[TraceEvent]


class AgentBlockedError(RecommendationBlockedError):
    """Recommendations were blocked; carries the stage and the trace so far."""

    def __init__(self, evaluation: EvaluationResult, stage: str, trace: List[TraceEvent]):
        super().__init__(evaluation)
        self.stage = stage
        self.trace = trace


# ---------------------------------------------------------------------------
# Diversity policy
# ---------------------------------------------------------------------------

def select_diverse(ranked: Sequence, k: int) -> list:
    """
    Walk a ranked list of (song, score, explanation) and keep the first song of
    each artist until k songs are chosen.

    Entries are kept as-is (same tuples, raw scores, and explanations), so the
    descending score order and the stable tie order of `ranked` carry over.
    Returns fewer than k entries when there are not enough distinct artists.
    """
    selected, seen = [], set()
    for entry in ranked:
        if len(selected) >= k:
            break
        key = artist_key(entry[0]["artist"])
        if key not in seen:
            seen.add(key)
            selected.append(entry)
    return selected


def _ids(recommendations: Sequence) -> List[Any]:
    return [entry[0].get("id") for entry in recommendations]


def _repeated_artist_issues(evaluation: EvaluationResult):
    return [i for i in evaluation.warnings if i.code == "repeated_artist"]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class RecommendationAgent:
    """Runs the plan-act-check-decide-correct-recheck workflow for one catalog."""

    def __init__(
        self,
        catalog: Sequence[Mapping],
        policy: str = DIVERSE_POLICY,
        k: int = 5,
        scorer: Optional[Scorer] = None,
        config: Optional[EvaluationConfig] = None,
    ):
        if policy not in RANKING_POLICIES:
            raise ValueError(f"policy must be one of {', '.join(RANKING_POLICIES)}")
        self.catalog = catalog
        self.policy = policy
        self.k = k
        self.scorer = scorer or recommend_songs
        base = config or EvaluationConfig()
        self.check_config = EvaluationConfig(
            strong_threshold=base.strong_threshold, moderate_threshold=base.moderate_threshold,
            score_tolerance=base.score_tolerance, require_top_scores=base.require_top_scores,
            ranking_policy=STANDARD_POLICY,
        )
        self.final_config = EvaluationConfig(
            strong_threshold=base.strong_threshold, moderate_threshold=base.moderate_threshold,
            score_tolerance=base.score_tolerance, require_top_scores=base.require_top_scores,
            ranking_policy=policy,
        )

    def run(self, user_prefs: Mapping, profile_name: str = "default") -> AgentResult:
        """Return verified recommendations, or raise AgentBlockedError."""
        trace: List[TraceEvent] = []

        def record(stage: str, action: str, level: int = logging.INFO, **details) -> None:
            event = TraceEvent(len(trace) + 1, stage, action, details)
            trace.append(event)
            log_event(logger, level, "agent_step", profile=profile_name, step=event.step, stage=stage,
                      action=action, **{k: ("-" if v in ([], ()) else v) for k, v in details.items()})

        # PLAN ---------------------------------------------------------------
        artists = len({artist_key(s["artist"]) for s in self.catalog})
        record(PLAN, "plan recommendation run", k=self.k, policy=self.policy,
               catalog_songs=len(self.catalog), distinct_artists=artists, max_corrections=MAX_CORRECTIONS)

        # ACT ----------------------------------------------------------------
        initial = self.scorer(user_prefs, self.catalog, k=self.k)
        top_score = initial[0][1] if initial and isinstance(initial[0], (list, tuple)) and len(initial[0]) > 1 else "-"
        log_event(logger, logging.INFO, "scoring_completed", profile=profile_name,
                  candidates=len(self.catalog), returned=len(initial) if isinstance(initial, list) else 0,
                  top_score=top_score)
        record(ACT, "score catalog with original engine", returned=len(initial) if isinstance(initial, list) else 0,
               song_ids=_safe_ids(initial))

        # CHECK --------------------------------------------------------------
        initial_eval = self._evaluate(user_prefs, initial, self.check_config, profile_name, "initial")
        repeated = _repeated_artist_issues(initial_eval)
        record(CHECK, "evaluate initial list (standard ranking rules)",
               level=logging.INFO if initial_eval.passed else logging.ERROR,
               passed=initial_eval.passed, critical=[i.code for i in initial_eval.critical],
               warnings=[i.code for i in initial_eval.warnings],
               repeated_artist_ranks=[r for i in repeated for r in i.ranks])
        if not initial_eval.passed:
            self._block(initial_eval, CHECK, trace, record, profile_name,
                        "initial list failed integrity checks; not re-ranking unreliable results")

        # DECIDE -------------------------------------------------------------
        if self.policy == STANDARD_POLICY:
            correct, reason = False, "standard policy keeps the original ranking"
        elif repeated:
            correct, reason = True, f"{len(repeated)} artist(s) repeated; diverse policy allows one song per artist"
        else:
            correct, reason = False, "every artist is already unique"
        record(DECIDE, "apply diversity correction" if correct else "keep initial list",
               correction=correct, reason=reason)

        # CORRECT (at most one pass) -----------------------------------------
        final, corrections = initial, 0
        if correct and corrections < MAX_CORRECTIONS:
            corrections += 1
            ranked = self.scorer(user_prefs, self.catalog, k=len(self.catalog))
            try:
                final = select_diverse(ranked, self.k)
            except (TypeError, KeyError, IndexError, AttributeError):
                final = ranked  # malformed ranking: let RECHECK report it rather than crash
            before, after = _ids(initial), _safe_ids(final)
            record(CORRECT, "select best song per artist from full ranked catalog",
                   pass_number=corrections, candidates=len(ranked) if isinstance(ranked, list) else 0,
                   removed_ids=[i for i in before if i not in after],
                   added_ids=[i for i in after if i not in before],
                   final_ids=after)

        # RECHECK ------------------------------------------------------------
        if self.policy == STANDARD_POLICY:
            final_eval = initial_eval  # the initial check already used the standard rules
        else:
            final_eval = self._evaluate(user_prefs, final, self.final_config, profile_name,
                                        "corrected" if corrections else "final", log_issues=bool(corrections))
            record(RECHECK, "evaluate corrected list (diverse rules)" if corrections
                   else "verify list against diverse rules",
                   level=logging.INFO if final_eval.passed else logging.ERROR,
                   passed=final_eval.passed, critical=[i.code for i in final_eval.critical],
                   warnings=[i.code for i in final_eval.warnings])
            if not final_eval.passed:
                self._block(final_eval, RECHECK, trace, record, profile_name,
                            "corrected list failed integrity checks; correction limit reached"
                            if corrections else "list failed diverse-policy checks")

        # OUTPUT -------------------------------------------------------------
        record(OUTPUT, "return verified recommendations", policy=self.policy, corrected=bool(corrections),
               returned=len(final), song_ids=_ids(final), warnings=[i.code for i in final_eval.warnings])
        return AgentResult(
            recommendations=final, evaluation=final_eval, policy=self.policy, corrected=bool(corrections),
            initial_recommendations=initial, initial_evaluation=initial_eval, trace=trace,
        )

    # -- helpers -----------------------------------------------------------

    def _evaluate(self, user_prefs, recommendations, config, profile_name, phase, log_issues=True):
        log_event(logger, logging.INFO, "evaluation_started", profile=profile_name, phase=phase,
                  policy=config.ranking_policy, requested=self.k)
        evaluation = evaluate_recommendations(user_prefs, recommendations, self.catalog, self.k, config)
        for issue in evaluation.critical:
            log_event(logger, logging.ERROR, "integrity_check_failed", profile=profile_name, phase=phase,
                      code=issue.code, ranks=list(issue.ranks) or "-")
        if log_issues:
            for issue in evaluation.warnings:
                log_event(logger, logging.WARNING, WARNING_EVENTS.get(issue.code, "quality_warning_detected"),
                          profile=profile_name, phase=phase, code=issue.code, ranks=list(issue.ranks) or "-")
        # Match stats from a list that failed integrity checks are untrustworthy; don't log them.
        top = evaluation.top if evaluation.passed else None
        log_event(logger, logging.INFO, "evaluation_completed", profile=profile_name, phase=phase,
                  policy=config.ranking_policy, passed=evaluation.passed,
                  critical=len(evaluation.critical), warnings=len(evaluation.warnings),
                  max_score=evaluation.max_score,
                  top_match_pct=top.match_percent if top else "-", top_level=top.match_level if top else "-")
        return evaluation

    def _block(self, evaluation, stage, trace, record, profile_name, reason):
        codes = sorted({i.code for i in evaluation.critical})
        record(BLOCK, "block recommendations", level=logging.ERROR, failed_stage=stage, reason=reason, codes=codes)
        log_event(logger, logging.ERROR, "recommendation_blocked", profile=profile_name, stage=stage,
                  failures=len(evaluation.critical), codes=codes)
        raise AgentBlockedError(evaluation, stage, trace)


def _safe_ids(recommendations: Any) -> List[Any]:
    """Song ids for tracing, tolerating malformed results (the evaluator reports those)."""
    if not isinstance(recommendations, (list, tuple)):
        return []
    return [
        entry[0].get("id") if isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], Mapping) else "?"
        for entry in recommendations
    ]
