# Steam 리뷰 CSV 스키마

파일은 쉼표로 구분하며 첫 줄은 아래 순서의 헤더다. 기본 인코딩은 UTF-8-SIG다.
빈 셀은 Null이다. 정제 데이터의 키는 `(app_id, review_id)`다. 두 게임에서 같은 리뷰 ID가
들어와도 별개의 행으로 취급한다. ID 비교 시 문자열을 사용한다.

| 컬럼 | 타입 | Null | 의미 |
| --- | --- | --- | --- |
| source | 문자열 | 아니요 | 원래 입력 출처 `api` 또는 `csv`. 캐시를 사용해도 그대로 유지 |
| app_id | 양의 uint32 | 아니요 | Steam App ID |
| review_id | 문자열 | 아니요 | Steam recommendationid, CSV의 원본 리뷰 ID 또는 `csv-` 해시 |
| review_text | 문자열 | 아니요 | HTML·공백 정리 및 개인정보 마스킹을 거친 대소문자 보존 텍스트 |
| review_clean | 문자열 | 아니요 | 소문자와 표준 아포스트로피를 사용한 분석용 텍스트 |
| language | 문자열 | 아니요 | 원본에 표시된 언어 코드. 기본 내보내기는 `english` |
| voted_up | Boolean | 아니요 | Steam 추천 여부. CSV에서는 True/False |
| sentiment | 정수 0 또는 1 | 아니요 | 추천은 1, 비추천은 0 |
| created_at_utc | UTC ISO 8601 문자열 | 예 | 리뷰 최초 작성 시각 |
| updated_at_utc | UTC ISO 8601 문자열 | 예 | 리뷰 최종 수정 시각 |
| text_length | 정수 | 아니요 | `review_clean`의 Unicode 코드 포인트 수 |
| word_count | 정수 | 아니요 | `review_clean`을 공백으로 나눈 토큰 수 |
| game_name | 문자열 | 예 | 게임 카탈로그 또는 CSV에 제공된 게임 이름 |
| playtime_at_review_minutes | 음이 아닌 정수 | 예 | 리뷰 작성 시점까지의 플레이 시간(분) |
| playtime_forever_minutes | 음이 아닌 정수 | 예 | 응답 시점에 제공된 누적 플레이 시간(분) |
| votes_up | 음이 아닌 정수 | 예 | 유용하다고 평가한 수 |
| votes_funny | 음이 아닌 정수 | 예 | 재미있다고 평가한 수 |
| weighted_vote_score | 유한 실수 | 예 | Steam의 유용성 점수 |
| steam_purchase | Boolean | 예 | Steam에서 구매했는지 여부 |
| received_for_free | Boolean | 예 | 무료 제공 표시 여부 |
| written_during_early_access | Boolean | 예 | 얼리 액세스 중 작성했는지 여부 |
| refunded | Boolean | 예 | 환불 여부 |

`get_processed_reviews`는 pandas DataFrame에서 `app_id`를 uint32, `review_id`를 문자열,
`voted_up`을 bool, `sentiment`를 int8로 유지한다. 선택적 숫자와 Boolean 필드는 pandas nullable
dtype을 사용한다. 날짜별 집계에는 `pd.to_datetime(df["created_at_utc"], utc=True)`를 사용할 수
있다. `sentiment_score`, `sentiment_label`은 시스템 팀의 별도 텍스트 감성 분석 필드다.

CSV를 직접 읽을 때 리뷰 ID 및 `NA`처럼 보이는 정상 리뷰를 유지하려면 아래 설정을 사용할 수 있다.

```python
import pandas as pd

df = pd.read_csv(
    "data/processed/steam_reviews_clean.csv",
    dtype={"review_id": "string"},
    keep_default_na=False,
    na_values=[""],
)
texts = df["review_clean"].tolist()
labels = df["sentiment"].tolist()
```
