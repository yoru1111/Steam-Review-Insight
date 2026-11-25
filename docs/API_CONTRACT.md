# API Contract

## `GET /api/health`

분석 서버 생존 여부를 반환합니다. 수집 Adapter 연결 여부와는 별개입니다.

## `GET /api/games/search?query=...`

성공 응답은 `{"games": [{"app_id": 1091500, "name": "..."}]}` 형태입니다. 현재 Adapter가
없으면 `503`, upstream 검색 실패는 `502`, 파라미터 오류는 `422`입니다.

## `POST /api/analyze`

요청:

```json
{"app_id": 1091500, "limit": 1000, "k": 5, "refresh": false, "sample_mode": "balanced"}
```

`sample_mode`는 기존 동작인 `recent`가 기본값이며 `balanced`를 선택하면 추천·비추천 목표를
절반씩 나눕니다. `app_id > 0`, `2 <= limit <= 10000`, `2 <= k <= 50`입니다. 동기 요청이며 응답 최상위에는
`game`, `summary`, `sentiment`, `clustering`, `clusters`, `priorities`, `positive_aspects`, `metadata`, `warnings`가
있습니다. 분석 입력 오류는 `422`, Adapter 미연결은 `503`, 예상하지 못한 오류는 `500`입니다.

각 cluster는 번호, 개수, 상위 키워드, 참고 이슈 유형, Steam 추천/비추천 비율, VADER 통계와
대표 리뷰를 포함합니다. 각 priority는 이슈 유형, 개수, 전체 대비 비율, 부정 비율, 평균 compound,
부정 강도, 점수, 대표 리뷰와 `score_basis`를 포함합니다. 언급 리뷰 수가 `metadata.config.min_priority_reviews`
(기본 3) 미만인 이슈는 `sufficient_evidence: false`이며, 점수와 관계없이 근거가 충분한 이슈 뒤에 정렬됩니다.
UI는 이 이슈를 순위에서 빼고 '근거 리뷰 부족'으로 따로 보여줍니다.

`positive_aspects`는 Steam 추천 여부나 VADER 감성 라벨이 아니라, 리뷰 문장에서 구체적인 대상과
긍정 표현이 함께 발견된 결과를 다중 라벨로 집계한 배열입니다. 일반적인 칭찬만 있는 리뷰에는 요소를
추정하지 않습니다. `review_ratio`의 분모는 분석한 전체 리뷰 수입니다. 한 리뷰가 여러 긍정 요소에
포함될 수 있으므로 요소별 `review_count` 또는 `review_ratio`의 합은 전체 리뷰 수 또는 100%를 넘을 수
있습니다. `positive_ratio`는 그 요소를 칭찬한 리뷰 중 Steam에서 추천한 리뷰의 비율로, 집계 이후에
참고용으로 붙이는 값이며 탐지에는 쓰이지 않습니다. 현재 `aspect_type`은 `Gameplay`, `Graphics / Visuals`,
`Sound / Music`, `Story / Narrative`, `Content / Exploration` 중 하나입니다.

```json
{
  "positive_aspects": [
    {
      "aspect_type": "Sound / Music",
      "review_count": 24,
      "review_ratio": 0.12,
      "positive_ratio": 0.92,
      "representative_reviews": [
        {"review_id": 123456789, "text": "The soundtrack is amazing, but combat feels repetitive."}
      ]
    }
  ]
}
```

`positive_aspects`와 `priorities`는 독립적으로 탐지됩니다. 따라서 긍정·부정이 섞인 같은 리뷰가
긍정 요소의 대표 리뷰이면서 동시에 특정 불만 유형 집계에도 포함될 수 있습니다.

균형 모드 응답의 `metadata.sampling`에는 실제 API 조건의 모집단 분포와 분석 표본 분포가 별도로
포함됩니다. `selected_ratios`의 50:50은 분석 설계이며 Steam 전체 평가 비율이 아닙니다.

## `GET /api/analyze/status/{job_id}`

현재 백그라운드 작업을 구현하지 않았기 때문에 `501 Not Implemented`를 반환합니다. 존재하지 않는
진행 상태를 만들지 않습니다.

## 2차 확장 메타데이터

기존 분석 응답의 `summary`, `sentiment`, `clustering`, `clusters`, `priorities`,
`positive_aspects`와 기존 metadata 필드를 유지한다. `summary.positive_ratio`는 표본 추천율이다.
UI는 실제 Steam 조건의 추천율을 표시할 때 `metadata.sampling.matching_population.positive_ratio`를
사용하며 객체나 비율이 null이면 미확인으로 표시한다.

| metadata 객체 | 주요 필드 |
| --- | --- |
| sampling | mode, matching_population, population_conditions, selected_counts, selected_ratios, is_population_representative, sampling_method_known, population_observed_at_utc, sample_collected_at_utc |
| data_quality | language, requested_review_count, raw_received_count, unique_collected_count, collection_duplicate_count, filter_mismatch_count, preprocessing_input_count, preprocessing_excluded_count, preprocessing_excluded_by_reason, processed_review_count, analyzed_review_count, analysis_limit_excluded_count, excluded_total_count, accounting_verified |
| review_period | requested_start_utc, requested_end_exclusive_utc, actual_start_utc, actual_end_utc |
| 실행 및 캐시 | collection_started_at_utc, collection_finished_at_utc, processed_at_utc, analyzed_at_utc, cache_age_seconds, cache_stale, cache_used, collection_status, latest_attempt, warnings |

비율은 0~1이며 통계가 없는 과거 캐시의 건수는 null이다. 표본과 모집단의 관측 시각을 구분한다.
제외 사유별 건수와 등식, 상세 Python 반환 타입은 [확장 계약](DATA_PIPELINE_EXTENSION.md)에 정의했다.

## `POST /api/reviews/compare`

데이터 준비 상태와 메타데이터를 반환하는 동기 API다.

```json
{
  "app_id": 1091500,
  "reference_date": "2026-11-01",
  "window_days": 7,
  "timezone": "Asia/Seoul",
  "language": "english",
  "limit_per_period": 100,
  "sample_mode": "recent",
  "minimum_required_count": 30,
  "refresh": false
}
```

기본값은 window_days=14, timezone=Asia/Seoul, language=english, limit_per_period=1000,
sample_mode=recent, minimum_required_count=30, refresh=false다.
window_days는 1~365, limit_per_period는 2~10000, App ID는 양의 uint32 범위다.

최상위 응답 키는 `before`, `after`, `conditions`, `status`, `comparison_ready`,
`comparable_conditions`, `warnings`다. before와 after는 각 기간의 메타데이터 dict다.
각 기간에는 sampling, data_quality, review_period와 다음 준비 상태 필드가 들어간다.

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| status | str | complete / insufficient_data / partial / period_incomplete / empty / failed |
| requested_count | int | 기간당 목표 수 |
| collected_count | int 또는 null | 실제 스냅샷 원본의 고유 리뷰 ID 수 |
| processed_count | int | 비교에 반환할 유효 DataFrame의 행 수 |
| minimum_required_count | int | 프로젝트 최소 입력 정책 |
| missing_count | int | 목표까지 부족한 건수 |
| minimum_missing_count | int | 최소 정책까지 부족한 건수 |
| shortage_reason | str 또는 null | 부족·중단 사유 |
| comparison_ready | bool | 해당 기간이 최소 정책과 검증 조건을 만족하는지 여부 |
| conditions_verified | bool | 작성 시각, 언어, App ID 및 라벨 검증 결과 |
| query | object | 해당 기간의 전체 수집·정제 조건 |
| query_hash | str | 조건별 캐시 식별자 |
| requested_period_start_utc | str | 요청 시작 시각 포함 |
| requested_period_end_exclusive_utc | str | 요청 종료 시각 미포함 |

`conditions`는 App ID, 언어, sample_mode, 요청 건수, 정렬·구매·off-topic 정책,
전처리 버전 및 요청 제한, 기준일, timezone, window_days와 UTC 양쪽 경계를 포함한다.
DST로 실제 UTC 기간 길이가 다르면 equal_elapsed_duration=false다.

HTTP 200에서도 데이터 준비 상태가 failed, partial 또는 insufficient_data일 수 있다.
UI는 `comparison_ready`와 status를 함께 표시한다. 잘못된 날짜·시간대·옵션은 422,
새 기능을 지원하지 않는 어댑터는 503, 로컬 데이터 접근 오류 등은 502다.
리뷰 원문이나 전체 DataFrame은 HTTP 응답에 넣지 않는다. 시스템 팀은 Python의
`ReviewPipeline.get_comparison_reviews(...).before.frame`과 `after.frame`을 사용한다.

## `GET /api/games/details/{app_id}?refresh=false`

| 필드 | 타입 |
| --- | --- |
| app_id | int |
| name, header_image, release_date, release_date_raw | str 또는 null |
| genres | list[str] |
| coming_soon | bool 또는 null |
| store_url, source, source_url | str |
| fetched_at_utc | UTC 문자열 또는 null |
| cache_used | bool |
| cache_stale | bool 또는 null |
| metadata_status | complete / partial / unavailable |
| missing_fields | list[str] |
| error | str 또는 null |

성공한 상세 응답에는 region, response_language, cache_age_seconds와 short_description,
developers, publishers, is_free, game_type, supported_languages도 포함한다.
정확한 출시일이 없으면 release_date는 null이며 release_date_raw를 함께 표시할 수 있다.
조회 불가 게임은 HTTP 200과 metadata_status=unavailable로 반환하며, 잘못된 ID는 422다.

## `GET /api/games/popular?type=top_sellers&limit=20&refresh=false`

type은 top_sellers 또는 most_played, limit은 1~100이다.
top_sellers는 revenue, most_played는 current_concurrent_players를 기준으로 하는 글로벌 목록이다.
응답은 ranking_type, ranking_metric, ranking_scope, source, source_url, fetched_at_utc,
cache_used, cache_stale, status, error, games를 포함한다.

games 항목은 rank, app_id, name, header_image, genres, release_date, current_players,
peak_today_players, ranking_source, ranking_fetched_at_utc, details_fetched_at_utc,
metadata_status, game_type을 포함한다. 판매 목록의 접속자 수는 null이다.
순위와 상세 메타데이터 갱신 시각이 다를 수 있다.
status는 available / stale / unavailable이다. 캐시도 없는 unavailable의 games는 빈 배열이다.
기본 TTL은 판매 30분, 접속자 10분, 상세 24시간이다. UI는 source와 실제 갱신 시각을 같이 표시한다.
