import pandas as pd
import pytest


@pytest.fixture
def reviews_df() -> pd.DataFrame:
    rows = [
        (1, "The game crashes constantly with terrible bugs.", "game crashes constantly terrible bugs", False, 101),
        (2, "Crash and freeze after every update. Broken mess.", "crash freeze every update broken mess", False, 102),
        (3, "Awful bugs cause an error on startup.", "awful bugs cause error startup", False, 103),
        (4, "Great story and beautiful world, I love it!", "great story beautiful world love", True, 104),
        (5, "Amazing characters and a wonderful story.", "amazing characters wonderful story", True, 105),
        (6, "I love exploring this beautiful world.", "love exploring beautiful world", True, 106),
        (7, "Low FPS and constant stutter make performance horrible.", "low fps constant stutter performance horrible", False, 107),
        (8, "Terrible lag and poor optimization even on a good PC.", "terrible lag poor optimization good pc", False, 108),
        (9, "Performance is slow and frames drop badly.", "performance slow frames drop badly", False, 109),
        (10, "Combat gameplay is fun and controls feel great.", "combat gameplay fun controls feel great", True, 110),
        (11, "The gameplay is repetitive and boring.", "gameplay repetitive boring", False, 111),
        (12, "Fun missions and excellent combat.", "fun missions excellent combat", True, 112),
    ]
    return pd.DataFrame([
        {"app_id": 999, "game_name": "Fixture Game", "review_id": rid, "review_text": text,
         "review_clean": clean, "language": "english", "voted_up": voted,
         "sentiment": int(voted), "created_at_utc": "2026-01-01T00:00:00Z",
         "updated_at_utc": "2026-01-01T00:00:00Z"}
        for rid, text, clean, voted, _ in rows
    ])
