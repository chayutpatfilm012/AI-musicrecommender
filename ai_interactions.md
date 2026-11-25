# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

> **Two different kinds of "agent" appear in this file.**
> 1. **Development-time AI assistance.** An AI coding agent (Claude Code) made multi-step changes to this repository at the student's direction. This is what the SF8 template questions below ask about.
> 2. **Runtime program behavior.** VibeFinder 2.0 contains its own deterministic recommendation agent ([src/agent.py](src/agent.py)) and an evaluation harness ([src/evaluate.py](src/evaluate.py)). They use no AI model. The traces in this file are the program's actual execution output, not AI conversations or hidden reasoning.
>
> Items marked **[Student input needed]** can only be answered by the student.

---

## Agentic Workflow (SF8)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

Extend VibeFinder 1.0 into VibeFinder 2.0 in reviewed phases, while preserving the original dataset, scoring weights, and behavior. Each phase was a separate request, and each phase's work was reviewed and committed before the next request.

| Phase | Request |
|---|---|
| 1 | Read-only inspection of the repository; run the baseline app and tests |
| 2 | Repository housekeeping and baseline regression tests |
| 3 | Input validation, data validation, and structured logging |
| 4 | Integrated runtime reliability evaluator |
| 5 | Agentic workflow, artist diversity guardrail, and execution traces |
| 6 | Automated evaluation harness and reproducible evidence |
| 7 | Final architecture diagram and execution evidence (this documentation) |

**Prompts used:**

Each phase used a written specification. It listed objectives, numbered tasks, constraints (for example, "Do not change scoring weights", "Do not modify data/songs.csv", "Do not commit or push"), and a required final report.

**[Student input needed]** Paste the key prompts here if the assignment requires their full text.

**What did the agent generate or change?**

The table below is verifiable from the git history: one commit per phase, made by the student after review.

| Commit | Phase | Files |
|---|---|---|
| `b1e2449` | 2 | `pytest.ini`, `tests/test_baseline.py` (it also restored an accidentally overwritten `model_card.md` to its committed version) |
| `ea9905b` | 3 | `src/validation.py`, `src/logging_config.py`, `src/main.py`, `tests/test_validation.py`, `tests/test_app_integration.py` |
| `c87f56a` | 4 | `src/evaluator.py`, `src/main.py`, `tests/test_evaluator.py`, `tests/test_app_integration.py` |
| `420173a` | 5 | `src/agent.py`, `src/evaluator.py`, `src/logging_config.py`, `src/main.py`, `tests/test_agent.py`, `tests/test_app_integration.py`, `tests/test_baseline.py` |
| `c65cf88` | 6 | `src/evaluate.py`, `src/main.py`, `tests/test_evaluate.py` |
| (uncommitted) | 7 | `diagrams/architecture.mmd`, `evaluation_results.md`, `ai_interactions.md` |

In each phase the agent also:
- ran the app, the stress test, and both pytest commands;
- diffed the standard-mode output against the original VibeFinder 1.0 output;
- reported the exact pass/fail counts.

**What did you verify or fix manually?**

The agent got the following wrong during development. Each was detected by running the code and then corrected; this is recorded in the phase reports.
- Phase 3: logs included absolute file paths, which can contain a username. They now log the file name only.
- Phase 4: blocked lists logged a misleading match score (`2200%`, computed from a corrupted score). That field is now omitted for blocked lists.
- Phase 5: one new test had a wrong expected value. The code was correct, and the test was fixed.
- Phase 6: JSON averages were sometimes integers and sometimes floats. They are now always floats.
- Phase 5 report: it said the Chill Lofi correction removed the rank-5 song. It actually removed *Focus Flow* at **rank 3**. This was found in Phase 6 and is corrected in [evaluation_results.md](evaluation_results.md).

Seven existing tests (six in `tests/test_app_integration.py`, one in `tests/test_baseline.py`) were updated in Phase 5, when diverse mode became the default. Each was pinned to `--mode standard`, or had its expected event list or call count updated, and every ranking, score, and explanation assertion was kept.

**[Student input needed]** Describe what you personally reviewed or changed before each commit.

---

## Agentic Workflow Enhancement — runtime recommendation agent

This section documents a feature of the program, not AI assistance.

### How the agent works with the scoring engine and evaluator

`RecommendationAgent.run()` in [src/agent.py](src/agent.py) is a fixed, deterministic workflow:

| Stage | What the program does |
|---|---|
| **PLAN** | Records k = 5, the ranking policy (`standard` or `diverse`), catalog size, distinct artists, and the correction limit (1) |
| **ACT** | Calls the **unchanged** scoring engine, `recommend_songs()` in [src/recommender.py](src/recommender.py) |
| **CHECK** | Runs `evaluate_recommendations()` in [src/evaluator.py](src/evaluator.py) on the initial list. This applies 9 integrity checks: scores valid and in range, order, unique ids, catalog match, score and explanation recomputed, top scores returned |
| **DECIDE** | Standard policy: keep the list. Diverse policy: correct only if an artist repeats. The reason is recorded |
| **CORRECT** | At most once: scores the full catalog with the same engine and keeps each artist's best song, with original scores and explanations unchanged |
| **RECHECK** | Diverse policy only: evaluates the final list with 10 checks, including one song per artist and exactly the expected selection |
| **OUTPUT / BLOCK** | Returns the verified list, or blocks it (CLI exit code 3, no list shown) |

The agent never changes the listener's preferences. It never re-ranks a list that failed CHECK, and it never makes a second correction attempt.

### Reproducing the traces

```bash
python -m src.main --mode diverse --trace            # Default profile: correction
python -m src.main --stress --mode diverse --trace   # all four stress profiles
```

### Trace 1 — diversity correction (Chill Lofi, from `--stress --mode diverse --trace`)

```
   1. [PLAN] plan recommendation run | k=5 policy=diverse catalog_songs=20 distinct_artists=18 max_corrections=1
   2. [ACT] score catalog with original engine | returned=5 song_ids=4,2,9,6,7
   3. [CHECK] evaluate initial list (standard ranking rules) | passed=True critical=- warnings=low_match,repeated_artist repeated_artist_ranks=2,3
   4. [DECIDE] apply diversity correction | correction=True reason="1 artist(s) repeated; diverse policy allows one song per artist"
   5. [CORRECT] select best song per artist from full ranked catalog | pass_number=1 candidates=20 removed_ids=9 added_ids=15 final_ids=4,2,6,7,15
   6. [RECHECK] evaluate corrected list (diverse rules) | passed=True critical=- warnings=low_match
   7. [OUTPUT] return verified recommendations | policy=diverse corrected=True returned=5 song_ids=4,2,6,7,15 warnings=low_match
```

- **CHECK:** the initial list is trustworthy, but LoRoom appears at ranks 2 and 3 (*Midnight Coding* #2 and *Focus Flow* #9).
- **DECIDE:** the diverse policy allows one song per artist, so correction is needed.
- **CORRECT:** keeps LoRoom's best song (#2, 5.365), removes *Focus Flow* (#9, 4.685, rank 3), and adds the next eligible song, *Winter Nocturne* (#15, Clara Voss, 2.405).
- **RECHECK:** the corrected list passes all 10 diverse-mode checks. The application output for this run shows the replacement:

```
Diversity correction: 1 song(s) replaced to avoid repeated artists
  - removed #9 Focus Flow (LoRoom, 4.69)
  + added   #15 Winter Nocturne (Clara Voss, 2.41)
Integrity: PASSED (10 checks)
```

### Trace 2 — no correction needed (Intense Rock, from `--stress --mode diverse --trace`)

```
   1. [PLAN] plan recommendation run | k=5 policy=diverse catalog_songs=20 distinct_artists=18 max_corrections=1
   2. [ACT] score catalog with original engine | returned=5 song_ids=3,5,19,13,1
   3. [CHECK] evaluate initial list (standard ranking rules) | passed=True critical=- warnings=low_match repeated_artist_ranks=-
   4. [DECIDE] keep initial list | correction=False reason="every artist is already unique"
   5. [RECHECK] verify list against diverse rules | passed=True critical=- warnings=low_match
   6. [OUTPUT] return verified recommendations | policy=diverse corrected=False returned=5 song_ids=3,5,19,13,1 warnings=low_match
```

- **CHECK:** no repeated artist, so **DECIDE** keeps the list.
- There is no CORRECT step, and the scoring engine is called only once.
- **RECHECK** still verifies the list against the diverse rules before output.

### Trace 3 — **SIMULATED** critical failure, blocked

This is an intentional fault. The scoring function is replaced in memory with one that sets the top score to 99.0; nothing in the source or data is changed. The snippet is in [evaluation_results.md, section 8](evaluation_results.md#8-corrupted-recommendations-are-blocked). Exit code: 3.

```
Error: Recommendations blocked: 2 integrity check failure(s): rank 1: score 99.00 is outside 0-4.50 for this profile; rank 1: score 99.00 does not match the scoring rules (4.48)

   1. [PLAN] plan recommendation run | k=5 policy=diverse catalog_songs=20 distinct_artists=18 max_corrections=1
   2. [ACT] score catalog with original engine | returned=5 song_ids=1,5,10,17,8
   3. [CHECK] evaluate initial list (standard ranking rules) | passed=False critical=score_out_of_range,score_mismatch warnings=- repeated_artist_ranks=-
   4. [BLOCK] block recommendations | failed_stage=CHECK reason="initial list failed integrity checks; not re-ranking unreliable results" codes=score_mismatch,score_out_of_range
```

The evaluator recomputes the score from the trusted catalog record (4.48) and finds it out of range (maximum 4.50). The agent blocks at CHECK and does **not** correct or re-rank, because doing so would hide an unreliable result. No recommendation list is printed.

---

## Test Harness / Evaluation Script — automated evaluation

This section documents a feature of the program.

[src/evaluate.py](src/evaluate.py) runs the production workflow automatically. It loads the catalog with `load_validated_songs()` and runs every profile through the same `recommend_for_profile()` function the CLI uses (validation, agent, and evaluator). It contains no separate recommender.

```bash
python -m src.evaluate                 # readable report
python -m src.evaluate --format json   # deterministic JSON on stdout, logs on stderr
```

- **Runs:** 5 profiles × 2 policies = 10 recommendation runs, with metrics computed from the actual results: ids and titles, unique artists, average raw score, average and top match %, low-match count, corrections, songs replaced, integrity result, and warning codes.
- **Scenarios:** 12 behavioral scenarios with explicit expected outcomes. These include three **expected rejections** (energy 1.5, NaN, empty profile), two **SIMULATED** faults (corrupted score, too few artists), and a determinism re-run.
- **Exit codes:** 0 only when all runs pass integrity and all scenarios pass; 1 on any unexpected result; 2 if the catalog cannot be loaded.

Current results: 10/10 runs passed integrity and 12/12 scenarios passed, and the output is byte-identical across runs. The scenario pass rate measures whether the system behaves as specified, not recommendation accuracy, which has not been measured with real listeners. Full results, tables, and limitations are in [evaluation_results.md](evaluation_results.md). The harness's own tests are in [tests/test_evaluate.py](tests/test_evaluate.py).

---

## Design Pattern (SF10)

> Document how AI helped you choose or implement a design pattern.

Not attempted as a stretch feature. **[Student input needed]** Delete this section, or complete it if you choose to claim it.

**Which design pattern did you use?**

<!-- e.g., Strategy, Factory, Observer, etc. -->

**How did AI help you brainstorm or implement it?**

<!-- Describe the conversation or suggestions that led to your decision -->

**How does the pattern appear in your final code?**

<!-- Point to the relevant class or method -->
