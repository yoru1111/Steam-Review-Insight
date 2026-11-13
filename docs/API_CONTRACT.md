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
있습니다. 현재 `aspect_type`은 `Gameplay`, `Graphics / Visuals`, `Sound / Music`, `Story / Narrative`,
`Content / Exploration` 중 하나입니다.

```json
{
  "positive_aspects": [
    {
      "aspect_type": "Sound / Music",
      "review_count": 24,
      "review_ratio": 0.12,
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
