# 🎧 Model Card: VibeFinder 2.0

## 1. Model Name

**VibeFinder 2.0: Explainable and Reliable Music Recommendation System.**

It is built on **VibeFinder 1.0**, the original content-based music recommendation simulation. The 1.0 scoring algorithm is unchanged and still available as `--mode standard`.

"Model" here means a hand-written, rule-based scoring system. VibeFinder is not a trained machine-learning model and uses no LLM, external AI API, or retrieval system.

---

## 2. Intended Use

**Goal:** recommend five songs that match a listener's stated taste, explain why each song was chosen, and refuse to show results that fail reliability checks.

The listener gives:
- a favorite genre;
- a mood;
- an energy level from 0 (very calm) to 1 (very intense);
- optionally, a valence level (how happy or sad the music sounds) and an acousticness level (how acoustic or electronic it sounds).

**Intended use:** an educational simulation for a graduate applied-AI course. It shows how a content-based recommender turns song features into ranked suggestions, how such a system can fail, and how validation, integrity checks, and evaluation make those failures visible.

**Not intended for:** recommending music to real users, or any decision that matters to a person. VibeFinder:
- does not learn from listening history, likes, or skips;
- assumes one genre, one mood, and a few numbers describe a listener's taste, which is not true for most people;
- cannot predict what anyone will enjoy.

---

## 3. How the System Works

### Scoring (unchanged from VibeFinder 1.0)

Each song earns points for matching the listener:

| Feature | Points |
|---|---|
| **Genre** | 2.0 for an exact match (case and surrounding spaces ignored) |
| **Mood** | 1.5 for an exact match, or 0.75 for a similar mood ("relaxed", "peaceful", and "focused" count as similar to "chill", in both directions) |
| **Energy** | up to 1.0: `1 − |listener energy − song energy|` |
| **Valence** (optional) | up to 0.5, same "closer is better" rule |
| **Acousticness** (optional) | up to 0.5, same rule |

Songs are sorted from highest to lowest score; ties keep catalog order. Each recommendation lists the reasons that earned it points, such as `genre match (+2.0)`.

**Maximum possible score**, for profiles accepted by the application:
- **4.5** for genre, mood, and energy;
- **5.0** when either valence or acousticness is also given;
- **5.5** when both are given.

The legacy low-level functions (`score_song()` and `recommend_songs()`) still accept profiles with missing preferences and simply skip them; an empty profile scores 0. The VibeFinder 2.0 application does **not** allow this: genre, mood, and energy are required and validated before scoring.

### What VibeFinder 2.0 adds around the scoring

1. **Input validation.**
   - Genre and mood must be non-empty text.
   - Energy, valence, and acousticness must be finite numbers from 0 to 1.
   - NaN, infinity, booleans, text such as `"high"`, empty profiles, and unknown keys are rejected with a clear message.
   - Values are never clamped or rewritten.
2. **Catalog validation.** Every CSV row and song record is checked: required columns, unique positive ids, non-blank text, and valid, finite feature values.
3. **Recommendation agent** (deterministic):
   - **PLAN**: set k = 5 and the ranking policy.
   - **ACT**: score the catalog with the unchanged engine.
   - **CHECK**: evaluate the list.
   - **DECIDE**: correct only if the diverse policy is active and an artist repeats.
   - **CORRECT**: at most once.
   - **RECHECK**: verify the final list.
   - **OUTPUT** the verified list, or **BLOCK** it.
4. **Runtime reliability evaluator.** Every list is checked before display.
   - Scores are finite and within range, in descending order, and unique songs from the catalog with unchanged details.
   - Every score and explanation is recomputed from the trusted catalog record.
   - In standard mode, no left-out song outscores the returned ones (9 checks).
   - In diverse mode, there is one song per artist and exactly the expected best song of each top-ranked artist (10 checks).
   - A list that fails is never shown.
5. **Ranking policies.**
   - `standard` is the original top 5.
   - `diverse` is the default: the highest-ranked songs with at most one song per artist. Artist names are compared case-insensitively, ignoring surrounding spaces.
6. **Match score and quality warnings.**
   - Match % = raw score ÷ maximum possible score, labeled Strong (≥ 80%), Moderate (≥ 60%), or Low (< 60%).
   - Warnings flag: low or no strong matches; a genre or mood not in the catalog; a top song whose genre or mood doesn't match (exact and similar moods are distinguished); repeated artists; a list shorter than requested.

---

## 4. Data

The catalog is [data/songs.csv](data/songs.csv): 20 fictional songs, unchanged since VibeFinder 1.0.
- The first 10 songs came with the starter project; 10 were added to cover new genres and moods.
- Each song has 10 fields: id, title, artist, genre, mood, energy, tempo_bpm, valence, danceability, and acousticness. Tempo and danceability are validated but not used in scoring.
- The songs cover 16 genres (pop, lofi, rock, jazz, classical, metal, country, reggae, R&B, hip hop, folk, EDM, blues, ambient, synthwave, indie pop) and 14 moods (happy, chill, intense, peaceful, angry, sad, and others).

**Limitations of the data:**
- The catalog is very small. Lofi has 3 songs, pop and jazz have 2, and the other 13 genres have only 1 song each.
- Only 3 songs have medium energy (between 0.45 and 0.7), so listeners who want medium energy have few close matches.
- There are 18 distinct artists. Two artists appear twice (LoRoom and Neon Echo), which is what triggers the diversity correction for some profiles.
- The data has no lyrics, language, release year, or popularity. It is missing many real-world genres, such as K-pop and Latin music.
- All values were made up for this project. They do not come from real audio analysis.

---

## 5. Strengths

- **It clearly separates calm and intense music.** High-Energy Pop and Chill Lofi share no songs; neither do Chill Lofi and Intense Rock.
- **The top pick is usually a strong match.** Mean top-recommendation match is 92.3% across the five profiles. The exception is the deliberately contradictory profile, at 65.1%.
- **Every result is explained.** Each score lists exactly where its points came from, and the evaluator confirms each explanation matches the scoring rules.
- **Unreliable output is never shown.** Invalid input is rejected before scoring, and corrupted results are blocked instead of displayed.
- **Weak results are labeled, not hidden.** Low matches, unknown genres or moods, and mismatched top picks produce visible warnings.
- **It is reproducible.** The same input always gives the same output, and the evaluation harness produces byte-identical results across runs.

---

## 6. Limitations and Biases

### Limitations and Biases

- **Dataset imbalance.** 13 of 16 genres have a single song. A rock or metal fan gets one good match, and the rest of the list is ranked mostly by energy. Across the five profiles, 60% of standard recommendations are low matches.
- **Handcrafted weights create genre bias.**
  - Genre (2.0) outweighs mood (1.5), so a right-genre, wrong-mood song can beat a better overall fit. For example, *Gym Hero* (pop, intense) outranks *Rooftop Lights* (indie pop, happy) for a happy pop listener.
  - The weights were chosen by a person, not learned from data, so they encode that person's assumptions.
- **Exact genre matching.** "indie pop" earns nothing for a "pop" listener, and a genre absent from the catalog earns no genre points at all.
- **Conflicting preferences are not understood.** For metal + peaceful + energy 0.9, the system recommends calm classical and lofi songs because the mood points outweigh the energy gap. It cannot tell that the request is contradictory; it can only warn that the fit is weak.
- **The diversity trade-off.** The diverse policy reduces the filter-bubble effect of one artist filling the list, but it lowers relevance. The cost falls unevenly by profile: Chill Lofi loses 8.29 percentage points of average match, while three profiles are unaffected.
- **Limits of match scores.** Match % measures only how much of this system's own weighted score a song earns. It is not a confidence level, a probability, or a prediction that a listener will like the song. The 60% and 80% thresholds are design choices, not calibrated values.

**Historical note (VibeFinder 1.0).** When genre was lowered to 1.0 and energy raised to 2.0, genre bias went down. But energy then dominated, and very different songs (rock, EDM, pop) began ranking as if they were the same. The bias moved rather than disappeared, and the original weights were restored.

---

## 7. Evaluation

### Historical baseline (VibeFinder 1.0)

Four stress profiles were run and their top 5 inspected by hand:

| Profile | Preferences | Top 5 (score) |
|---|---|---|
| High-Energy Pop | pop, happy, energy 0.90 | Sunrise City (4.42), Gym Hero (2.97), Rooftop Lights (2.36), Storm Runner (0.99), Neon Pulse (0.95) |
| Chill Lofi | lofi, chill, energy 0.35, valence 0.60, acousticness 0.80 | Library Rain (5.47), Midnight Coding (5.37), Focus Flow (4.69), Spacewalk Thoughts (3.35), Coffee Shop Stories (2.63) |
| Intense Rock | rock, intense, energy 0.95 | Storm Runner (4.46), Gym Hero (2.48), Neon Pulse (1.00), Iron Tempest (0.98), Sunrise City (0.87) |
| Conflicting Preferences | metal, peaceful, energy 0.90 | Iron Tempest (2.93), Winter Nocturne (1.78), Midnight Coding (1.27), Library Rain (1.20), Spacewalk Thoughts (1.13) |

Notable 1.0 findings:
- *Gym Hero* ranked above *Rooftop Lights* for High-Energy Pop because of the genre weight.
- Chill Lofi's top three were all lofi, two of them by LoRoom.
- *Winter Nocturne* (energy 0.18) ranked #2 for a listener asking for energy 0.90.
- High-Energy Pop and Intense Rock shared four songs, because both wanted high energy.

These results are reproduced exactly by today's `--mode standard`.

### Current evaluation (VibeFinder 2.0)

Run with `python -m src.evaluate` and `python -m pytest -q`. Full details are in [evaluation_results.md](evaluation_results.md).

| Result | Value |
|---|---|
| Automated tests | 391 passed, 0 failed |
| Behavioral scenarios | 12/12 passed (3 expected rejections and 2 simulated failures included) |
| Recommendation runs passing integrity | 10/10 (5 profiles × 2 policies) |

| Metric | Standard | Diverse |
|---|---|---|
| Average unique artists per list | 4.6 | 5.0 |
| Lists with a repeated artist | 2/5 | 0/5 |
| Mean of per-list average match | 52.55% | 50.84% (−1.71 percentage points) |
| Mean top-recommendation match | 92.3% | 92.3% |
| Low-match recommendations | 60% | 64% (+4 percentage points) |
| Profiles corrected | — | 2/5 (Default, Chill Lofi) |

**How to read these numbers:**
- The scenario pass rate means the predefined behaviors work as specified.
- The integrity pass rate means each list is internally consistent with the scoring rules and the catalog.
- Match % is a heuristic.
- **None of these is a measure of recommendation accuracy or listener satisfaction, which has not been measured.**

---

## 8. Potential Misuse and Prevention

### Potential Misuse and Prevention

**Possible misuse or misinterpretation**

- **Treating match % as confidence or a guarantee.** "99.6% Strong Match" could be read as "99.6% likely to enjoy."
- **Treating the 100% scenario pass rate as 100% accuracy.**
- **Using the system for real listeners,** or presenting its suggestions as personalized advice it is not designed to give.
- **Hiding failures.** Silently clamping bad input, or re-ranking corrupted results, would show users output that looks fine but isn't.
- **Leaking information through logs.** Logs that record listener preferences or machine paths can expose personal data.

**Mitigations implemented**

- **Safe validation.** Invalid, non-finite, or empty input is rejected before scoring with a clear message. Nothing is silently changed.
- **Output integrity checks.** Every list is checked before display. A list with impossible scores, unknown songs, or explanations that don't match the scoring rules is **blocked** (exit code 3) and never shown. Corrupted results are never re-ranked to disguise them.
- **Transparent explanations.** Every recommendation shows its reasons. Corrections show exactly which song was removed and which was added. `--trace` shows each decision the agent made.
- **Honest labeling.** The output states that match % "is a heuristic share of the maximum score, not a confidence level or a prediction of enjoyment." The evaluation report states that a 100% scenario pass rate "is not a measure of recommendation accuracy."
- **Privacy-aware logging.**
  - Logs record which preference fields were given, never their values.
  - Catalog paths are logged relative to the project, or as a file name only.
  - The evaluation JSON contains no timestamps, absolute paths, or usernames.
- **Clear scope.** This card and the README state that the system is an educational simulation, not for real users.

---

## 9. Reliability Testing Reflection

### Reliability Testing Reflection

Findings from testing VibeFinder 1.0 and 2.0. Each was observed by running the code.

- **Invalid and non-finite input used to reach scoring.**
  - In VibeFinder 1.0, energy 1.5 produced a negative score (−0.32), NaN produced a `nan` score that silently broke the ranking, and `"high"` crashed with a `ValueError`.
  - Now all three are rejected before scoring, and tests confirm the scoring engine is never called for them.
- **Corrupted scores can now be blocked.** In a **simulated** failure, the top score was replaced with 99.0. The evaluator found it out of range (maximum 4.50) and inconsistent with the scoring rules (the recomputed score is 4.48). The agent blocked the list at CHECK, without re-ranking, and exited with code 3.
- **Diversity reduces repeated artists but can lower relevance.**
  - Lists with a repeated artist fell from 2/5 to 0/5.
  - For Chill Lofi, the correction removed *Focus Flow* (LoRoom, 4.685), which is at **standard rank 3**, and added *Winter Nocturne* (Clara Voss, 2.405) at rank 5. That lowered the list's average match by 8.29 percentage points.
  - Across all five profiles, the mean average match fell **1.71 percentage points** (52.55% → 50.84%).
- **A misleading statistic was found during development testing.** A demonstration run of the blocked-list path showed that an early version logged a 2200% match, computed from the corrupted score. Match statistics are now omitted for blocked lists.
- **Passing every integrity check does not mean listeners will enjoy the songs.** Integrity confirms the list is computed correctly from the rules and data. It says nothing about whether the rules capture real taste; Conflicting Preferences passes integrity with a best match of only 65.1%.
- **The fixed evaluation set does not measure real-world accuracy.** Five profiles and twelve hand-written scenarios show the system behaves as designed. They are not a sample of real listeners, and no accuracy or satisfaction measurement was made.

---

## 10. Collaboration with AI

### Collaboration with AI

VibeFinder 2.0 was developed with an AI coding assistant (Claude Code) working in reviewed phases. The student wrote each phase's specification and committed each phase after review. The development record is in [ai_interactions.md](ai_interactions.md).

The statements below are supported by the phase specifications, the phase reports, and the git history.

**Accepted AI suggestion: lock in the baseline before adding anything.** The AI's initial inspection recommended an order:
1. fix the test setup;
2. add regression tests pinning VibeFinder 1.0's exact results;
3. add validation, logging, the evaluator, diversity, the agent, and the harness on top, without changing `score_song()`.

The project followed that order. 48 baseline regression tests were added in Phase 2, before any feature work, and they still pass unchanged apart from one CLI test pinned to `--mode standard`.

**Revised AI suggestion: a policy-aware evaluator instead of disabling a check.** After Phase 4, the AI noted that diverse ranking would conflict with the top-score integrity check. Its report said the check would need to be either turned off for diverse mode (`require_top_scores=False`) or changed to account for diversity. The Phase 5 specification ruled out simply disabling it and required an equivalent check for diverse mode. The final evaluator replaces the check in diverse mode with two independent ones: one song per artist, and exactly the expected selection recomputed from the catalog. This keeps the protection that the suggested shortcut would have removed.

**Not pursued:**
- A Streamlit UI, external LLM APIs, RAG, and automatic preference relaxation were excluded by the project specifications. The starter template's unused `streamlit` and `pandas` entries were removed from `requirements.txt`.
- An early draft of the architecture diagram showed a "Request Corrected Input" loop and a "User Review and Feedback" loop. The final diagram removes both because they were never implemented.

**AI mistakes caught during development**, each found by running the code:
- absolute file paths in logs;
- the misleading 2200% log value;
- one test with a wrong expected value;
- inconsistent integer/float JSON values;
- a report wrongly saying the removed Chill Lofi song was at rank 5.

All were corrected and are documented in [ai_interactions.md](ai_interactions.md).

**Student's original reflection (VibeFinder 1.0, unchanged):**

> My biggest learning moment was the conflicting profile test, where someone who wanted high-energy metal got calm classical and lofi songs just because "peaceful" matched, which showed me how much one weight, like 1.5 points for mood, can control the results. AI helped me write the scoring code, create 10 new songs, and run the stress tests quickly, but I still had to double-check its work, like making sure the README showed real terminal output, that the original weights were back after the experiment, and that the song names and scores in my comparisons were correct. I was surprised that such a simple algorithm, just adding up points for genre, mood, and energy, could already create a filter bubble, like the Chill Lofi list with three lofi songs and two by the same artist. The weight-shift experiment surprised me too, because lowering genre to 1.0 and raising energy to 2.0 didn't remove the bias, it just moved it from genre to energy. Next, I would add more songs for each genre, give partial points for related genres like pop and indie pop, and allow only one song per artist in the top 5. I would also check user input, so values like 1.5 or "high" can't break the scores.

Several of the next steps in that reflection were carried out in 2.0: input checking, and allowing only one song per artist (the diverse policy). The others, more songs per genre and partial credit for related genres, remain future work.

Personal Reflection:
During this project, I learned that making an AI system reliable is different from making it more accurate. My original recommender could calculate scores and recommend songs, but it did not validate its inputs or check whether its outputs were reliable.

I used AI to help plan the development process, implement new components, and create automated tests. One suggestion I accepted was to establish baseline regression tests before adding new features. This helped preserve the original scoring behavior throughout development.

One suggestion I revised was how the evaluator should handle diverse recommendations. Instead of simply disabling the top-score check, I chose a policy-aware evaluator that verifies recommendations according to the selected ranking policy. This allowed the system to improve artist diversity without removing important reliability checks.

The most interesting result was the trade-off between diversity and relevance. Diverse mode eliminated repeated artists in the tested recommendation lists, but the overall average match decreased from 52.55% to 50.84%. This showed me that improving one aspect of an AI system can reduce another.

I also learned that passing 391 automated tests does not mean that the recommendations are always accurate or that users will enjoy every recommended song. Testing provides evidence that the system behaves as designed, while real-world recommendation quality would require feedback from actual listeners.

---

## 11. Future Work

1. **More diverse songs.** At least 3 songs per genre and more medium-energy songs, so every type of listener has more than one good match.
2. **Better genre and mood similarity.**
   - Partial credit for related genres (pop and indie pop, rock and metal).
   - Grouped moods (intense, angry, energetic).
   - Mood credit that considers energy, so a very calm "peaceful" song isn't recommended to someone asking for high energy.
3. **Adjustable diversity.** Let the listener choose how strongly to prefer variety, instead of an on/off policy, and report the relevance cost of each setting.
4. **Better artist identity.** Recognize collaborations, "feat." credits, and aliases.
5. **Real evaluation.** Test with real listeners (ratings or a small user study) before making any claim about recommendation quality.
