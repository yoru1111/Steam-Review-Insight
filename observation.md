# Steam Review Insight: Interim Progress Report

## 1. Project Overview

Steam Review Insight is a team project that turns large collections of Steam user reviews into a compact, explainable summary for game developers and analysts. Its goal is not only to count positive and negative reviews, but also to identify recurring product issues, group similar opinions, and rank issues that may deserve attention.

The current system follows this pipeline:

1. The data pipeline requests public English reviews from Steam and stores paginated raw responses in a local cache.
2. Preprocessing validates identifiers and labels, removes duplicates, cleans text, masks common personal identifiers, and publishes a standardized `pandas` DataFrame.
3. The analysis backend applies TF-IDF, K-means clustering, VADER sentiment analysis, context-aware issue rules, and an issue-priority formula.
4. FastAPI exposes game search and synchronous analysis endpoints. It returns JSON containing summary statistics, sentiment counts, clusters, priority items, representative reviews, sampling metadata, and warnings.
5. A separate team UI branch consumes the API. The UI was implemented by another team member; the present integration branch contains the collection, preprocessing, analysis, and API connection rather than claiming sole ownership of the whole application.

The collection/preprocessing contribution and analysis-backend contribution were combined in merge commit `5b55ba5`. Balanced collection was added in `589d83a`, and two context-aware issue-detection improvements were added in `c5d9cce` and `ce27bf4`.

## 2. Data Collection and Preprocessing

The collector uses Steam's public `IUserReviewsService/GetAppReviews/v1/` endpoint. Requests include an App ID, English language filter, sort option, review-type filter, page size of up to 100, and a cursor. An API key is optional; the tested workflow uses public requests by default. The collector supports resumable pagination, request limits, and exponential backoff for HTTP 429 and retryable server errors. Raw API pages and cursor state are cached locally so that analysis does not require repeated requests.

Preprocessing performs the following main operations:

- validation of App IDs, review IDs, timestamps, language, text, and `voted_up`;
- review-ID deduplication, preserving the newest valid update;
- HTML and Unicode normalization and whitespace cleanup;
- masking of URLs, email addresses, Steam IDs, phone numbers, and IPv4 addresses;
- preservation of useful expressions such as negation, FPS values, hardware names, and emojis;
- publication of a standard schema containing both original review text and normalized `review_clean` text.

Two sampling modes are implemented. `recent` requests the latest mixed stream of recommended and not-recommended reviews. It is useful for monitoring current activity, but its class distribution depends on what Steam returns and can be strongly positive. `balanced` independently requests Positive (`review_type=1`) and Negative (`review_type=2`) reviews, with a default target of 500 each. It removes duplicate review IDs and interleaves the two labels. If one side is short, the system reports the actual count and reason rather than duplicating reviews. Metadata separates the Steam filter population from the selected analysis sample and explicitly marks the balanced sample as not population-representative.

A new reproducible Cyberpunk 2077 experiment collected 10,000 Recent reviews and separate 5,000 Positive plus 5,000 Negative reviews. Preprocessing retained 9,956 Recent reviews (94.60% Positive) and 9,963 Balanced reviews (49.97% Positive). The collector used 100 and 101 public API requests respectively, with no rate-limit error. The final Balanced sample was 37 rows below its raw target because invalid or empty reviews were removed rather than duplicated. A preserved 150-review validation artifact also confirms an earlier stratified evaluation sample with 75 recommended and 75 not recommended reviews. Neither the balanced experiment nor the validation sample estimates the Steam population ratio.

## 3. Analysis Methods

### TF-IDF and K-means

The backend converts `review_clean` into TF-IDF vectors. English stop words are removed, but `no`, `not`, `nor`, and `never` are retained to preserve negation. The default configuration uses unigrams and bigrams, a maximum of 5,000 features, and a maximum document frequency of 0.95.

K-means groups reviews by word-use similarity. The default is `k=5` with `random_state=42`; collections of at least 10,000 reviews use MiniBatchKMeans. Cluster keywords come from high-weight centroid features, and representative reviews are selected by similarity to the centroid. These clusters show lexical patterns rather than guaranteed semantic topics.

The system reports a Silhouette Score when valid clusters form. The score compares within-cluster cohesion with separation from other clusters, using at most 2,000 reviews for efficiency. A low score indicates overlapping vocabulary and weak separation, but even a higher score would not prove that clusters correspond to meaningful product issues.

### VADER sentiment

VADER produces a compound score for each original review. Scores at or above 0.05 are Positive, scores at or below -0.05 are Negative, and the remainder are Neutral. This result is stored separately from Steam's `voted_up` value: recommendation behavior and linguistic sentiment are related but not equivalent.

### Rule-based issue detection

Issue detection is a transparent multi-label rule system. It now separates complaint detection from issue classification, evaluates text by sentence or clause, suppresses negated or resolved problems, and distinguishes praise from problem statements. Supported categories include Bugs/Crashes, Performance, Balance, Gameplay, UI, Monetization, Story/Narrative, Dialogue Length, Content/Open World, Customization, Developer Support, and Quest/Progression Design. New categories require contextual problem phrases rather than bare nouns; for example, “great story” is not a Story issue.

### Issue priority

For every detected issue, the backend calculates:

```text
Frequency = issue review count / total review count
Negative Ratio = fraction of issue reviews with voted_up=False
Negative Severity = mean(max(0, -VADER compound))
Priority = 0.4*Frequency + 0.3*Negative Ratio + 0.3*Negative Severity
```

The score is clipped to 0–1. Because classification is multi-label, issue counts may sum to more than the total number of reviews. Priority is an explainable project heuristic, not an objective measure of defect severity.

## 4. Experimental Results

Cyberpunk 2077 (App ID `1091500`) was analyzed with `k=5` using the current integrated algorithm. Recent contained 9,418 Positive and 538 Negative Steam labels after cleaning; Balanced contained 4,979 Positive and 4,984 Negative. VADER labeled Recent as 62.82% Positive, 26.38% Neutral, and 10.81% Negative, compared with 49.68%, 22.46%, and 27.85% for Balanced.

Five clusters formed in both runs. Because preprocessing reduced both datasets below the 10,000-row threshold, the code used standard `KMeans`, not `MiniBatchKMeans`. Silhouette Scores were calculated on 2,000-review samples: 0.0689 for Recent and 0.0307 for Balanced. The largest clusters contained 8,280 Recent reviews and 5,485 Balanced reviews, confirming very uneven and weakly separated groups. Balanced keywords included more negative terms such as `not`, `boring`, and `crashes`, but broad words such as `game`, `story`, and `good` remained common.

Balanced sampling increased complaint-oriented issue rates: Bugs/Crashes rose from 704/9,956 (7.07%) to 1,806/9,963 (18.13%), Gameplay from 1.56% to 9.18%, and Other/Unclassified from 4.47% to 10.03%. The top Balanced priorities were Gameplay (0.4424), UI/Usability (0.4147), and Bugs/Crashes (0.4145). The top Recent priorities were UI/Usability (0.3121), Dialogue Length (0.2375), and Gameplay (0.2262). These differences demonstrate the effect of sample design, not a change in the Steam population. Full clusters, category counts, priorities, and phase times are preserved in `cyberpunk_10k_experiment.md`.

The frozen initial predictions in the 150-review validation artifact labeled 83 reviews (55.3%) as `Other / Unclassified`. On the later 80-review Gold file, rerunning the three committed classifier versions produced the following descriptive rates over all 80 texts:

| Classifier version | `Other / Unclassified` | No issue returned |
| --- | ---: | ---: |
| Initial keyword classifier (`589d83a`) | 49/80 (61.3%) | 0/80 (0.0%) |
| First context-aware pass (`c5d9cce`) | 5/80 (6.3%) | 58/80 (72.5%) |
| Second context/category pass (`ce27bf4`) | 6/80 (7.5%) | 50/80 (62.5%) |

This change is intentional: the initial classifier forced every unmatched review into `Other`, including praise. The improved versions return no issue for non-complaints and reserve `Other` for complaints without a supported category. The rates are based on a selected Gold file, not the full Steam population.

## 5. Issue Detection Improvements

The initial classifier matched category keywords anywhere in a review and always returned `Other / Unclassified` when no keyword matched. This caused false positives such as treating “I love the gameplay” as a Gameplay problem and “I haven't encountered bugs” as a Bugs issue. It also missed positive reviews that contained a real complaint after a contrast, such as praise followed by a crash report.

The first improvement introduced clause-level context, complaint detection independent of Steam recommendation, negation and resolved-problem suppression, contrast handling, and progression-blocking patterns. It also stopped treating `Other` as an automatic complaint. The second improvement added high-confidence expressions for launch/loading failures, level design and enemy AI, UI and rebinding, hardware compatibility, and price/value. It added six issue families: Story/Narrative, Dialogue Length, Content/Open World, Customization, Developer Support, and Quest/Progression Design. Praise and negated forms were covered by synthetic regression tests.

Human Gold evaluation used 70 issue-eligible rows from the 80-review file; uncertain complaint labels and one pending issue annotation were excluded according to the Gold protocol. Under the official normalization, results were:

| Version | TP | FP | FN | Precision | Recall | Micro-F1 | Exact match |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Initial keyword rules | 20 | 60 | 24 | 0.2500 | 0.4545 | **0.3226** | 0.1714 |
| First context-aware pass | 16 | 9 | 28 | 0.6400 | 0.3636 | **0.4638** | 0.6857 |
| Second category/rule pass | 35 | 8 | 9 | 0.8140 | 0.7955 | **0.8046** | 0.8286 |

Thus Micro-F1 changed from 0.3226 to 0.4638 and then to 0.8046. The first pass mainly removed false positives; the second recovered many previously unsupported labels. These are development-set results, not final generalization results. The same Gold data was inspected during rule improvement, so the final number may overestimate performance on unseen reviews. No Gold review IDs or full review sentences were hardcoded into the classifier or tests, but an independent dataset is still required.

## 6. Limitations

- **Short and imbalanced reviews:** Very short comments provide little context. Recent samples can contain far more recommended than not-recommended reviews, while balancing changes the observed distribution by design.
- **Weak cluster separation:** TF-IDF and K-means group vocabulary, not meaning. The measured Cyberpunk Silhouette Scores (0.0689 Recent and 0.0307 Balanced) confirm substantial overlap.
- **Rule limitations:** Rules remain sensitive to wording, spelling, long-distance context, and category boundaries. Sarcasm and indirect dissatisfaction are particularly difficult.
- **Sentiment limitations:** VADER can misread game terminology, negation scope, mixed opinions, and sarcasm.
- **Sampling interpretation:** A 50:50 Balanced sample improves issue analysis but does not estimate the recommendation ratio of all Steam users.
- **Evaluation leakage:** Gold-guided development requires a new, unused, human-labeled test set. Ideally, two annotators should label independently and adjudicate disagreements.
- **Artifact handling:** Raw pages and processed reviews remain outside Git for privacy. The versioned experiment summary contains aggregates but intentionally omits review text and identifiers.

## 7. Current Progress and Next Steps

### Completed and verified

- public Steam review collection, retries, resumable caching, and CSV import;
- deterministic cleaning, privacy masking, ID deduplication, validation, and quality metadata;
- Recent and Balanced sampling with separate population/sample metadata;
- TF-IDF, K-means/MiniBatchKMeans, Silhouette Score, VADER, multi-label issues, and priority calculation;
- FastAPI health, game search, synchronous analysis, balanced-mode metadata, and preprocessing adapter integration;
- context-aware issue detection and expanded categories;
- 117 automated tests passing after the second improvement, including API, preprocessing, praise/negation regression, and priority representative-review tests.

### Integration status and next work

The FastAPI backend is connected to `ReviewPipeline` and returns the documented JSON structure. The separate `feat/review-web-ui` branch contains a browser UI that consumes this API. Its issue map has fixed labels and colors for the original categories; unknown new categories still render through a generic fallback, but adding translated names, colors, and icons remains a UI-team integration task.

Before the final demonstration, the team should (1) use the preserved 10k Recent/Balanced aggregate report as a reproducible baseline, (2) label a separate unseen test sample, (3) report both accuracy and remaining errors, (4) update the UI mapping for the new issue categories, and (5) merge and smoke-test the UI and API together without committing raw reviews or private data. The final demonstration should clearly distinguish Steam recommendation, VADER sentiment, designed sampling ratios, and model-derived issue priorities.
