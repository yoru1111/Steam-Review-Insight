import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis import AnalysisConfig, analyze_reviews


def sample_frame() -> pd.DataFrame:
    themes = [
        ("The game crashes with awful bugs and errors.", False),
        ("Crash and freeze make this broken game terrible.", False),
        ("Constant bugs ruin every mission.", False),
        ("Low FPS and stutter cause horrible performance.", False),
        ("Terrible lag and poor optimization.", False),
        ("Performance is slow but the story is good.", False),
        ("I love the wonderful story and characters!", True),
        ("Amazing world, beautiful story, great game.", True),
        ("Excellent quests and a fun world.", True),
        ("Combat gameplay is fun and controls are great.", True),
        ("Gameplay is repetitive and boring.", False),
        ("Fun combat and excellent missions.", True),
    ]
    return pd.DataFrame([{"app_id": 999, "game_name": "Sample Game", "review_id": i + 1,
                          "review_text": text, "review_clean": text.lower(), "language": "english",
                          "voted_up": voted, "sentiment": int(voted)}
                         for i, (text, voted) in enumerate(themes)])


if __name__ == "__main__":
    config = AnalysisConfig()
    config.clustering.k = 4
    print(json.dumps(analyze_reviews(sample_frame(), config), indent=2, ensure_ascii=False))
