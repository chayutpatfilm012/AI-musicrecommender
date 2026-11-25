# VibeFinder 2.0 — Evaluation Results

All numbers below come from running the commands in [Reproducing the results](#2-reproducing-the-results) on the current code. The harness output is deterministic, so rerunning the commands reproduces them exactly.

**What these results show, and what they do not**

| Measure | Result | What it means |
|---|---|---|
| Integrity pass rate | 10/10 runs (100%) | Every recommendation list passed the evaluator's integrity checks: valid, in-range scores; correct order; real catalog songs; scores and explanations that match the scoring rules |
| Behavioral scenario pass rate | 12/12 (100%) | Every predefined scenario behaved as expected, including expected rejections and blocks |
| Normalized match % | 36.9%–78.2% average per list | Heuristic: raw score ÷ maximum possible score for the profile. **Not** confidence, accuracy, or predicted satisfaction |
| Recommendation accuracy | **Not measured** | No real listeners rated the recommendations |

A 100% scenario pass rate is **not** 100% recommendation accuracy.

---

## 1. Methodology

The evaluation harness ([src/evaluate.py](src/evaluate.py)) exercises the same code path as the application:

```
load_validated_songs → recommend_for_profile → validate_user_prefs → RecommendationAgent → evaluator
```

It does not contain a separate or simplified recommender.

- **Profiles:** the five listener profiles defined in [src/main.py](src/main.py) — `DEFAULT_PROFILE` and the four `STRESS_PROFILES` (High-Energy Pop, Chill Lofi, Intense Rock, Conflicting Preferences).
- **Policies:** each profile is run under both ranking policies, so there are 10 recommendation runs with k = 5.
  - `standard` is the original VibeFinder 1.0 top-5.
  - `diverse` is the default: the highest-ranked songs with at most one song per artist. Artist names are compared case-insensitively, ignoring surrounding spaces.
- **Metrics:** computed from each run's actual output. Raw scores are compared only within a profile, because profiles with optional valence and acousticness have a higher maximum (5.5 instead of 4.5). Cross-profile aggregates use normalized match % only.
- **Low match:** a song below 60% of the profile's maximum score. The 60% and 80% thresholds are design choices, not values derived from listener data.
- **Scenarios:** 12 behavioral scenarios with explicit expected outcomes.
  - Expected rejections and blocks count as PASS when they happen as expected.
  - The two **SIMULATED** scenarios inject faults through dependency injection (a replacement scoring function, or an in-memory synthetic catalog).
  - The real catalog, scoring weights, and preferences are never modified.

## 2. Reproducing the results

Run from the repository root:

```bash
python -m src.main --mode standard               # original VibeFinder 1.0 ranking
python -m src.main --mode diverse --trace        # default policy, with agent trace
python -m src.main --stress --mode diverse --trace
python -m src.evaluate                           # readable evaluation report
python -m src.evaluate --format json             # deterministic JSON (logs on stderr)
python -m pytest -q
pytest -q
```

Exit codes observed for this run:

| Command | Exit code |
|---|---|
| `python -m src.main --mode standard` | 0 |
| `python -m src.main --mode diverse --trace` | 0 |
| `python -m src.main --stress --mode diverse --trace` | 0 |
| `python -m src.evaluate` | 0 |
| `python -m src.evaluate --format json` | 0 |
| `python -m pytest -q` | 0 |
| `pytest -q` | 0 |
| Simulated corrupted score (snippet in [section 8](#8-corrupted-recommendations-are-blocked)) | 3 (blocked, as expected) |

## 3. Automated tests

`python -m pytest -q` → `391 passed in 0.98s`  
`pytest -q` → `391 passed in 0.99s`

| Test file | Tests | Covers |
|---|---|---|
| `tests/test_baseline.py` | 48 | VibeFinder 1.0 regression: weights, top 5 for all profiles, matching, max scores, ties, explanations |
| `tests/test_recommender.py` | 2 | Original starter tests |
| `tests/test_validation.py` | 179 | Preference and catalog validation, malformed CSVs |
| `tests/test_app_integration.py` | 28 | CLI workflow, safe errors, logging, blocking |
| `tests/test_evaluator.py` | 78 | Integrity checks, match %, quality warnings |
| `tests/test_agent.py` | 39 | Agent stages, diversity policy, one-pass limit, traces |
| `tests/test_evaluate.py` | 17 | Harness metrics, denominators, determinism, JSON, exit codes |
| **Total** | **391** | 0 failed |

## 4. Standard vs. diverse, per profile

| Profile (max score) | Policy | Song ids | Unique artists | Avg raw score | Avg match % | Low-match songs | Corrected | Integrity | Quality warnings |
|---|---|---|---|---|---|---|---|---|---|
| Default (4.5) | standard | 1, 5, 10, 17, 8 | 4/5 | 2.348 | 52.18 | 3 | — | PASS (9) | low_match, repeated_artist |
| | diverse | 1, 5, 10, 17, **3** | 5/5 | 2.336 | 51.91 | 3 | yes, 1 song | PASS (10) | low_match |
| High-Energy Pop (4.5) | standard | 1, 5, 10, 3, 19 | 5/5 | 2.338 | 51.96 | 3 | — | PASS (9) | low_match |
| | diverse | same | 5/5 | 2.338 | 51.96 | 3 | no | PASS (10) | low_match |
| Chill Lofi (5.5) | standard | 4, 2, 9, 6, 7 | 4/5 | 4.299 | 78.16 | 1 | — | PASS (9) | low_match, repeated_artist |
| | diverse | 4, 2, 6, 7, **15** | 5/5 | 3.843 | 69.87 | 2 | yes, 1 song | PASS (10) | low_match |
| Intense Rock (4.5) | standard | 3, 5, 19, 13, 1 | 5/5 | 1.958 | 43.51 | 4 | — | PASS (9) | low_match |
| | diverse | same | 5/5 | 1.958 | 43.51 | 4 | no | PASS (10) | low_match |
| Conflicting Preferences (4.5) | standard | 13, 15, 2, 4, 6 | 5/5 | 1.662 | 36.93 | 4 | — | PASS (9) | low_match, no_strong_match, top_mood_mismatch |
| | diverse | same | 5/5 | 1.662 | 36.93 | 4 | no | PASS (10) | low_match, no_strong_match, top_mood_mismatch |

In standard mode the 9th integrity check confirms that no left-out song outscores the returned ones. In diverse mode it is replaced by two checks — one song per artist, and exactly the expected best song of each top-ranked artist — giving 10.

**What changed, standard → diverse**

| Profile | Unique artists | Avg raw score | Avg match | Replacement |
|---|---|---|---|---|
| Default | +1 | −0.012 | −0.27 pp | #8 *Night Drive Loop* (Neon Echo, 0.95, rank 5) → #3 *Storm Runner* (Voltline, 0.89), standard rank 6 |
| Chill Lofi | +1 | −0.456 | −8.29 pp | #9 *Focus Flow* (LoRoom, 4.685, **rank 3**) → #15 *Winter Nocturne* (Clara Voss, 2.405), new rank 5 |
| Other three | 0 | 0.000 | 0.00 pp | No repeated artist, so no correction |

The Chill Lofi correction removes *Focus Flow*, which is rank 3 in the standard list. *Spacewalk Thoughts* and *Coffee Shop Stories* move up to ranks 3 and 4, and *Winter Nocturne* is added at rank 5. An earlier development report wrongly said rank 5. Actual standard-mode output:

```
1. Library Rain - Paper Lanterns     Score: 5.47
2. Midnight Coding - LoRoom          Score: 5.37
3. Focus Flow - LoRoom               Score: 4.69
4. Spacewalk Thoughts - Orbit Bloom  Score: 3.35
5. Coffee Shop Stories - Slow Stereo Score: 2.63
```

## 5. Aggregate metrics

| Metric (5 runs per policy) | Standard | Diverse | Difference |
|---|---|---|---|
| Integrity passed | 5/5 | 5/5 | — |
| Average unique artists per list | 4.6 | 5.0 | +0.4 |
| Lists with a repeated artist | 2/5 | 0/5 | −2 |
| Runs that needed correction | 0/5 | 2/5 (40%) | — |
| Mean of per-list average match % | 52.55% | 50.84% | −1.71 pp |
| Mean top-ranked match % | 92.29% | 92.29% | 0.00 pp |
| Low-match songs (of 25 returned) | 15 (60%) | 16 (64%) | +4 pp |

Separate denominators:
- **Recommendation runs:** 10, all valid.
- **Behavioral scenarios:** 12, all passed, 2 of them simulated.
- **Songs returned:** 25 per policy.

## 6. Behavioral scenarios

| # | Scenario | Expected | Observed | Result |
|---|---|---|---|---|
| 1 | Standard mode preserves the original ranking | Lists equal the `recommend_songs()` top 5 | 5/5 identical (ids and raw scores), no correction | PASS |
| 2 | Diverse mode returns unique artists | One song per artist; integrity passes | 5/5 | PASS |
| 3 | Default profile triggers diversity correction | corrected = True | Corrected once, 1 song replaced, artists 5/5 | PASS |
| 4 | Chill Lofi triggers diversity correction | corrected = True | Corrected once, 1 song replaced, artists 5/5 | PASS |
| 5 | Intense Rock needs no correction | corrected = False | Stages: PLAN > ACT > CHECK > DECIDE > RECHECK > OUTPUT | PASS |
| 6 | Conflicting preferences produce quality warnings | Shown with no_strong_match and top_mood_mismatch | low_match, no_strong_match, top_mood_mismatch (top match 65.1%) | PASS |
| 7 | Energy above 1 is rejected *(expected rejection)* | Rejected before scoring | `energy must be between 0 and 1, got 1.5` | PASS |
| 8 | NaN preference is rejected *(expected rejection)* | Rejected before scoring | `energy must be a finite number between 0 and 1, got nan` | PASS |
| 9 | Empty preferences are rejected *(expected rejection)* | Rejected before scoring | `preferences are empty; provide at least genre, mood, and energy` | PASS |
| 10 | **SIMULATED:** corrupted score is blocked | Blocked, not re-ranked | Blocked at CHECK; no re-ranking; no list returned | PASS |
| 11 | **SIMULATED:** too few unique artists | Valid shorter list plus a warning | 2 of 5 songs (ids 1, 3), with a fewer_than_requested warning | PASS |
| 12 | Repeated execution is deterministic | Identical second run | 10 runs identical (ids, raw scores, decisions, warnings, traces) | PASS |

Scenarios 7–9 also confirm that the scoring engine was never called. Scenario 11 uses a three-song in-memory catalog with two artists, and the catalog is validated before use.

## 7. Invalid input is rejected

Each invalid profile was passed to the application's `run()` function, which takes the same path as the CLI. Actual stderr, exit code 1, and no recommendations printed:

```
Error: Invalid listener preferences: energy must be between 0 and 1, got 1.5
Error: Invalid listener preferences: energy must be a finite number between 0 and 1, got nan
Error: Invalid listener preferences: preferences are empty; provide at least genre, mood, and energy
```

Reproduce one case:

```bash
python -c "import sys; from src import main as m; m.configure_logging('ERROR'); sys.exit(m.run(False, user_prefs={'genre': 'pop', 'mood': 'happy', 'energy': 1.5}))"
```

## 8. Corrupted recommendations are blocked

**SIMULATED failure.** The scoring function is replaced in memory with one that sets the top score to 99.0, and the real application runs in diverse mode with `--trace`. No source file or data is changed.

```bash
python - <<'EOF'
import sys
from src import main as m
real = m.recommend_songs
def corrupted(prefs, songs, k=5):
    recs = real(prefs, songs, k=k)
    song, _, explanation = recs[0]
    return [(song, 99.0, explanation)] + recs[1:]
m.recommend_songs = corrupted
sys.exit(m.main(["--mode", "diverse", "--trace", "--log-level", "ERROR"]))
EOF
```

Actual result, exit code **3**, with no recommendation list printed:

```
Error: Recommendations blocked: 2 integrity check failure(s): rank 1: score 99.00 is outside 0-4.50 for this profile; rank 1: score 99.00 does not match the scoring rules (4.48)

   1. [PLAN] plan recommendation run | k=5 policy=diverse catalog_songs=20 distinct_artists=18 max_corrections=1
   2. [ACT] score catalog with original engine | returned=5 song_ids=1,5,10,17,8
   3. [CHECK] evaluate initial list (standard ranking rules) | passed=False critical=score_out_of_range,score_mismatch warnings=- repeated_artist_ranks=-
   4. [BLOCK] block recommendations | failed_stage=CHECK reason="initial list failed integrity checks; not re-ranking unreliable results" codes=score_mismatch,score_out_of_range
```

The agent stops at CHECK. It does not try to hide the corrupted score by re-ranking or correcting the list.

## 9. Reproducibility

- Two consecutive runs of `python -m src.evaluate --format json` were byte-identical, and so were two text runs.
- The text report matched the one produced at the end of Phase 6.
- Scenario 12 checks determinism inside the harness itself.
- The JSON contains no timestamps, absolute paths, or usernames; the catalog is identified only as `data/songs.csv`. Timestamps appear only in the stderr logs, which are not part of the JSON.
- Recomputing every run's ids, average raw score, maximum score, and average match % directly from `recommend_songs()` and `max_possible_score()` gave zero mismatches with the harness.
- In standard mode, the original VibeFinder 1.0 output lines (titles, ranks, scores, reasons) are byte-identical to the output captured before any VibeFinder 2.0 change.

## 10. Limitations and interpretation

- **Diversity vs. relevance.** The diverse policy guarantees one song per artist, but it can only do this by giving up score.
  - For Chill Lofi it replaces a 4.685-point lofi track with a 2.405-point classical one. That lowers the list's average match by 8.29 percentage points.
  - Across all profiles, low-match songs rise from 60% to 64% of recommendations.
  - The top-ranked song never changed in these profiles.
  - Standard mode remains available for anyone who prefers maximum relevance.
- **Low matches are common because the catalog is small.** There are 20 songs, and 13 of the 16 genres have only one song, so ranks 3–5 are usually filled on energy alone. The warnings report this honestly; they don't fix it.
- **Match % is a heuristic.** It shows how much of the possible weighted score a song earns. The 60% and 80% thresholds are design choices, not calibrated values.
- **Small, predefined evidence base.** Five profiles and twelve hand-written scenarios show that the system behaves as designed. They are not a statistical evaluation.
- **No listener study.** Whether people actually enjoy these recommendations has not been measured.
- **Artist identity is name-based.** Collaborations, "feat." credits, and aliases are not recognized as the same artist.
