from collections import defaultdict
import re
from typing import Any

import pandas as pd


ISSUE_KEYWORDS: dict[str, set[str]] = {
    "Bugs / Crashes": {"bug", "bugs", "crash", "crashes", "error", "broken", "glitch", "freeze"},
    "Performance / Optimization": {"fps", "lag", "stutter", "performance", "optimization", "slow", "frame", "frames"},
    "Game Balance": {"balance", "balanced", "unbalanced", "overpowered", "underpowered", "nerf", "buff", "difficulty"},
    "Gameplay": {"gameplay", "combat", "movement", "controls", "mission", "quest", "boring", "repetitive"},
    "UI / Usability": {"ui", "interface", "menu", "menus", "inventory", "usability", "font", "navigation"},
    "Monetization": {"dlc", "microtransaction", "microtransactions", "paywall", "price", "expensive", "cash", "store"},
}


def classify_text(text: str) -> list[str]:
    tokens = set(re.findall(r"[a-z]+", str(text).lower()))
    matches = [issue for issue, terms in ISSUE_KEYWORDS.items() if tokens & terms]
    return matches or ["Other / Unclassified"]


def add_issue_types(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    source = result["review_clean"].fillna("").astype(str)
    result["issue_types"] = source.map(classify_text)
    return result


def annotate_cluster_types(clusters: list[dict[str, Any]]) -> None:
    for cluster in clusters:
        scores = {issue: len(set(cluster["keywords"]) & terms) for issue, terms in ISSUE_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        cluster["issue_type"] = best if scores[best] else "Other / Unclassified"


def group_by_issue(df: pd.DataFrame) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for pos, types in enumerate(df["issue_types"]):
        for issue in types:
            groups[issue].append(pos)
    return dict(groups)
