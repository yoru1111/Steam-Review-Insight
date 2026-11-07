# 데이터 수집·전처리 인수인계

게임 검색, Steam 리뷰 수집, 오프라인 CSV 가져오기, 게임별 캐시, 정제 DataFrame을 제공한다.
[표준 스키마](DATA_SCHEMA.md)와 [설치 및 실행](../README.md#리뷰-수집과-전처리)을 함께 참고한다.

## Steam 원본

Steamworks의 `IUserReviewsService/GetAppReviews/v1/`에 GET 요청을 보낸다.
`input_json`에 App ID, 언어 목록, Recent(1) 또는 Updated(2), 전체 평가(0), 전체 구매 방식(1),
페이지 크기(최대 100), 커서를 넣는다. 첫 커서는 `*`다. 공개 요청이 기본이다.
관련 앱에 연결된 게시자 키를 사용할 때 PowerShell 환경변수 `STEAM_WEB_API_KEY`와 CLI
`--use-key`를 함께 설정한다. 인증 거절 시 공개 요청으로 한 번 전환한다.
[Steamworks API 명세](https://partner.steamgames.com/doc/webapi/IUserReviewsService)

기본 `recent` 표본은 기존과 같이 `review_type=0`으로 최신 추천·비추천 리뷰를 함께 받는다.
분석용 `balanced` 표본은 공식 enum인 Positive(`review_type=1`)와
Negative(`review_type=2`)를 독립적으로 요청한다. 기본 목표는 각각 500건이다. 두 필터는
별도 커서와 원본 캐시를 사용하며, 한쪽 결과가 부족하면 확보한 고유 리뷰만 게시하고 부족 사유를
메타데이터에 남긴다. 중복을 채우기 위해 같은 리뷰를 반복하지 않는다.

```bash
python -m src.data_pipeline.cli pipeline --source api --appid 1091500 --limit 1000 --sample-mode balanced
```

`sampling.matching_population`은 각 필터 응답의 `total_matching`으로 계산한 API 조건 내 실제
추천·비추천 분포다. `sampling.selected_counts`와 `selected_ratios`는 분석을 위해 구성한 표본이다.
균형 표본의 50:50은 설계된 표본 비율이며 전체 Steam 사용자 평가 비율이 아니다.

| 응답 필드 | 처리 |
| --- | --- |
| `response.reviews` | 리뷰 객체 배열. 페이지의 원본 응답을 JSON으로 보존 |
| `response.cursor` | 다음 페이지 요청에 사용. 누락·반복 시 부분 완료 |
| `response.query_summary` | 페이지 크기 검증 및 첫 페이지 집계 기록 |
| `response.total_matching` | Steam이 집계한 필터 일치 수. 로컬 수집 건수와 별개 |
| `reviews[].recommendationid`, `review`, `language`, `voted_up` | 표준 ID, 텍스트, 언어, 추천 여부 |
| `timestamp_created`, `timestamp_updated` | Unix 초를 UTC 문자열로 변환 |
| `author.playtime_at_review`, `author.playtime_forever` | 별개의 플레이 시간 필드 |
| 투표, 구매, 환불 필드 | 표준 메타데이터로 변환. 없는 값은 Null |

429, 500/502/503/504, 연결·읽기 오류는 지수 백오프로 최초 시도 이후 최대 3회 재시도한다.
`Retry-After`를 우선하며 120초를 초과하면 오류를 기록하고 중단한다. HTTP 시도 사이 기본
간격은 1초이며 전체 시도 횟수는 `--max-requests`로 제한한다. 실패나 Ctrl+C 이전에 저장한
페이지와 커서는 `state.json`에 남는다. 조건이 같은 부분 수집은 재실행 시 이어서 진행한다.
이미 호환되는 완전 캐시가 있으면 `--refresh`로 재개를 요청한다. 커서 이상이나 중복 페이지가
발견된 경우 다음 요청은 첫 페이지부터 진행한다. `--refresh --restart`는 새 수집을 시작한다.

정상 캐시가 있는 게임에서 갱신에 실패하면 그 캐시를 제공한다. 처음 수집하는 게임에서 유효한
페이지까지만 저장됐다면 `partial`로 제공할 수 있다. CLI 종료 코드는 성공 0, 사용 가능한
데이터를 반환한 API 실패 또는 부분 수집 2, 사용 가능한 결과 없는 실패 1, Ctrl+C 130이다.
목록에서 확인된 앱이 빈 응답을 보내면 빈 결과로 처리한다. 목록 밖의 ID도 직접 수집할 수 있다.
목록 밖 앱의 첫 응답이 비어 있고 검증된 수집 이력도 없으면 조회 불가 오류를 반환한다.

## 오프라인 CSV

팀원이 준비한 UTF-8 또는 UTF-8-SIG 파일의 헤더를 확인하고 필요하면 아래처럼 표준 필드를
실제 헤더에 연결하는 JSON을 작성한다. 필수 입력은 `review_text`, `voted_up`, `app_id`다.
단일 게임 파일에 App ID 컬럼이 없다면 확인된 ID를 `--appid`로 지정한다. 입력에 식별자가
누락된 개별 행은 제외된다. Steam 추천 여부 컬럼을 매핑하며, 별도로 계산된 감성 점수는 이
필드에 연결하지 않는다.

```json
{
  "review_text": "파일에서 확인한 리뷰 헤더",
  "voted_up": "파일에서 확인한 추천 헤더",
  "app_id": "파일에서 확인한 App ID 헤더"
}
```

언어가 없는 행은 미확인으로 집계하고 분석용 결과에서 제외한다. 파일 설명 등으로 그 행의
언어가 확인된 경우에만 `--csv-language english`처럼 명시할 수 있다. 언어 모델은 사용하지
않는다. 파일을 바꿀 때 새 헤더를 확인한 뒤 매핑과 `--dataset`을 업데이트한다.

- Mendeley Data의 예시 데이터셋은 페이지에 CC BY 4.0으로 표시된다. 배포 시 저자와 출처를
  표기하고 수정 사실을 표시한다. [Mendeley Data 원본](https://data.mendeley.com/datasets/fgh22zvdzm/1)
- Kaggle의 예시 링크는 파일 스키마와 라이선스를 확인하지 못했다. 다운로드 전 데이터 카드에서
  이용 및 재배포 조건을 확인한다. [Kaggle 데이터셋 링크](https://www.kaggle.com/datasets/andrewmvd/steam-reviews)
- Steam 원본은 SteamID와 기타 원본 필드를 포함할 수 있다. Git에서 제외한다. 공유 전 CSV와 보고서
  예문도 확인한다. [Steam Web API 이용 조건](https://steamcommunity.com/dev/apiterms)

## 정제와 검증

1. 앱과 리뷰 ID의 유효성을 검사한다. 같은 키가 반복되면 유효한 수정 시각이 최신인 행을
   보존하며, 같은 시각 또는 두 시각 모두 누락이면 먼저 등장한 행을 사용한다. 충돌 결정은
   `--verbose` 로그에 남긴다. CSV의 ID가 비어 있으면 입력 순번과 매핑된 필드의 SHA-256을
   사용한다. 같은 입력에서 재현되며, 파일의 행 순서나 매핑을 바꾸면 ID가 달라질 수 있다.
2. HTML 엔티티·태그, Unicode NFKC, 제어 문자와 공백을 처리한다. URL, 이메일, 식별 가능한
   Steam ID, 전화번호 및 IPv4를 마스킹한다. 형식이 같은 값은 가려질 수 있고, 패턴으로
   식별하기 어려운 이름 등은 남을 수 있다.
3. `review_clean`에는 소문자화와 아포스트로피 표준화를 적용한다. `not`, `don't`,
   `60 FPS`, `RTX 3070`, `1.2.3` 같은 표현과 이모지·이모티콘을 유지한다.
   불용어 제거, 어간 추출, 표제어 추출은 분석 단계에서 필요에 따라 설정한다.
4. 빈 텍스트, 비정상·누락 추천 라벨, 비대상·미확인 언어를 제외한다. 한 행은 제거 사유 하나로
   집계한다. 시각 누락이나 잘못된 시각은 품질 진단에 기록하며 결과에서 빈 값으로 유지한다.
   시간대가 없는 CSV 시각은 UTC로 해석한다.
5. 스키마, UTF-8, 고유 키, 라벨, 카운트와 부정 표현 보존을 검증한 뒤 게시한다.
   Markdown과 JSON에 제거 사유, 원본 언어 분포, 추천/비추천 비율, 게임·출처·길이 분포,
   작성 시각 범위 및 마스킹된 예문을 기록한다. 표본 100건 미만과 한 라벨이 90% 이상인
   경우 경고한다.

CSV는 입력 행을 순차적으로 읽고, ID별 최신 버전과 정제 결과를 메모리에 둔다. 50,000건을
API 수집 한도로 허용하며 더 큰 CSV에서는 입력 크기에 비례해 메모리가 증가한다. 여러 페이지의
API 원본과 게임별 결과는 로컬에서 누적 보존한다. 캐시 나이는 API 수집 완료 시점 기준이며,
24시간 이상이면 `cache_stale`이 True다. 최신 리뷰는 모집단을 대표하지 않을 수 있고 Steam의
기본 필터는 비관련 활동 리뷰를 제외한다. `sentiment`는 Steam 추천 여부로 정의한다.

## 파일 위치

| 파일 | 용도 |
| --- | --- |
| `data/raw/steam/<app_id>/<run_id>/<page>.json` | Steam 원본 API 응답 |
| `data/raw/steam/<app_id>/state.json` | 활성 원본과 최근 수집 시도, 커서, 요청·완료 시각 |
| `data/processed/games/<app_id>/current.json` | 현재 사용 가능한 정제 버전 |
| `data/processed/games/<app_id>/<generation>/steam_reviews_clean.csv` | 게임별 정제 결과 |
| `data/processed/steam_reviews_clean.csv` | 마지막으로 게시한 CLI 분석용 CSV |
| `reports/quality_report.json`, `reports/quality_report.md` | 기본 CSV에 대응하는 품질 보고서 |

결과가 0건인 갱신에서는 기존 비어 있지 않은 CSV를 보존한다. 빈 결과의 보고서는
`rejected/`에 기록된다. 오프라인 CSV에서 나뉜 게임 캐시의 품질 집계는 최초 가져오기의 전체
보고서를 참조한다. 그 캐시를 재사용해도 집계 단위를 유지하도록 기본 CSV를 다시 게시하지 않는다.
API 응답은 페이지 단위로, 게임별 정제 결과는 스냅샷 단위로 원자적으로 전환한다.
기본 CSV와 보고서 사이의 불일치는 CLI `validate`의 행 수와 SHA-256 검사로 확인할 수 있다.

## UI와 시스템 어댑터

`src.data_pipeline`에서 아래 함수와 `ReviewPipeline`을 가져올 수 있다. 기본 로컬 카탈로그는
[Portal](https://store.steampowered.com/app/400/), [Portal 2](https://store.steampowered.com/app/620/),
[Cyberpunk 2077](https://store.steampowered.com/app/1091500/)의 App ID를 포함한다.
`data/catalog.local.json`에 검증된 게임을 `{"620": "Portal 2"}`와 같은 형태로 추가하면
네트워크와 키 없이 검색할 수 있다. 전체 Steam 목록이 필요할 때는 팀에서 카탈로그를 확장한다.

| 함수 | 입력 → 반환 | 동작 및 오류 |
| --- | --- | --- |
| `search_games(query)` | str → list[dict] | 대소문자 무시 부분 검색. 항목은 `{"app_id": int, "name": str}`. 미일치는 빈 리스트. 잘못된 타입은 TypeError, 잘못된 카탈로그는 ValueError |
| `collect_reviews(app_id, limit=1000)` | int, int → dict | 양의 uint32 ID와 1~50,000건. 호환 캐시 사용, 신규 수집 또는 중간 재개. `refresh=True`로 갱신, `resume=False`로 새 수집. 잘못된 인자는 ValueError, 사용할 데이터가 없으면 CollectionError |
| `preprocess_reviews(app_id)` | int → dict | 네트워크 없이 게임별 원본을 정제하고 결과 경로, 건수, 성공 여부 반환. 사용 가능한 원본이나 정제 캐시가 없으면 CollectionError, 검증 실패는 ValueError |
| `get_processed_reviews(app_id)` | int → pandas.DataFrame | 이미 저장된 게임별 정제 결과를 즉시 읽음. 검증된 빈 게임은 컬럼을 가진 빈 DataFrame. 결과 미생성은 CollectionError |
| `get_collection_status(app_id)` | int → dict | 네트워크 없이 최근 시도, 활성 데이터 상태와 시각, 캐시 나이, 정제 여부를 조회. 미수집은 `not_started` |
| `get_reviews(app_id, limit, refresh, sample_mode="recent")` | int, int, bool, str → tuple[pandas.DataFrame, dict] | `recent`는 기존 최신 표본, `balanced`는 limit을 절반씩 추천·비추천 목표로 나눔. 수집 및 정제 후 시스템 팀 규격으로 반환 |
| `get_balanced_reviews(app_id, limit=1000, refresh=False)` | int, int, bool → tuple[pandas.DataFrame, dict] | 추천·비추천을 독립 수집해 ID 중복 제거 후 교차 배치. 모집단·표본 분포, 요청 수, 부족 사유를 `sampling` 메타데이터로 반환 |

수집 상태의 `collection_status`는 최근 시도, `data_status`는 실제 제공하는 데이터 상태다.
`get_reviews`의 메타데이터는 분석 응답이 읽는 `data_source`에도 `source`와 같은 값을 제공한다.
`source`, `cache_used`, `review_count`, `raw_count`, `last_collected_at_utc`,
`cache_age_seconds`, `cache_stale`, `processed_rows`, `preprocessing_success`, `error`를
사용할 수 있다. 상태 조회 함수의 `cache_used`는 현재 호출에서 캐시를 대체 데이터로 읽었는지
나타내는 요청 단위 플래그이므로, UI에서는 어댑터 반환값의 `cache_used`를 표시한다.

```python
from src.data_pipeline import get_reviews, search_games

matches = search_games("portal")
# 실제 UI에서는 사용자가 선택한 항목의 App ID를 사용한다.
app_id = matches[0]["app_id"]
frame, metadata = get_reviews(app_id, limit=100, refresh=False)
bug_reviews = frame[frame["review_clean"].str.contains("bug", regex=False, na=False)]
```

분석 브랜치와 합친 뒤 시스템 담당자는 기존 앱 팩토리에 어댑터를 전달할 수 있다.

```python
from backend.main import create_app
from src.data_pipeline import ReviewPipeline

app = create_app(ReviewPipeline())
```

데이터가 0건이거나 부분 수집인 경우 UI에서 먼저 건수와 상태를 확인한다.
키워드 검색은 저장된 텍스트에 대한 부분 검색이다. 한국어 UI 검색어를 영문 리뷰에서 찾으려면
UI나 분석 단계에서 `버그`를 `bug`처럼 대응시킬 수 있다.
[시스템 팀의 Adapter 계약](https://github.com/yoru1111/Steam-Review-Insight/blob/feat/analysis-backend/backend/data_adapter.py)
