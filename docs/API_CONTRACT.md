# API Contract

## `GET /api/health`

분석 서버 생존 여부를 반환합니다. 수집 Adapter 연결 여부와는 별개입니다.

## `GET /api/games/search?query=...`

성공 응답은 `{"games": [{"app_id": 1091500, "name": "..."}]}` 형태입니다. 현재 Adapter가
없으면 `503`, upstream 검색 실패는 `502`, 파라미터 오류는 `422`입니다.

## `POST /api/analyze`

요청:

```json
{"app_id": 1091500, "limit": 1000, "k": 5, "refresh": false}
```

`app_id > 0`, `2 <= limit <= 10000`, `2 <= k <= 50`입니다. 동기 요청이며 응답 최상위에는
`game`, `summary`, `sentiment`, `clustering`, `clusters`, `priorities`, `metadata`, `warnings`가
있습니다. 분석 입력 오류는 `422`, Adapter 미연결은 `503`, 예상하지 못한 오류는 `500`입니다.

각 cluster는 번호, 개수, 상위 키워드, 참고 이슈 유형, Steam 추천/비추천 비율, VADER 통계와
대표 리뷰를 포함합니다. 각 priority는 이슈 유형, 개수, 전체 대비 비율, 부정 비율, 평균 compound,
부정 강도, 점수, 대표 리뷰와 `score_basis`를 포함합니다.

## `GET /api/analyze/status/{job_id}`

현재 백그라운드 작업을 구현하지 않았기 때문에 `501 Not Implemented`를 반환합니다. 존재하지 않는
진행 상태를 만들지 않습니다.
