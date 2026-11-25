# 데이터 파이프라인 2차 확장

최신 통합 브랜치 `integration/full-stack`의 `14d33b9`를 기준으로 구현했다.
세 가지 확장은 표본·모집단 및 데이터 품질 메타데이터, 날짜 전후 비교 데이터,
게임 상세 정보와 서로 구분된 두 인기 목록이다.

## 구성

| 모듈 | 책임 |
| --- | --- |
| metadata.py | 실제 정제 스냅샷에 맞춘 표본·모집단, 기간과 단계별 건수 |
| comparison.py | 달력 기간 계산, UTC 경계 검증, 기간별 격리 파이프라인, 비교 상태 |
| game_details.py | 공개 appdetails 검증, 출시일, 이미지·장르, 상세 정보 캐시 |
| rankings.py | 두 공식 차트의 의미 기반 표 파싱, 순위 검증, 스냅샷 가져오기 |
| public_steam.py | HTTPS 호스트 제한, 타임아웃·재시도, 응답 크기 제한 |
| live_validation.py | 명시적으로 실행하는 실제 게임 연결 검증 |
| service.py | 기존 수집·정제 재사용 및 새 기능을 연결하는 Python 인터페이스 |

분석 모듈의 수정은 데이터 메타데이터와 경고를 최종 응답에 전달하고 JSON 숫자를 변환하는 부분이다.
TF-IDF, 군집, VADER, 장단점 분류와 우선순위 계산은 기존 구현을 사용한다.

## 표본과 모집단

`metadata.sampling.selected_counts`와 `selected_ratios`는 실제 반환 DataFrame의 구성이다.
Balanced는 추천·비추천을 별도로 요청하는 표본 설계다. Recent도 각 조건에서 최신 리뷰를
선택하므로 `is_population_representative`는 두 방식 모두 false다.
비율은 모두 0~1이다. UI에서는 100을 곱해 퍼센트로 표시한다.

`matching_population`은 같은 App ID, 언어, 작성 기간, 구매 방식 및 기본 off-topic 필터에
맞는 Steam 응답의 분포다. Recent에서는 첫 페이지 score summary의 두 라벨 합, 전체 합,
`total_matching`이 일치할 때 사용한다. Balanced에서는 조건이 같은 두 라벨 필터의
`total_matching`을 합산한다. 두 호출의 시점이 달라 변화가 생길 수 있다는 경고를 전달한다.
집계가 빠졌거나 불일치하면 객체 전체가 null이다. 합계가 0이면 건수는 0이고 비율은 null이다.
CSV에서는 모집단 정보가 null이다. [Steam 리뷰 명세](https://partner.steamgames.com/doc/webapi/IUserReviewsService)

`population_observed_at_utc`는 라벨별 첫 응답 관측 시각 목록이고
`sample_collected_at_utc`는 실제 제공 스냅샷의 수집 종료 시각 목록이다.
새 시각 필드가 없던 과거 캐시의 모집단 관측 시각은 null이다.
`collection_started_at_utc`, `collection_finished_at_utc`, `processed_at_utc`,
분석 단계의 `analyzed_at_utc`는 각각 API 실행, 정제, 분석 시각이다.

## 품질 건수

`metadata.data_quality`의 필드는 다음과 같다.

| 필드 | 정의 |
| --- | --- |
| language | 요청한 리뷰 언어 |
| requested_review_count | 이번 호출에서 요청한 최대 건수 |
| raw_received_count | 실제 제공 스냅샷의 원본 페이지에 들어 있던 행 수 |
| unique_collected_count | 라벨을 합친 전체 원본에서 유효한 리뷰 ID의 고유 개수 |
| collection_duplicate_count | 수집 단계에서 실제로 버린 중복 행 수 |
| filter_mismatch_count | Balanced 필터와 추천 여부가 달라 정제 입력 전에 제외된 행 수 |
| preprocessing_input_count | 실제 품질 보고서의 정제 입력 행 수 |
| preprocessing_excluded_count | 정제 단계의 제외 행 수 |
| preprocessing_excluded_by_reason | 품질 보고서에 기록된 상호 배타적인 제거 사유 |
| processed_review_count | 저장된 정제 스냅샷의 전체 행 수 |
| analyzed_review_count | 최종 DataFrame의 행 수 |
| analysis_limit_excluded_count | 호출의 limit 때문에 최종 반환에서 제외된 행 수 |
| comparison_excluded_count | 기간 간 ID 충돌이 있을 때 추가 제외된 행 수 |
| comparison_excluded_by_reason | 기간 간 ID 충돌의 추가 제외 사유 |
| excluded_total_count | 위 단계에서 실제로 제외한 행 수의 합 |
| accounting_verified | 같은 스냅샷의 보고서 및 원본 건수 등식 검증 여부 |

기존 collector는 원본 페이지를 모두 보존하고 ID 집합으로 수집 목표를 센다.
행 자체를 버리는 중복 제거는 `prepare()`에서 수행한다. 따라서
`collection_duplicate_count`는 현재 0이며 중복 행은 `duplicate_id`로 정제 단계에 집계된다.
`unique_collected_count`는 별도의 고유 ID 통계여서 정제 입력 행 수와 다를 수 있다.

확인 가능한 API 스냅샷에서는 다음 등식을 검증한다.

```text
raw_received_count
  = collection_duplicate_count + filter_mismatch_count + preprocessing_input_count

preprocessing_input_count
  = preprocessing_excluded_count + processed_review_count

processed_review_count
  = analysis_limit_excluded_count + comparison_excluded_count + analyzed_review_count
```

마지막 등식에서 생략된 `comparison_excluded_count`는 0이다.
과거 CSV 게임 캐시에 게임별 품질 보고서가 없으면 알 수 없는 건수는 null로 제공한다.
다른 게임까지 포함한 CSV 가져오기 보고서의 통계를 특정 게임에 배분하지 않는다.
호환되는 이전 캐시를 제공하면 건수와 작성 기간은 그 캐시 기준이다.
실패한 갱신은 `latest_attempt`, `collection_status`, `error`에서 확인한다.

## 날짜 경계와 캐시

기준일은 이후 구간에 포함한다. `Asia/Seoul`, 기준일 2026-11-01, 7일 창은 다음과 같다.

| 구간 | 로컬 반개구간 | UTC 반개구간 |
| --- | --- | --- |
| 이전 | 10월 25일 00시 이상, 11월 1일 00시 미만 | 10월 24일 15시 이상, 10월 31일 15시 미만 |
| 이후 | 11월 1일 00시 이상, 11월 8일 00시 미만 | 10월 31일 15시 이상, 11월 7일 15시 미만 |

입력 UTC 경계는 시간대를 가진 정수 초 단위 시각이다. 내부 종료 경계에서 1초를 빼
Steam의 포함형 종료 시각에 전달한다. 작성 시각으로 다시 필터링하며 수정 시각을 쓰지 않는다.
잘못된 작성 시각은 `invalid_timestamp_for_period`, 범위를 벗어난 행은
`outside_requested_period`로 제외한다. 언어·App ID·라벨도 검증한다.
기간 조건이나 라벨이 어긋난 응답이 있으면 보수적으로 partial을 반환한다.

두 기간에 같은 리뷰 ID가 남으면 양쪽 반환 DataFrame에서 해당 ID를 제외한다.
원래 정제 스냅샷은 보존하고 추가 비교 제외 건수를 메타데이터에 기록한다.
DST로 달력 일수는 같지만 UTC 경과 시간이 달라지는 시간대에서는
`equal_elapsed_duration=false`와 비교 불가 상태를 반환한다.

캐시 키에는 App ID, UTC 양쪽 경계, 언어, 표본 방식, 요청 건수, review_type, purchase_type,
sort, off-topic 정책, 전처리 정책 버전, 요청·재시도 제한이 들어간다.
경로는 `data/raw/comparisons/<app_id>/<query_hash>/`와
`data/processed/comparisons/<app_id>/<query_hash>/`다.
추천·비추천 원본은 서로 다른 run ID로 저장된다. 일반 게임 캐시와 경로를 공유하지 않는다.
스냅샷을 게시하는 기존 원자적 파일 교체와 SQLite writer lock을 재사용한다.
첫 시도의 부분 수집 자료도 보존하며 기존 정상 캐시는 오류나 빈 갱신으로 덮어쓰지 않는다.
라벨별 attempt와 run.json을 보존하므로 한쪽 실패 뒤 다른 라벨을 수집해도 이어받을 수 있다.
정제 캐시는 run ID와 함께 페이지 수·원본 건수·상태의 revision을 비교한다.
같은 run ID를 재개해 페이지가 추가된 경우에도 이전 부분 정제 결과를 새로 생성한다.

## 비교 상태

| status | 의미 |
| --- | --- |
| complete | 두 창의 실제 유효 행이 목표와 최소 건수를 만족 |
| insufficient_data | 정상 조회했지만 목표 또는 최소 건수 미달 |
| partial | API 중단, 검증 불일치, 기간 간 ID 충돌 또는 UTC 기간 길이 불일치 |
| period_incomplete | 아직 비교 구간의 종료 시각이 오지 않음 |
| empty | 양쪽 모두 정상 조회했고 유효 리뷰가 없음 |
| failed | 양쪽 모두 사용할 데이터가 없음 |

최소 건수 기본값 30은 프로젝트의 분석 입력 정책이다. 통계적 신뢰도를 보장하지 않는다.
목표에 조금 못 미쳐도 양쪽 모두 최소 건수를 만족하고 조건이 검증됐다면
`status=insufficient_data`, `comparison_ready=true`로 제한적 비교를 허용한다.
UI에서는 상태와 부족 이유를 함께 보여준다. `missing_count`는 목표까지 부족한 수,
`minimum_missing_count`는 최소 정책까지 부족한 수다.
한쪽만 완전히 실패하면 전체 상태는 partial이다. 미래 창을 현재 시각에 잘라서 완료로
표시하지 않는다. `comparable_conditions`와 `comparison_ready`를 별도로 확인한다.

## Python 인터페이스

기존 `get_reviews(app_id, limit, refresh, sample_mode="recent")`와 DataFrame 컬럼 계약을 유지한다.
아래 메서드는 `ReviewPipeline` 및 `src.data_pipeline`의 기본 인스턴스 함수로 제공된다.

```python
from src.data_pipeline import ReviewPipeline

pipeline = ReviewPipeline()
period = pipeline.collect_reviews_by_period(
    1091500, "2026-10-24T15:00:00Z", "2026-10-31T15:00:00Z",
    language="english", limit=1000, sample_mode="recent", refresh=False,
)
comparison = pipeline.get_comparison_reviews(
    1091500, "2026-11-01", window_days=7, limit_per_period=100,
    language="english", sample_mode="recent", timezone="Asia/Seoul",
    minimum_required_count=30, refresh=False,
)
before_df = comparison.before.frame
after_df = comparison.after.frame
summary = comparison.summary()  # JSON-compatible metadata, without review text
details = pipeline.get_game_details(1091500)
batch = pipeline.get_game_details_batch([400, 620])
sales = pipeline.get_popular_games("top_sellers", limit=20)
players = pipeline.get_popular_games("most_played", limit=20)
```

기간 수집은 `PeriodReviews(frame: pandas.DataFrame, metadata: dict)`를 반환한다.
전후 비교는 `ComparisonReviews(before, after, conditions, status, comparison_ready,
comparable_conditions, warnings)`를 반환한다. 상세·순위는 dict, 상세 batch는 list[dict]다.
잘못된 ID, 날짜, 언어·옵션은 ValueError다. 수집 오류는 기간별 failed 또는 partial 메타데이터로
변환한다. 로컬 파일 시스템 오류는 예외로 전달한다.

## 게임 상세 정보

상점의 공개 `api/appdetails` JSON을 사용하며 안정성이 보장되는 Steamworks 계약과는 구분한다.
응답 ID·성공 여부·이름을 검증하고 Steam 이미지 호스트의 HTTPS URL만 허용한다.
영어 응답과 us 지역을 기록한다. 장르·이미지·게임 유형·정확한 출시일이 빠지면 partial이다.
`release_date_raw`는 원래 표시값, `release_date`는 정확한 연월일이 파싱된 경우의 ISO 날짜다.
출시 예정, 연도, 분기, 부분 날짜는 정확한 날짜를 임의로 보충하지 않는다.

상세 정보 캐시의 검증된 게임 이름도 키 없는 로컬 검색에 사용된다.
API 장애 시 기존 상세 캐시와 실제 갱신 시각을 유지한다. 이미지 HEAD 연결 검사는
명시적인 `validate-games`에서만 수행한다. 실제 연결 보고서는 `reports/` 아래에 저장한다.
[상점 상세 응답 예시](https://store.steampowered.com/api/appdetails?appids=620&l=english&cc=us)

## 두 인기 목록

판매 목록은 매출 기준이다. 접속자 목록의 `current_players`와 `peak_today_players`는
각각 현재와 오늘 최고 접속자 수다. 두 목록을 통합 점수로 합치지 않는다.
현재 구현은 공식 글로벌 차트에 공개된 표를 의미 기반으로 읽으며 CSS 클래스명에 의존하지 않는다.
순위가 없는 게임에 임의 순위를 붙이지 않고, 후보 20개의 개별 접속자 수로 글로벌 순위를 만들지 않는다.
[판매 순위 설명](https://partner.steamgames.com/doc/store/top_sellers), [글로벌 판매 차트](https://store.steampowered.com/charts/topselling/global), [접속자 차트](https://store.steampowered.com/charts/mostplayed)

순위 응답에는 `ranking_type`, `ranking_metric`, `ranking_scope="global"`, `source`,
`source_url`, `fetched_at_utc`, `cache_used`, `cache_stale`, `status`, `error`, `games`가 있다.
목록 갱신 시각과 각 게임 상세 정보의 갱신 시각을 분리한다. 서식 변경이나 접근 실패 시
이전 목록과 stale 상태를 반환하며, 캐시도 없으면 unavailable과 빈 목록을 반환한다.

공식 차트에서 직접 확인한 JSON을 가져올 수 있다. 입력 필드는 `ranking_type`,
`ranking_metric`, `ranking_scope`, 공식 `source_url`, 실제 `fetched_at_utc`, `games`다.
games의 각 항목은 정수 `rank`, 정수 `app_id`, `name`을 가지며 most_played에서는
`current_players`도 필요하다. 중복 ID·순위, 미래 시각, 잘못된 출처·범위는 거절한다.
출처 URL은 데이터 출처 검증용이며 그 URL을 임의로 요청하는 기능은 제공하지 않는다.

```powershell
python -m src.data_pipeline.cli popular --type top_sellers --snapshot official_snapshot.json
```

## TTL, 요청 한도와 이용 조건

카탈로그와 상세 정보는 24시간, 매출 차트는 30분, 접속자 차트는 10분이 기본 TTL이다.
상세 TTL은 `ReviewPipeline(details_ttl_seconds=...)`, 순위 TTL은
`ReviewPipeline(ranking_ttls={"top_sellers": 1800, "most_played": 600})`,
카탈로그 TTL은 기존 `SteamCatalog(ttl_seconds=...)`로 설정한다.
기간 리뷰는 명시적 refresh로 갱신하며 24시간 경과 여부를 메타데이터로 전달한다.

기간 수집의 HTTP 한도는 기간별 라벨당 100회다. 각 HTTP 호출은 기본 15초 제한,
최대 3회 재시도와 지수 백오프를 적용한다. 상세·차트·이미지 클라이언트는 최대 2회 재시도,
1초 요청 간격, 응답 크기 8 MiB 제한을 사용한다. Retry-After는 120초까지 우선한다.

2026-11-25 확인 시 robots.txt에 두 차트 경로를 차단하는 항목은 없었다.
이 사실이 재배포 허가를 보장하지는 않는다. 차트 HTML과 appdetails는 공개 응답 형식 변경의
영향을 받는다. 로그인·CAPTCHA 우회 기능과 반복 백그라운드 수집기는 두지 않았다.
이번 작업에서 Steam 약관 페이지는 조회 도구로 접근되지 않아 이용 조건 전체의 최신 확인은
완료하지 못했다. 원본 리뷰·캐시·생성 보고서는 Git에서 제외했다.
[Steam robots.txt](https://store.steampowered.com/robots.txt), [Steam Web API 이용 조건](https://steamcommunity.com/dev/apiterms)

## 검증과 남은 제한

모의 테스트는 HTTP 없이 실행한다. 실제 연결은 `validate-games`와 별도 명시적인 비교 실행으로
검증한다. 실제 게임 20개의 모든 상세 조회와 이미지 연결은 성공했다.
한 게임은 출시일이 확정되지 않은 표시여서 상세 완전 확보는 19개다.
리뷰 HTTP 응답은 20개 모두 확인했다. Dota 2는 total_matching이 846,105인데 첫 페이지가
비어 있어 유효 조회 실패로 구분했다. 출시 예정 게임의 정상적인 빈 조회는 0건으로 기록했다.
최종 관측에서는 유효 조회 19개, 실제 리뷰가 포함된 게임 18개다.

2026-11-01을 기준으로 Portal 2의 7일 창은 각각 30건으로 complete와 비교 가능을 확인했다.
Cyberpunk 2077의 50건 목표는 50건·49건으로, 빈 텍스트 1건이 제외되어
insufficient_data와 제한적 비교 가능을 반환했다.
Portal의 하루 창은 16건·28건으로 최소 정책 미달을 확인했다.
별도 Balanced 30건 시험에서는 Steam 비추천 필터가 추천 리뷰 1건을 반환해 이를 제외했고,
양쪽 최종 행은 각각 29건이었다. 필터 불일치가 있는 창은 partial로 표시했다.
실제 응답은 실행 시점에 따라 달라질 수 있으므로 reports의 시각과 건수를 함께 확인한다.

기존 UI 정적 경로와 분석 API를 회귀 검증했다. 신규 비교 결과의 분석과 시각화는 시스템·UI
담당자가 이 계약으로 연결한다. 공용 Steam API의 캐싱과 분리 호출 시점 차이 때문에 모집단
집계를 원자적인 한 시점 측정으로 해석하면 안 된다.

## 최종 검증 기록과 변경 파일

2026-11-25의 기존 통합 테스트는 152개였고, 신규 회귀 테스트 77개를 포함한 최종 결과는
229 passed, 0 failed다. Starlette의 테스트용 httpx 사용 중단 예고 경고 1건이 있었다.
실제 HTTP 연결·모의 테스트·저장한 실제 응답의 재검증은 각각 구분해 기록했다.

실제 일반 분석 API에서는 Recent 40건의 추천율이 92.5%, Balanced 40건의 추천율이 50%였다.
같은 영어·구매 조건의 모집단 추천율은 약 89.27%로 별도 반환됐다.
신규 API 세 개, 기존 분석·검색·health 및 프론트엔드 HTML·JavaScript 제공 경로가 응답했다.
일반·기간 캐시 경로 분리, 같은 run의 재개 후 재정제, 실패한 갱신의 이전 스냅샷 보존을 검증했다.

보고서 경로는 다음과 같다.

- `reports/game_metadata_20_validation.json`, `reports/game_metadata_20_validation.md`
- `reports/date_comparison_live_validation.json`
- `reports/extension_api_live_validation.json`

20게임 보고서의 마지막 실제 응답 확인은 UTC 2026-11-25 12:20경이었다.
Dota 2의 모순된 빈 첫 페이지는 저장한 실제 응답을 재검증하여 실패로 반영했다.
최근 보고서에는 원래 확인 시각과 저장 응답 재평가 시각을 구분해서 기록했다.
매출 차트 관측 시각은 UTC 12:04:30, 접속자 차트는 UTC 12:19:36이다.
보고서와 원본·캐시는 Git에서 제외했다.

| 변경 범위 | 파일 |
| --- | --- |
| 신규 데이터 모듈 | src/data_pipeline/metadata.py, comparison.py, game_details.py, rankings.py, public_steam.py, live_validation.py |
| 기존 데이터 모듈 | src/data_pipeline/service.py, collector.py, preprocessing.py, schema.py, cli.py, __init__.py |
| 백엔드 데이터 계약 | backend/main.py, backend/schemas.py |
| 분석 메타데이터 전달 | src/analysis/pipeline.py |
| 신규 테스트 | tests/data_pipeline/test_metadata.py, test_comparison.py, test_game_details.py, test_rankings.py, test_extension_api.py, test_live_validation.py |
| 기존 테스트 확장 | tests/data_pipeline/test_collector.py |
| 설치 및 제외 규칙 | requirements.txt, requirements-data-pipeline.txt, .gitignore |
| 인수인계 | README.md, docs/PREPROCESSING.md, docs/DATA_SCHEMA.md, docs/API_CONTRACT.md, docs/DATA_PIPELINE_EXTENSION.md |

시스템 담당자는 `comparison.before.frame`과 `comparison.after.frame`을 분석 입력으로 사용한다.
UI 담당자는 새 API의 준비 상태, 표본·모집단 비율, 요청·실제 작성 기간, 언어, 제외 사유,
순위 출처 및 서로 다른 갱신 시각을 표시할 수 있다. 비교 분석 결과와 시각화 연결은 후속 작업이다.
