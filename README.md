# Steam Review Insight — Analysis Backend

전처리된 Steam 리뷰 `pandas.DataFrame`을 메모리에서 받아 TF-IDF, K-means, VADER 감성,
이슈 유형과 개선 우선순위를 계산하는 독립 백엔드입니다. CSV는 필수 경로가 아닙니다.

## 설치와 실행

Python 3.12 기준입니다.

```bash
cd /home/jimmy099/steam-review-insight
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
pytest
uvicorn backend.main:app --reload
```

서버 실행 후 `http://127.0.0.1:8000/docs`에서 API를 확인합니다. 현재 기본 Adapter는
전처리 팀 모듈이 연결되지 않았으므로 검색과 App ID 분석에 `503`을 반환합니다.

샘플 DataFrame 분석:

```bash
python examples/run_sample.py
```

Python 코드에서 직접 사용:

```python
from src.analysis import AnalysisConfig, analyze_reviews

config = AnalysisConfig()
config.clustering.k = 5
result = analyze_reviews(processed_dataframe, config)
```

필수 컬럼은 `review_text`, `review_clean`, `voted_up`입니다. `app_id`, `game_name`,
`review_id`가 있으면 결과 식별자에 사용합니다. 기존 `sentiment`와 `voted_up`은 수정하지 않고
VADER 결과를 `sentiment_score`, `sentiment_label`로 별도 생성합니다.

## 분석 방식

- TF-IDF: 영어 stop word만 제외하며 `review_clean`에 추가 정규화를 하지 않습니다. 부정 의미
  보존을 위해 `no`, `not`, `nor`, `never`는 stop-word에서 제외합니다. n-gram, 문서 빈도와 최대
  feature 수는 설정 가능합니다.
- K-means: 기본 `k=5`, `random_state=42`; 10,000건 이상은 MiniBatchKMeans를 사용합니다.
  대표 리뷰는 군집 중심과 cosine-equivalent TF-IDF 내적이 큰 문서입니다.
- 품질: 가능한 경우 silhouette score를 계산하며 2,000개로 샘플링합니다. 낮거나 유효 군집이
  부족하면 경고를 반환합니다.
- 유형: 설명 가능한 키워드 규칙의 다중 라벨 분류입니다. 군집 이름은 상위 키워드 기준의 참고
  라벨이고, 우선순위 집계는 리뷰별 다중 라벨을 사용합니다.

## 우선순위 공식

각 이슈 유형에 대해 다음을 0~1 범위로 계산합니다.

```text
Frequency Score = 해당 유형을 언급한 고유 리뷰 수 / 분석한 전체 리뷰 수
Negative Review Ratio = 해당 유형 리뷰 중 voted_up=False 비율
Negative Sentiment Severity = mean(max(0, -VADER compound))
Priority = 0.4*Frequency + 0.3*Negative Ratio + 0.3*Severity
```

한 리뷰가 여러 이슈에 포함될 수 있으므로 유형별 리뷰 수 합계는 전체 수보다 클 수 있습니다.
가중치는 `PriorityWeights`로 변경하며 합계가 1이어야 합니다. 이 점수는 프로젝트 휴리스틱이고
실제 결함의 객관적 심각도가 아닙니다.

## 전처리 모듈 연결

`backend.data_adapter.ReviewDataAdapter` 계약을 구현하여 앱 팩토리에 전달합니다.

```python
class TeamAdapter:
    def search_games(self, query): ...
    def get_reviews(self, app_id, limit, refresh):
        # return (processed_dataframe, metadata_dict)
        ...

app = create_app(TeamAdapter())
```

팀 모듈의 실제 함수명과 반환값이 확정되면 이 Adapter만 수정합니다. 수집, 캐시, API 오류 처리는
전처리 계층의 책임이고 분석 모듈은 DataFrame만 소비합니다.

## Streamlit 연동

```python
import requests
result = requests.post("http://127.0.0.1:8000/api/analyze",
    json={"app_id": 1091500, "limit": 1000, "k": 5, "refresh": False}, timeout=300)
result.raise_for_status()
data = result.json()
```

상세 계약은 [docs/API_CONTRACT.md](docs/API_CONTRACT.md), 분석 한계는
[docs/ANALYSIS.md](docs/ANALYSIS.md)를 참고합니다.

## 리뷰 수집과 전처리

프로젝트 루트에서 Python 3.12를 사용한다. Windows PowerShell에서는 가상환경의 Python을
직접 호출하면 활성화 스크립트 설정 없이 실행할 수 있다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-data-pipeline.txt
.\.venv\Scripts\python.exe -m pytest -q
```

가상환경을 활성화한 뒤에는 아래 명령의 `python`을 그대로 사용할 수 있다. 활성화하지 않았다면
`.\.venv\Scripts\python.exe`를 사용한다.

```powershell
python -m src.data_pipeline.cli search portal
python -m src.data_pipeline.cli collect --appid 1091500 --limit 100 --language english
python -m src.data_pipeline.cli collect --appid 1091500 --limit 10000 --language english
python -m src.data_pipeline.cli pipeline --source api --appid 1091500 --limit 1000
python -m src.data_pipeline.cli pipeline --source api --appid 1091500 --limit 1000 --sample-mode balanced
python -m src.data_pipeline.cli pipeline --source cache --appid 1091500
python -m src.data_pipeline.cli preprocess --source csv --input data/raw/reviews.csv --mapping mapping.json
python -m src.data_pipeline.cli validate
```

CSV 헤더가 표준 이름 또는 지원하는 별칭과 일치하면 `--mapping`을 생략할 수 있다.
`--refresh`로 API를 다시 요청하고 `--refresh --restart`로 첫 페이지부터 재수집한다.
`--encoding utf-8`을 지정하면 BOM 없이 내보낸다. 기본 CSV와 품질 보고서는
`data/processed/steam_reviews_clean.csv`와 `reports/quality_report.{json,md}`에 저장된다.
실데이터와 모의 테스트는 별도 경로에 저장되며 테스트에는 네트워크가 필요 없다.

```python
from src.data_pipeline import get_reviews

frame, metadata = get_reviews(app_id=1091500, limit=100, refresh=False)
```

`frame`의 `review_clean`과 `voted_up`을 분석 입력으로 사용한다. `sentiment`는 Steam의
추천 여부를 0과 1로 표현한 컬럼이다. [전처리 및 UI·시스템 연동 가이드](docs/PREPROCESSING.md)와
[표준 스키마](docs/DATA_SCHEMA.md)를 참고한다.
