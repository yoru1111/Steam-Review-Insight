# Steam Review Insight

Steam Review Insight는 Steam 사용자 리뷰를 수집·정제하고, 반복되는 의견과 개선 우선순위를 웹에서
확인할 수 있는 통합 리뷰 분석 애플리케이션입니다. 게임 이름 또는 Steam App ID를 입력하면 FastAPI
서버가 리뷰 수집과 전처리를 수행하고 TF-IDF, KMeans, VADER 및 규칙 기반 이슈 탐지를 거쳐 결과를
HTML/CSS/JavaScript UI에 표시합니다.

## 주요 기능

- Steam 게임 이름 검색과 App ID 선택
- App ID 직접 입력을 통한 카탈로그 비등록 게임 분석
- Steam 리뷰의 재개 가능한 페이지 수집과 게임별 로컬 캐시
- HTML·공백 정리, 개인정보 마스킹, 언어 필터링, 중복 제거 및 스키마 검증
- 최신 리뷰 표본과 추천·비추천 균형 표본 지원
- TF-IDF와 KMeans를 이용한 리뷰 군집화 및 대표 리뷰 추출
- VADER 기반 텍스트 감성과 Steam 추천 여부의 분리 분석
- 규칙 기반 다중 이슈 탐지와 개선 우선순위 계산
- 간단히/자세히 보기를 제공하는 반응형 웹 UI
- CSV 데이터 가져오기, 품질 보고서 생성 및 CLI 검증

## 기술 스택

| 구분 | 기술 |
| --- | --- |
| 서버/API | Python 3.12, FastAPI, Uvicorn, Pydantic |
| 데이터 처리 | pandas, NumPy, SciPy |
| 분석 | scikit-learn TF-IDF·KMeans·MiniBatchKMeans, vaderSentiment |
| 프론트엔드 | HTML, CSS, Vanilla JavaScript |
| 외부 데이터 | Steam Web API |
| 테스트 | pytest, FastAPI TestClient, httpx |

이 프로젝트는 Streamlit을 사용하지 않습니다. FastAPI가 API와 `frontend/`의 정적 웹 UI를 같은
서버에서 제공합니다.

## 설치 및 실행

아래 명령은 WSL2 Ubuntu 및 일반 Linux의 Bash를 기준으로 합니다. Python 3.12가 필요합니다.

```bash
git clone https://github.com/yoru1111/Steam-Review-Insight.git
cd Steam-Review-Insight

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

uvicorn backend.main:app --reload
```

서버가 시작되면 다음 주소를 사용합니다.

- 웹 UI: <http://127.0.0.1:8000/>
- FastAPI 문서: <http://127.0.0.1:8000/docs>
- 상태 확인: <http://127.0.0.1:8000/api/health>

`requirements.txt`는 웹 서버, 전처리, 분석 및 테스트에 필요한 통합 의존성을 포함합니다.
`requirements-data-pipeline.txt`는 전처리 CLI만 별도 환경에서 사용할 때의 최소 의존성입니다.

## Steam Web API 키 발급 및 설정

전체 Steam 게임 카탈로그를 이름으로 검색하려면 개인 Steam Web API 키가 필요합니다.

1. Steam 계정으로 [Steam Web API Key 발급 페이지](https://steamcommunity.com/dev/apikey)에 로그인합니다.
2. 안내에 따라 도메인을 등록하고 이용 약관에 동의해 키를 발급받습니다.
3. 서버를 실행할 Bash 세션에 키를 환경변수로 설정합니다.

```bash
export STEAM_WEB_API_KEY="발급받은_키"
uvicorn backend.main:app --reload
```

키는 저장소나 `.env.example`에 기록하지 마세요. 애플리케이션은 게임 카탈로그 요청 시 공개 Steam
Web API 호스트의 `IStoreService/GetAppList/v1`을 호출하고 키를 `x-webapi-key` 헤더로 전달합니다.

게임 카탈로그는 `data/catalog.steam.json`에 저장됩니다.

- 정상 캐시는 24시간 동안 재사용합니다.
- 갱신 실패 시 기존 캐시가 있으면 계속 사용합니다.
- 실패 후 같은 서버 프로세스에서는 1시간 동안 원격 갱신을 다시 시도하지 않습니다.
- 캐시가 없거나 키를 설정하지 않았다면 `config/games.json`과 선택적인
  `data/catalog.local.json`만 검색합니다.
- 카탈로그 캐시와 로컬 확장 목록은 Git에 포함되지 않습니다.

API 키가 없어도 Steam App ID를 직접 입력해 리뷰를 수집하고 분석할 수 있습니다. 키가 없는 경우
제한되는 부분은 전체 카탈로그를 이용한 게임 이름 검색입니다. 리뷰 수집 API는 기본적으로 공개 요청을
사용하며, CLI에서 `--use-key`를 지정한 경우에만 환경변수의 키를 사용합니다.

## 웹 UI 사용 방법

1. <http://127.0.0.1:8000/>에 접속합니다.
2. 게임 이름을 검색해 결과를 선택하거나 Steam 상점 URL의 숫자 App ID를 직접 입력합니다.
3. 분석할 리뷰 수와 리뷰 선택 방식을 정합니다.
4. 자세히 보기에서는 군집 수 `k`를 조정할 수 있습니다.
5. 필요하면 **새로 수집**을 선택한 뒤 **분석 시작**을 누릅니다.

리뷰 선택 방식은 다음과 같습니다.

| 방식 | 동작 | 용도와 주의점 |
| --- | --- | --- |
| `recent` (UI: 최신 리뷰) | Steam의 최신 추천·비추천 리뷰 흐름을 그대로 수집 | 최근 반응 확인에 적합하며 실제 비율에 따라 표본이 치우칠 수 있음 |
| `balanced` (UI: 추천·비추천 반반) | 목표 리뷰 수를 추천·비추천에 각각 약 50%씩 배분해 독립 수집 | 불만 이슈 탐색에 유리하지만 표본의 50:50은 Steam 전체 추천 비율이 아님 |

균형 모드에서는 `metadata.sampling.matching_population`에 Steam API 필터 조건에 맞는 모집단의
추천·비추천 수와 비율을 별도로 기록합니다. UI의 모집단 평가는 이 값을 사용하며, 분석용으로 선택한
`selected_ratios`와 구분합니다.

**간단히** 보기는 추천 비율 요약, 주요 불만 TOP 3 및 대표 리뷰를 보여줍니다. 리뷰 3건 미만에서만
탐지된 이슈는 간단히 보기의 TOP 3에서 제외되고 자세히 보기에서 확인할 수 있습니다. **자세히**
보기는 KPI, Steam 추천과 VADER 감성 비교, 이슈 점수 구성, 리뷰 군집과 대표 리뷰를 제공합니다.

## 시스템 구조 및 데이터 처리 흐름

```text
브라우저 (frontend/index.html, app.js, style.css)
    │
    ├─ GET /api/games/search ── ReviewDataAdapter.search_games()
    │                              └─ ReviewPipeline.search_games()
    │                                  ├─ Steam 카탈로그 캐시
    │                                  └─ 로컬 폴백 카탈로그
    │
    └─ POST /api/analyze ───── ReviewDataAdapter.get_reviews()
                                   └─ ReviewPipeline.get_reviews()
                                       ├─ Steam 리뷰 수집 또는 캐시 읽기
                                       ├─ 정제·검증 DataFrame 생성
                                       └─ analyze_reviews()
                                           ├─ TF-IDF
                                           ├─ KMeans / MiniBatchKMeans
                                           ├─ VADER 감성 분석
                                           └─ 이슈 탐지·우선순위 계산
```

`backend.data_adapter.create_default_adapter()`가 실제 `ReviewPipeline`을 생성하므로 전처리 모듈은
기본 FastAPI 앱에 연결되어 있습니다. `/api/analyze`는 동기 요청이며 백그라운드 작업 상태 API는
구현되어 있지 않습니다.

주요 API:

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 서버 상태 확인 |
| GET | `/api/games/search?query=portal` | 게임 이름 검색 |
| POST | `/api/analyze` | App ID의 리뷰 수집·전처리·분석 |

분석 요청 예시:

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"app_id":1091500,"limit":1000,"k":5,"refresh":false,"sample_mode":"balanced"}'
```

## 리뷰 수집·전처리 CLI 사용법

모든 명령은 프로젝트 루트와 활성화된 가상환경에서 실행합니다.

```bash
# 게임 이름 검색
python -m src.data_pipeline.cli search "Stardew Valley"

# 수집 상태 확인
python -m src.data_pipeline.cli status --appid 1091500

# 최신 리뷰 수집
python -m src.data_pipeline.cli collect \
  --appid 1091500 --limit 1000 --language english --sample-mode recent

# 추천·비추천 균형 리뷰 수집
python -m src.data_pipeline.cli collect \
  --appid 1091500 --limit 1000 --language english --sample-mode balanced

# 수집부터 전처리와 기본 CSV 게시까지 실행
python -m src.data_pipeline.cli pipeline \
  --source api --appid 1091500 --limit 1000 --sample-mode recent

python -m src.data_pipeline.cli pipeline \
  --source api --appid 1091500 --limit 1000 --sample-mode balanced

# 기존 원본 캐시를 다시 전처리
python -m src.data_pipeline.cli pipeline \
  --source cache --appid 1091500

# 오프라인 CSV 전처리
python -m src.data_pipeline.cli preprocess \
  --source csv --input data/raw/reviews.csv --mapping mapping.json

# 게시된 정제 CSV와 품질 보고서 검증
python -m src.data_pipeline.cli validate
```

주요 옵션:

- `--refresh`: 원격 API를 다시 요청합니다.
- `--refresh --restart`: 저장된 재개 커서를 사용하지 않고 첫 페이지부터 새 수집을 시작합니다.
- `--sort 1|2`: Steam의 Recent 또는 Updated 필터를 선택합니다.
- `--max-requests`: 한 번의 수집에서 허용할 최대 요청 수를 지정합니다.
- `--use-key`: 리뷰 수집 요청에도 `STEAM_WEB_API_KEY`를 사용합니다.
- `--encoding utf-8|utf-8-sig`: 출력 CSV 인코딩을 선택합니다.

CSV 헤더가 표준 이름 또는 지원 별칭과 일치하면 `--mapping`을 생략할 수 있습니다. App ID 컬럼이
없는 단일 게임 CSV에는 `--appid`를 지정할 수 있습니다. 기본 결과는 다음 위치에 저장됩니다.

| 경로 | 내용 |
| --- | --- |
| `data/raw/steam/<app_id>/` | 페이지별 Steam 원본과 수집 상태 |
| `data/processed/games/<app_id>/` | 게임별 정제 스냅샷 |
| `data/processed/steam_reviews_clean.csv` | 마지막으로 게시한 기본 정제 CSV |
| `reports/quality_report.json` | 품질 검사와 전처리 통계 |
| `reports/quality_report.md` | 사람이 읽을 수 있는 품질 보고서 |

정제 CSV의 주요 컬럼은 다음과 같습니다.

| 컬럼 | 설명 |
| --- | --- |
| `app_id`, `game_name` | Steam 게임 식별 정보 |
| `review_id` | Steam recommendation ID 또는 CSV 기반 재현 가능한 ID |
| `review_text` | 대소문자를 유지하고 개인정보를 마스킹한 표시용 텍스트 |
| `review_clean` | 소문자화와 아포스트로피 표준화를 적용한 분석용 텍스트 |
| `language` | 원본 언어 코드 |
| `voted_up` | Steam 추천 여부 Boolean |
| `sentiment` | Steam 추천 1, 비추천 0 |

전체 컬럼, nullable 타입과 균형 표본 메타데이터는 [데이터 스키마](docs/DATA_SCHEMA.md)를
참고하세요.

## 리뷰 분석 알고리즘 및 우선순위 공식

### TF-IDF와 군집화

- TF-IDF는 기본적으로 unigram과 bigram을 사용하고 최대 5,000개 feature를 생성합니다.
- 영어 stop word를 제거하되 부정 의미 보존을 위해 `no`, `not`, `nor`, `never`는 유지합니다.
- 기본 군집 수는 `k=5`, `random_state=42`입니다.
- 리뷰가 10,000건 이상이면 MiniBatchKMeans를 사용합니다.
- 대표 리뷰는 군집 중심과 TF-IDF 내적이 큰 문서에서 선택합니다.
- 가능한 경우 최대 2,000건 표본으로 silhouette score를 계산합니다.

### 감성과 이슈 탐지

VADER compound가 `0.05` 이상이면 긍정, `-0.05` 이하이면 부정, 그 사이는 중립으로 분류합니다.
이 값은 Steam의 `voted_up`과 별도로 `sentiment_score`, `sentiment_label`에 저장됩니다.

이슈 유형은 공개된 영어 키워드와 문맥 규칙을 이용한 다중 라벨 분류입니다. 한 리뷰가 여러 이슈에
포함될 수 있으므로 이슈별 리뷰 수의 합은 전체 리뷰 수보다 클 수 있습니다. 군집의 이슈 이름은 상위
키워드 기반 참고 라벨이며, 실제 우선순위는 리뷰별 다중 이슈 결과를 집계합니다.

### 우선순위 공식

각 이슈에 대해 다음 값을 0~1 범위로 계산합니다.

```text
Frequency Score = 해당 이슈를 언급한 고유 리뷰 수 / 분석한 전체 리뷰 수
Negative Review Ratio = 해당 이슈 리뷰 중 voted_up=False 비율
Negative Sentiment Severity = mean(max(0, -VADER compound))

Priority Score
  = 0.4 × Frequency Score
  + 0.3 × Negative Review Ratio
  + 0.3 × Negative Sentiment Severity
```

가중치는 `PriorityWeights`로 변경할 수 있으며 합계가 1이어야 합니다. 이 점수는 반복 빈도와 부정적
반응을 결합한 프로젝트 휴리스틱이며 실제 결함의 객관적 심각도나 사업 우선순위를 보장하지 않습니다.

리뷰 몇 건만으로 점수가 높게 나오는 것을 막기 위해, 언급 리뷰가 `AnalysisConfig.min_priority_reviews`
(기본 3건) 미만인 이슈는 `sufficient_evidence: false`로 표시하고 근거가 충분한 이슈 뒤로 정렬합니다.
UI의 간단히/자세히 보기 모두 이 기준으로 순위를 매기며, 미달 이슈는 '근거 리뷰 부족'으로 따로 보여줍니다.

Python에서 전처리된 DataFrame을 직접 분석할 수도 있습니다.

```python
from src.analysis import AnalysisConfig, analyze_reviews

config = AnalysisConfig()
config.clustering.k = 5
result = analyze_reviews(processed_dataframe, config)
```

필수 컬럼은 `review_text`, `review_clean`, `voted_up`이며 `voted_up`은 Boolean이어야 합니다.
샘플 실행은 다음과 같습니다.

```bash
python examples/run_sample.py
```

## 테스트 실행 방법

통합 의존성을 설치한 가상환경에서 실행합니다.

```bash
source .venv/bin/activate
python -m pytest -q
```

테스트는 모의 Steam 응답과 임시 디렉터리를 사용하므로 실제 리뷰 API나 개인 API 키가 없어도
실행할 수 있습니다.

## 프로젝트 폴더 구조

```text
Steam-Review-Insight/
├── backend/                  # FastAPI 앱, 요청 스키마, ReviewDataAdapter
├── config/                   # 기본 게임 폴백 카탈로그
├── data/                     # Git에서 제외되는 원본·정제·카탈로그 캐시
├── docs/                     # API, 전처리, 분석 및 데이터 스키마 문서
├── examples/                 # 분석 파이프라인 실행 예제
├── frontend/                 # HTML/CSS/JavaScript 웹 UI
├── src/
│   ├── analysis/             # TF-IDF, 군집화, VADER, 이슈·우선순위 분석
│   └── data_pipeline/        # Steam 수집, 캐시, CSV, 정제, 검증
├── tests/                    # 분석·API·전처리 자동화 테스트
├── requirements.txt         # 통합 실행 및 테스트 의존성
├── requirements-data-pipeline.txt
└── pyproject.toml
```

## 관련 문서

- [API 계약](docs/API_CONTRACT.md)
- [리뷰 수집·전처리 가이드](docs/PREPROCESSING.md)
- [Steam 리뷰 데이터 스키마](docs/DATA_SCHEMA.md)
- [분석 설계와 한계](docs/ANALYSIS.md)
- [Cyberpunk 2077 10k 표본 실험](cyberpunk_10k_experiment.md)
- [Steam IStoreService API 문서](https://partner.steamgames.com/doc/webapi/IStoreService)
- [Steam Web API 이용 약관](https://steamcommunity.com/dev/apiterms)
