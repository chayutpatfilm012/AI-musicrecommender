# VibeFinder 2.0: Explainable and Reliable Music Recommendation System

VibeFinder 2.0 is a command-line music recommender built as a graduate applied-AI course project. It takes a listener's preferred genre, mood, and energy level and recommends five songs from a small fictional catalog. Each recommendation comes with a plain-language explanation of its score.

The original recommender (VibeFinder 1.0) only scored and sorted songs. Version 2.0 keeps that scoring exactly as it was and adds a reliability layer around it:

- every input and catalog record is validated;
- every recommendation list is independently checked before it is shown;
- lists that fail those checks are blocked;
- a deterministic agent can correct a list once so that no artist appears twice.

**Primary advanced AI feature: the integrated runtime reliability evaluator.** Every recommendation list is checked at runtime, before display. The evaluator verifies:

- scores are valid and within range;
- the list is in the correct order;
- every song exists in the catalog;
- each score and explanation matches the scoring rules, recomputed from the catalog.

A list that fails is never shown.

The system is **rule-based and deterministic**. It is not a trained machine-learning model, it uses no LLM or external AI API, and it does not retrieve documents (no RAG). It is intended for learning how recommenders work, and how they can fail. It is not intended for recommending music to real users.

---

## Original Project: VibeFinder 1.0

VibeFinder 1.0 was a content-based music recommendation simulation. It compared a listener profile with 20 fictional songs in [data/songs.csv](data/songs.csv) and printed the top 5 songs with the reasons behind each score.

**Scoring.** Each song received points for matching the listener:

| Feature | Points |
|---|---|
| Genre (exact match) | 2.0 |
| Mood (exact match) | 1.5, or 0.75 for a similar mood ("relaxed", "peaceful", and "focused" count as similar to "chill") |
| Energy closeness | up to 1.0, as `1 − |user − song|` |
| Valence closeness (optional) | up to 0.5 |
| Acousticness closeness (optional) | up to 0.5 |

Songs were sorted from highest to lowest score. Python's stable sort keeps tied songs in catalog order. The top 5 were printed with explanations such as `genre match (+2.0)`.

**Dataset.** 20 fictional songs across 16 genres and 14 moods. Each song has an id, title, artist, genre, mood, energy, tempo, valence, danceability, and acousticness.

**Stress test.** `--stress` ran four listener profiles: High-Energy Pop, Chill Lofi, Intense Rock, and a deliberately contradictory "Conflicting Preferences" profile (metal, peaceful, energy 0.9). The original top results were:

| Profile | Original top 5 (score) |
|---|---|
| High-Energy Pop | Sunrise City (4.42), Gym Hero (2.97), Rooftop Lights (2.36), Storm Runner (0.99), Neon Pulse (0.95) |
| Chill Lofi | Library Rain (5.47), Midnight Coding (5.37), Focus Flow (4.69), Spacewalk Thoughts (3.35), Coffee Shop Stories (2.63) |
| Intense Rock | Storm Runner (4.46), Gym Hero (2.48), Neon Pulse (1.00), Iron Tempest (0.98), Sunrise City (0.87) |
| Conflicting Preferences | Iron Tempest (2.93), Winter Nocturne (1.78), Midnight Coding (1.27), Library Rain (1.20), Spacewalk Thoughts (1.13) |

VibeFinder 1.0 experiments included:
- expanding the catalog from 10 to 20 songs;
- adding partial credit for similar moods;
- a temporary weight shift (genre 1.0, energy 2.0). It reduced genre bias, but energy then dominated, and the original weights were restored.

**Limitations that motivated VibeFinder 2.0.** The 1.0 stress tests and inspection found:

- **No input checks.**
  - An empty profile scored every song 0.00.
  - An energy of 1.5 produced negative points.
  - A non-number such as `"high"` crashed the program.
  - NaN silently produced `nan` scores.
- **No catalog checks.** A missing or malformed CSV crashed with a raw traceback.
- **No check on the output.** Nothing confirmed that scores, order, or explanations were correct before display.
- **Scores couldn't be compared across profiles.** The maximum was 4.5 or 5.5 depending on which preferences were given.
- **Repeated artists.** The default profile's list contained Neon Echo twice, and Chill Lofi's contained LoRoom twice.
- **Silent weak matches.** Ranks 3–5 were usually filled on energy alone, with no warning.

> **Original VibeFinder 1.0 reflection (unchanged):** Building VibeFinder showed me that a recommender is really just simple rules that a person chose: each song is a few labels and numbers, and a "recommendation" is the result of adding up points and sorting. The results looked right for clear tastes like Chill Lofi and Intense Rock, which made it easy to forget that the system doesn't actually understand music. The stress tests showed where bias hides, because genre was worth 2.0 points and kept listeners stuck in their favorite genre, while fans of genres with only one song got weak lists. When I shifted the weights toward energy, the bias didn't go away; it just moved. Now I understand that the people who choose the weights and the data have a big say in what listeners get to hear.

---

## Key Features

| Feature | What it does | Where |
|---|---|---|
| Original weighted scoring | VibeFinder 1.0's scoring, weights, similar-mood rule, and ranking, all unchanged | [src/recommender.py](src/recommender.py) |
| Input validation | Requires genre, mood, and energy. Numbers must be finite and between 0 and 1. Rejects NaN, ±infinity, booleans, text, empty profiles, and unknown keys. Never clamps or rewrites values | [src/validation.py](src/validation.py) |
| Catalog validation | Checks the file exists and is valid UTF-8 CSV with all required columns. Catches duplicate or invalid ids, blank text, and out-of-range values, giving the line or song number | [src/validation.py](src/validation.py) |
| Runtime integrity checking | 9 checks in standard mode and 10 in diverse mode, run on every list before display (details below) | [src/evaluator.py](src/evaluator.py) |
| Normalized match score | Raw score ÷ maximum possible score for the profile. Labeled Strong (≥ 80%), Moderate (≥ 60%), or Low (< 60%) | [src/evaluator.py](src/evaluator.py) |
| Quality warnings | Low or no strong match; genre or mood not in the catalog; top song's genre or mood mismatched (exact vs. similar mood); repeated artist; shorter list than requested | [src/evaluator.py](src/evaluator.py) |
| Ranking policies | `standard`: the original top 5. `diverse` (default): the highest-ranked songs, at most one per artist | [src/agent.py](src/agent.py) |
| Deterministic recommendation agent | PLAN → ACT → CHECK → DECIDE → CORRECT (optional) → RECHECK → OUTPUT or BLOCK | [src/agent.py](src/agent.py) |
| Artist diversity correction | Runs only when an artist repeats in diverse mode. Picks each artist's best song from the full ranked catalog. At most one pass. Original scores and explanations are kept | [src/agent.py](src/agent.py) |
| Safe failure blocking | A list that fails an integrity check is not displayed. The program prints a clear error and exits with code 3 | [src/agent.py](src/agent.py), [src/main.py](src/main.py) |
| Structured logging and traces | `key=value` log events on stderr. Preference values are never logged. `--trace` prints the agent's actual steps and decisions | [src/logging_config.py](src/logging_config.py), [src/agent.py](src/agent.py) |
| Evaluation harness | Runs 5 profiles × 2 policies plus 12 behavioral scenarios through the real workflow. Produces a text report or deterministic JSON | [src/evaluate.py](src/evaluate.py) |

Integrity checks:
- **Both modes:**
  - the result has the expected structure and number of songs;
  - every score is finite and within 0 and the profile's maximum;
  - songs are in descending score order;
  - each song appears only once;
  - every song exists in the catalog with unchanged details;
  - each score and explanation equals a fresh recomputation from the catalog record.
- **Standard mode:** no left-out song outscores the returned ones.
- **Diverse mode:** one song per artist, and exactly the expected best song of each top-ranked artist.

---

## Architecture Overview

The full diagram is in [diagrams/architecture.mmd](diagrams/architecture.mmd). It is Mermaid source, which GitHub and most Markdown previewers render directly.

**Runtime flow (one user run):**

1. **CLI** ([src/main.py](src/main.py)) parses `--mode`, `--stress`, `--trace`, and `--log-level`.
2. **Catalog validation** loads `data/songs.csv` through `load_validated_songs()`. An invalid catalog stops the run with exit code 1.
3. **Input validation** checks each listener profile. Invalid input is rejected before scoring. In stress mode, only that profile is skipped.
4. The **recommendation agent**:
   - **ACT** calls the unchanged `recommend_songs()`.
   - **CHECK** evaluates the initial list under the standard rules. If it fails, the list is **blocked**, never re-ranked.
   - **DECIDE**:
     - **standard** policy: output as is;
     - **diverse** policy with all artists unique: verify against the diverse rules;
     - **diverse** policy with a repeated artist: **CORRECT** once, then **RECHECK**. If RECHECK fails, the list is blocked.
5. **Output**: the recommendations with raw scores and reasons, then a reliability summary showing the policy, any correction, the integrity result, match %, and warnings.

Logs go to stderr throughout; with `--trace`, the agent's execution trace is printed after the results.

**Runtime evaluation vs. offline testing.** The reliability evaluator runs inside every application run and controls what the user sees. The pytest suite and the evaluation harness run offline, as development tools. They exercise the same functions, but they are not part of a user's run.

---

## Setup Instructions

Tested with **Python 3.13** on Windows. A fresh clone with a new virtual environment ran every command below successfully.

```bash
git clone https://github.com/chayutpatfilm012/AI-musicrecommender.git
cd AI-musicrecommender
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# macOS / Linux:       source .venv/bin/activate
python -m pip install -r requirements.txt
```

> **Dependencies.** The code uses only the Python standard library at runtime; `requirements.txt` contains only **pytest**, which is needed for the tests. The course starter template also listed `pandas` and `streamlit`. Nothing in the project imported them, so they were removed.

Run from the repository root:

```bash
python -m src.main                                 # default profile, diverse mode
python -m src.main --mode standard                 # original VibeFinder 1.0 ranking
python -m src.main --mode diverse --trace          # show the agent's execution trace
python -m src.main --stress --mode diverse --trace # four stress-test profiles
python -m src.evaluate                             # evaluation report
python -m src.evaluate --format json               # deterministic JSON on stdout
python -m pytest -q                                # automated tests (plain `pytest -q` also works)
```

| Flag | Meaning |
|---|---|
| `--mode diverse` | Default. At most one song per artist; corrects once if needed |
| `--mode standard` | Original VibeFinder 1.0 ranking, unchanged |
| `--stress` | Run the four stress-test profiles instead of the default profile |
| `--trace` | Print the agent's execution trace |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Minimum level of log lines on stderr (default INFO for `src.main`, ERROR for `src.evaluate`) |
| `--format {text,json}` | Report format for `src.evaluate` |

| Exit code | `python -m src.main` | `python -m src.evaluate` |
|---|---|---|
| 0 | Recommendations shown | All runs passed integrity and all scenarios passed |
| 1 | Invalid preferences or catalog | An unexpected result in any run or scenario |
| 2 | Unexpected internal error (no traceback shown; use `--log-level DEBUG`) | Catalog could not be loaded |
| 3 | Recommendations blocked by an integrity check | — |

---

## Sample Interactions

All output below was captured from real runs. The profile header and log lines are omitted for brevity.

### 1. Standard recommendation (`python -m src.main --mode standard`)

```
1. Sunrise City - Neon Echo
   Genre: pop | Mood: happy
   Score: 4.48
   Reasons:
     * genre match (+2.0)
     * mood match (+1.5)
     * energy closeness (+0.98)
...
5. Night Drive Loop - Neon Echo
   Genre: synthwave | Mood: moody
   Score: 0.95
...
Ranking policy: standard (original VibeFinder 1.0 top-5 ranking)
Integrity: PASSED (9 checks)
Warnings: 2
  ! Low match: ranks 3, 4 and 5 scored below 60% of the maximum possible score.
  ! Repeated artist: Neon Echo appears at ranks 1 and 5.
```

The list is identical to VibeFinder 1.0. The repeated artist is reported as a warning but not changed.

### 2. Diverse recommendation with a correction (`python -m src.main --mode diverse --trace`)

```
5. Storm Runner - Voltline
   Genre: rock | Mood: intense
   Score: 0.89
...
Ranking policy: diverse (highest-ranked songs, at most one per artist)
Diversity correction: 1 song(s) replaced to avoid repeated artists
  - removed #8 Night Drive Loop (Neon Echo, 0.95)
  + added   #3 Storm Runner (Voltline, 0.89)
Integrity: PASSED (10 checks)
...
Execution trace (actual agent steps)
   1. [PLAN] plan recommendation run | k=5 policy=diverse catalog_songs=20 distinct_artists=18 max_corrections=1
   2. [ACT] score catalog with original engine | returned=5 song_ids=1,5,10,17,8
   3. [CHECK] evaluate initial list (standard ranking rules) | passed=True critical=- warnings=low_match,repeated_artist repeated_artist_ranks=1,5
   4. [DECIDE] apply diversity correction | correction=True reason="1 artist(s) repeated; diverse policy allows one song per artist"
   5. [CORRECT] select best song per artist from full ranked catalog | pass_number=1 candidates=20 removed_ids=8 added_ids=3 final_ids=1,5,10,17,3
   6. [RECHECK] evaluate corrected list (diverse rules) | passed=True critical=- warnings=low_match
   7. [OUTPUT] return verified recommendations | policy=diverse corrected=True returned=5 song_ids=1,5,10,17,3 warnings=low_match
```

Neon Echo's second song is replaced by the next-best song from a different artist (standard rank 6). Ranks 1–4 and every score and explanation are unchanged.

### 3. Conflicting preferences (`python -m src.main --stress`, Stress Test 4)

```
1. Iron Tempest - Grave Sentinel
   Genre: metal | Mood: angry
   Score: 2.93
...
Integrity: PASSED (10 checks)
Match scores (raw score / max possible 4.50 for this profile):
  1. Iron Tempest            2.93 / 4.50   65.1%  Moderate Match
  2. Winter Nocturne         1.78 / 4.50   39.6%  Low Match
...
Warnings: 3
  ! Low match: ranks 2, 3, 4 and 5 scored below 60% of the maximum possible score.
  ! No strong match: the best recommendation reaches only 65.1% (strong is 80% or more).
  ! Top recommendation 'Iron Tempest' does not match the requested mood.
```

The list is trustworthy (it passes integrity), but it is a weak fit, and the user is told so. A **simulated** corrupted-score failure, which is blocked with exit code 3, is documented with its reproduction steps in [evaluation_results.md](evaluation_results.md#8-corrupted-recommendations-are-blocked).

---

## Design Decisions and Trade-offs

- **The original scoring weights were preserved.** VibeFinder 1.0's behavior is the baseline that every new component is measured against. Keeping `score_song()` and its weights unchanged means standard mode reproduces the 1.0 results exactly. 48 regression tests protect that.
- **Invalid values are rejected, not clamped.** Turning an energy of 1.5 into 1.0 would silently change what the listener asked for. A clear error that names the field is more honest than a recommendation based on an altered preference.
- **Diversity correction never changes preferences.** It only chooses among songs the original engine already ranked, and it keeps their original scores and explanations. Every explanation therefore remains true for the listener's actual request.
- **Correction is limited to one pass.** Choosing each artist's best song in one pass already satisfies the diversity rule. A retry loop would add complexity and could hide a deeper fault. If the corrected list fails RECHECK, it is blocked.
- **Corrupted results are blocked, not repaired.** If scores or explanations don't match the scoring rules, something is wrong upstream. Re-ranking would hide that, so the agent stops at CHECK.
- **Standard mode is kept.** It is the reproducible 1.0 baseline. It makes the cost of diversity measurable, and it remains a choice for users who prefer maximum relevance.
- **Rule-based components rather than an external LLM.** The task is small and fully specified. Deterministic rules can be tested exactly, give the same output every time, cost nothing to run, need no network or API keys, and send no user data anywhere.

**Relevance vs. artist diversity.** Diversity has a measurable cost. For Chill Lofi, the diverse policy removes *Focus Flow* (LoRoom, 4.685, standard **rank 3**) and adds *Winter Nocturne* (Clara Voss, 2.405) at rank 5. That lowers the list's average match by 8.29 percentage points. Across all five profiles, the mean average match falls 1.71 percentage points, and low-match songs rise from 60% to 64% of recommendations. The top-ranked song never changed. Diverse mode is the default because repeated artists are a visible filter-bubble effect; standard mode remains available.

---

## Testing and Evaluation Summary

Verified with the current code (`python -m src.evaluate`, `python -m pytest -q`):

| Result | Value |
|---|---|
| Automated tests | **391 passed**, 0 failed |
| Behavioral scenarios | **12/12 passed** (includes 3 expected rejections and 2 simulated failures) |
| Normal recommendation runs passing integrity | **10/10** (5 profiles × 2 policies) |

| Metric (5 profiles each) | Standard | Diverse | Change |
|---|---|---|---|
| Average unique artists per list | 4.6 | 5.0 | +0.4 |
| Lists with a repeated artist | 2/5 (40%) | 0/5 (0%) | −40 percentage points |
| Mean of per-list average match | 52.55% | 50.84% | −1.71 percentage points |
| Mean top-recommendation match | 92.3% | 92.3% | no change |
| Low-match recommendations | 15/25 (60%) | 16/25 (64%) | +4 percentage points |
| Profiles that needed correction | — | 2/5 (Default, Chill Lofi) | — |

A change between two percentages is reported in percentage points. For example, 52.55% → 50.84% is a 1.71-point drop, not a 1.71% drop.

**What these numbers do not mean.** The scenario pass rate shows that predefined behaviors work as specified. The integrity pass rate shows the lists are internally consistent. Match % is a heuristic share of the maximum possible score. **None of them measures listener satisfaction or recommendation accuracy, which has not been measured with real listeners.**

Full methodology, per-profile tables, scenario results, and reproduction steps: [evaluation_results.md](evaluation_results.md).

---

## Reflection

This project shows that a recommender can look correct and still be unreliable. VibeFinder 1.0 produced sensible-looking lists, yet the same code accepted an energy of 1.5, produced `nan` scores, and showed results that nothing had checked.

Reliability came from adding independent checks around the original algorithm, not from changing it:
- validating inputs before scoring;
- recomputing every score and explanation from trusted data before display;
- blocking anything that doesn't match.

Explainability turned out to support reliability. Because every score has written reasons, the evaluator can confirm the explanation is true, and not just that it exists.

The diversity feature shows that "better" depends on the goal. Removing repeated artists is easy to measure and to guarantee. But it costs relevance, and the cost is uneven: almost nothing for the default profile, and over 8 percentage points of average match for Chill Lofi. Making that trade-off visible, by keeping standard mode, reporting match % and warnings, and evaluating both policies side by side, mattered more than choosing one answer.

The detailed Responsible AI reflection is in [model_card.md](model_card.md).

---

## Limitations and Future Work

**Limitations**
- **Small, fictional catalog.** 20 songs, 18 artists, 16 genres; 13 genres have one song. Values were invented, not measured from audio.
- **Handcrafted weights.** Genre 2.0 dominates. "indie pop" earns nothing for a "pop" listener, because genre matching is exact.
- **Heuristic thresholds.** The 60% and 80% match thresholds are design choices, not calibrated values.
- **Fixed evaluation set.** Five profiles and twelve scenarios are not a statistical evaluation.
- **Name-based artist matching.** Collaborations, "feat." credits, and aliases are not recognized as the same artist.
- **No real listener data.** There are no ratings, listening history, or user study, so accuracy and satisfaction are unknown.
- **No learning.** The system does not learn from feedback; the same input always gives the same output.

**Future work**
- Expand the catalog so each genre has several songs.
- Add partial credit for related genres (pop and indie pop) and grouped moods (intense, angry, energetic).
- Let users choose a diversity strength instead of an on/off policy.
- Evaluate with real listeners before drawing any conclusions about recommendation quality.

---

## Project Structure

```
AI-musicrecommender/
├── data/songs.csv              # 20 fictional songs (unchanged from VibeFinder 1.0)
├── src/
│   ├── main.py                 # CLI: validation → agent → output
│   ├── recommender.py          # original VibeFinder 1.0 scoring and ranking (unchanged)
│   ├── validation.py           # preference and catalog validation
│   ├── evaluator.py            # runtime reliability evaluator, match %, warnings
│   ├── agent.py                # deterministic recommendation agent and diversity policy
│   ├── logging_config.py       # structured key=value logging to stderr
│   └── evaluate.py             # offline evaluation harness
├── tests/                      # 391 pytest tests
│   ├── test_baseline.py        # VibeFinder 1.0 regression tests
│   ├── test_recommender.py     # original starter tests
│   ├── test_validation.py
│   ├── test_evaluator.py
│   ├── test_agent.py
│   ├── test_app_integration.py
│   └── test_evaluate.py
├── diagrams/architecture.mmd   # system architecture (Mermaid)
├── assets/                     # placeholder for images
├── evaluation_results.md       # evaluation evidence
├── model_card.md               # model card and Responsible AI reflection
├── ai_interactions.md          # AI-assisted development and agent traces
├── pytest.ini
└── requirements.txt
```

Documentation: [model_card.md](model_card.md) · [evaluation_results.md](evaluation_results.md) · [ai_interactions.md](ai_interactions.md) · [diagrams/architecture.mmd](diagrams/architecture.mmd)
