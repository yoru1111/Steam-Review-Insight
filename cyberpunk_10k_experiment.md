# Cyberpunk 2077: Recent 10k vs Balanced 10k Experiment

## Experiment setup

- Game: Cyberpunk 2077 (`App ID 1091500`)
- Run date: 2026-11-08 KST
- Branch/algorithm: `integration/analysis-data-preprocessing` at `ce27bf4`
- Recent target: 10,000 latest English reviews
- Balanced target: 5,000 Positive + 5,000 Negative English reviews
- Steam access: public API, no API key
- Clusters: `k=5`, `random_state=42`
- TF-IDF: maximum 5,000 unigram/bigram features
- Silhouette: maximum 2,000-review sample, `random_state=42`
- Raw pages and processed reviews: local Git-ignored `data/` paths

Times below are monotonic process measurements. No raw review text or review IDs are included in this report.

## Collection and preprocessing

| Measure | Recent | Balanced |
| --- | ---: | ---: |
| Target | 10,000 | 5,000 Positive + 5,000 Negative |
| API-collected unique reviews | 10,000 | 5,000 Positive + 5,000 Negative |
| API requests | 100 | 101 |
| Cache used for this call | No | No |
| Collection status | Complete | Complete |
| API/rate-limit error | None | None |
| Reviews after preprocessing | 9,956 | 9,963 |
| Steam Positive | 9,418 (94.60%) | 4,979 (49.97%) |
| Steam Negative | 538 (5.40%) | 4,984 (50.03%) |

Recent preprocessing removed 44 rows with missing review text. The Balanced Steam filters returned 10,000 rows, but four rows from the Negative filter had a mismatched `voted_up` label and were rejected before preprocessing. Preprocessing then removed 32 missing-text rows and one row that became empty after normalization. No duplicate IDs were removed. Balanced collection recorded no shortage, although its final clean sample was 37 rows below the target because invalid rows were not duplicated or replaced.

Steam reported 428,705 reviews matching the experiment's API conditions: 382,342 Positive (89.19%) and 46,363 Negative (10.81%). This API-condition population ratio is different from both the Recent result and the deliberately constructed 50:50 Balanced sample.

## VADER sentiment

| VADER label | Recent | Balanced |
| --- | ---: | ---: |
| Positive | 6,254 (62.82%) | 4,950 (49.68%) |
| Neutral | 2,626 (26.38%) | 2,238 (22.46%) |
| Negative | 1,076 (10.81%) | 2,775 (27.85%) |
| Average compound | 0.3487 | 0.1530 |

Steam recommendation and VADER sentiment are separate variables. In particular, the 50:50 Steam label design did not produce a 50:50 VADER split.

## Clustering

Both clean samples contained fewer than 10,000 rows, so the implementation selected `KMeans`, not `MiniBatchKMeans`. Five clusters formed in each run. Silhouette Scores were calculated from 2,000-review samples.

- Recent Silhouette Score: **0.0689**
- Balanced Silhouette Score: **0.0307**

### Recent clusters

| Cluster | Reviews | Top keywords (first 10) |
| ---: | ---: | --- |
| 0 | 331 | best game, best, game, played, best games, game played, games, game oat, oat, game time |
| 1 | 471 | good, good game, game, game good, really good, good story, choom, pretty, really, game recommend |
| 2 | 347 | peak, peak game, game, game peak, just peak, peak peak, holy, just, bro, say |
| 3 | 527 | game, great, amazing, great game, amazing game, game amazing, story, game great, great story, love |
| 4 | 8,280 | game, fun, love, good, like, story, just, play, yes, games |

### Balanced clusters

| Cluster | Reviews | Top keywords (first 10) |
| ---: | ---: | --- |
| 0 | 5,485 | peak, game, love, boring, choom, yes, panam, no, preem, crashes |
| 1 | 279 | best, best game, game, best games, played, games, ive played, game played, game ive, ive |
| 2 | 3,474 | game, like, not, just, fun, story, it's, play, good, really |
| 3 | 387 | game, amazing, great, great game, amazing game, game amazing, story, game great, love, great story |
| 4 | 338 | good, good game, game, game good, it's good, pretty good, pretty, it's, not good, really good |

The low scores and very uneven cluster sizes show weak lexical separation. Balanced sampling introduced more negative vocabulary, including `not`, `boring`, and `crashes`, but the clusters still mix broad game-related language rather than forming clean issue categories.

## Detected issues and priority

Issue ratios use the clean sample size as the denominator. Reviews may receive multiple labels, so ratios do not sum to 100%.

### Recent

| Priority rank | Issue | Reviews | Ratio | Priority Score |
| ---: | --- | ---: | ---: | ---: |
| 1 | UI / Usability | 12 | 0.12% | 0.3121 |
| 2 | Story / Dialogue Length | 8 | 0.08% | 0.2375 |
| 3 | Gameplay | 155 | 1.56% | 0.2262 |
| 4 | Content / Open World | 6 | 0.06% | 0.2245 |
| 5 | Story / Narrative | 11 | 0.11% | 0.2084 |
| 6 | Game Balance | 29 | 0.29% | 0.1741 |
| 7 | Bugs / Crashes | 704 | 7.07% | 0.1685 |
| 8 | Developer Support | 2 | 0.02% | 0.1501 |
| 9 | Monetization | 46 | 0.46% | 0.1406 |
| 10 | Performance / Optimization | 55 | 0.55% | 0.1340 |
| 11 | Other / Unclassified | 445 | 4.47% | 0.1151 |
| 12 | Customization | 2 | 0.02% | 0.0001 |
| 13 | Quest / Progression Design | 1 | 0.01% | 0.0000 |

### Balanced

| Priority rank | Issue | Reviews | Ratio | Priority Score |
| ---: | --- | ---: | ---: | ---: |
| 1 | Gameplay | 915 | 9.18% | 0.4424 |
| 2 | UI / Usability | 67 | 0.67% | 0.4147 |
| 3 | Bugs / Crashes | 1,806 | 18.13% | 0.4145 |
| 4 | Story / Narrative | 74 | 0.74% | 0.4060 |
| 5 | Content / Open World | 33 | 0.33% | 0.3942 |
| 6 | Story / Dialogue Length | 44 | 0.44% | 0.3936 |
| 7 | Performance / Optimization | 138 | 1.39% | 0.3856 |
| 8 | Game Balance | 86 | 0.86% | 0.3817 |
| 9 | Monetization | 198 | 1.99% | 0.3807 |
| 10 | Other / Unclassified | 999 | 10.03% | 0.3748 |
| 11 | Quest / Progression Design | 8 | 0.08% | 0.3349 |
| 12 | Developer Support | 5 | 0.05% | 0.2633 |
| 13 | Customization | 4 | 0.04% | 0.1864 |

Balanced sampling substantially increased the observed frequency and priority of complaint-oriented categories. For example, Bugs/Crashes increased from 7.07% to 18.13%, Gameplay from 1.56% to 9.18%, and Other/Unclassified from 4.47% to 10.03%. This is an expected consequence of the sampling design and must not be interpreted as a change in the underlying Steam population.

## Execution time

| Phase | Recent | Balanced |
| --- | ---: | ---: |
| Collection | 143.88 s | 140.36 s |
| Preprocessing | 0.82 s | 1.08 s |
| Analysis | 4.61 s | 8.54 s |
| Total by measured phases | 149.32 s | 149.98 s |

Combined measured phase time was **299.30 seconds (approximately 4 minutes 59 seconds)**. Collection dominated runtime because public API requests retained the one-second request interval.

## Interpretation limits

Recent and Balanced answer different questions. Recent approximates a current review stream and was 94.60% Positive after cleaning. Balanced is a designed diagnostic sample and intentionally gives Negative reviews much more influence. Consequently, differences in sentiment, issue frequency, priorities, clusters, or silhouette must not be treated as population-level model performance differences. VADER, clustering, and rule-based issues also remain heuristic outputs that require human validation.
