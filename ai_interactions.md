# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

> **Two different kinds of "agent" appear in this file.**
> 1. **Development-time AI assistance.** An AI coding agent (Claude Code) made multi-step changes to this repository at the student's direction. This is what the SF8 template questions below ask about.
> 2. **Runtime program behavior.** VibeFinder 2.0 contains its own deterministic recommendation agent ([src/agent.py](src/agent.py)) and an evaluation harness ([src/evaluate.py](src/evaluate.py)). They use no AI model. The traces in this file are the program's actual execution output, not AI conversations or hidden reasoning.

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
| 7 | Final architecture diagram and execution evidence |
| 8 | Final README, model card, and documentation review |
| 9 | Final submission audit and repository cleanup |

**Prompts used:**

```text
Implement Phase 9 of VibeFinder 2.0: Final Submission Audit and Repository Cleanup.

Work only within the AI-musicrecommender repository.

The project is functionally complete. Do not introduce any new features.

## Task 1: Clean up dependencies

The removal of unused dependencies is approved.

- Confirm that pandas and streamlit are unused.
- Remove pandas and streamlit from requirements.txt.
- Retain pytest.
- Update the relevant dependency descriptions in README.md and model_card.md.
- Do not introduce additional dependencies.

## Task 2: Finalize setup documentation

Replace the placeholder repository URL in README.md with the actual public GitHub repository URL obtained from git remote.

Verify that the clone, installation, execution, and testing commands are correct.

Keep diagrams/architecture.mmd as the required Mermaid source file.

Do not generate a PNG or screenshot.

## Task 3: Complete student reflection placeholders

Inspect model_card.md and ai_interactions.md.

Insert the student-approved personal reflection and manual-review description supplied with this task.

Only describe student actions that are supported by the development history or explicitly confirmed by the student.

Do not invent personal experiences, manually performed tests, or historical prompts.

For SF8 prompts, preserve the actual prompts if available. If the complete prompts are not available, identify the missing material rather than reconstructing it.

Keep SF10 marked Not attempted.

Search for remaining student-input placeholders and report any that cannot be resolved honestly.

## Task 4: Final rubric audit

Inspect the repository against these seven required grading categories:

1. Clear identification of the original project.
2. Substantial new AI feature.
3. System architecture diagram.
4. Functional end-to-end demonstration.
5. Reliability, evaluation, or guardrails.
6. Documentation and setup.
7. Responsible AI reflection and AI collaboration.

Also verify the evidence for:

- Agentic Workflow Enhancement.
- Test Harness or Evaluation Script.

For each item, identify the exact supporting files and relevant evidence.

Do not claim that points have already been awarded.

## Task 5: Fresh environment verification

Create a temporary clean copy of the final working tree outside the repository, including uncommitted documentation and dependency changes.

Create a new virtual environment and install only the dependencies listed in requirements.txt.

Run:

python -m src.main

python -m src.main --mode standard

python -m src.main --mode diverse --trace

python -m src.main --stress --mode standard

python -m src.main --stress --mode diverse --trace

python -m src.evaluate

python -m src.evaluate --format json

python src/main.py

python -m pytest -q

pytest -q

Verify:

- Every command exits successfully.
- All 391 tests pass.
- All 12 behavioral scenarios pass.
- All 10 normal recommendation runs pass integrity.
- The evaluation results match the existing execution evidence.
- The JSON output is valid and deterministic.
- No removed dependency is required.

Do not modify production code or tests unless a genuine submission-blocking problem is discovered. Report such a problem before making changes.

## Task 6: Final repository review

Check:

- Git branch and remote URL.
- Meaningful commit history.
- All required source, test, data, diagram, and documentation files.
- Internal Markdown links.
- Unresolved TODOs and student-input placeholders.
- Accidental credentials, API keys, absolute local paths, or sensitive information in tracked files and relevant Git history.
- Unnecessary generated files, virtual environments, and cache files.
- Accuracy of all documented evaluation metrics.
- Consistency of standard and diverse ranking behavior.
- Preservation of original scoring weights and data/songs.csv.

Distinguish genuine submission blockers from optional improvements.

Do not rewrite Git history.

## Constraints

- No additional features.
- No changes to the scoring algorithm.
- No dataset changes.
- No unnecessary refactoring.
- No external AI APIs.
- No Streamlit UI.
- No RAG or model training.
- No fabricated evidence.
- Do not commit or push yet.

## Final report

Provide:

1. Files modified.
2. Dependency cleanup result.
3. Student reflection completion status.
4. Remaining placeholders, if any.
5. Rubric-by-rubric evidence mapping.
6. Stretch feature evidence.
7. Actual fresh environment command results.
8. Exact automated test counts.
9. Final evaluation results.
10. Security and repository hygiene findings.
11. Current Git status.
12. Remaining submission blockers.
13. Suggested final commit message.
14. Final submission readiness: READY or NOT READY, with reasons.

Stop after completing the final audit.
```

**What did the agent generate or change?**

The table below is verifiable from the git history: one commit per phase, made by the student after review.

| Commit | Phase | Files |
|---|---|---|
| `b1e2449` | 2 | `pytest.ini`, `tests/test_baseline.py` (it also restored an accidentally overwritten `model_card.md` to its committed version) |
| `ea9905b` | 3 | `src/validation.py`, `src/logging_config.py`, `src/main.py`, `tests/test_validation.py`, `tests/test_app_integration.py` |
| `c87f56a` | 4 | `src/evaluator.py`, `src/main.py`, `tests/test_evaluator.py`, `tests/test_app_integration.py` |
| `420173a` | 5 | `src/agent.py`, `src/evaluator.py`, `src/logging_config.py`, `src/main.py`, `tests/test_agent.py`, `tests/test_app_integration.py`, `tests/test_baseline.py` |
| `c65cf88` | 6 | `src/evaluate.py`, `src/main.py`, `tests/test_evaluate.py` |
| `c94a518` | 7 | `diagrams/architecture.mmd`, `evaluation_results.md`, `ai_interactions.md` |
| (not yet committed) | 8 | `README.md`, `model_card.md`, `ai_interactions.md` |
| (not yet committed) | 9 | `requirements.txt`, `README.md`, `model_card.md`, `ai_interactions.md` |

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


**Personal Reflection**
I reviewed the development reports at the end of each phase and compared the reported results with the project requirements. I used the baseline results to check whether the original scoring algorithm, dataset, and ranking behavior were preserved.

I also reviewed the reported test results, architecture decisions, and evaluation metrics before moving to the next development phase. The AI coding assistant performed the implementation and automated command execution, while I used its reports to guide the development process and control the project scope.

I chose to keep the project focused on reliability, explainability, and artist diversity rather than introducing unnecessary external APIs or a web interface. I also required actual execution evidence instead of fabricated sample outputs.

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

**Not attempted.** This stretch feature was not part of the project, so the template questions below are left blank, as the template instructs.

**Which design pattern did you use?**

<!-- Not attempted -->

**How did AI help you brainstorm or implement it?**

<!-- Not attempted -->

**How does the pattern appear in your final code?**

<!-- Not attempted -->
