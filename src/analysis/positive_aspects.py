import re
from typing import Any

import pandas as pd


CLAUSE_BOUNDARY = re.compile(
    r"(?:[.!?;\n]+|\b(?:but|however|although|though|yet|while|whereas)\b)", re.IGNORECASE
)
NEGATED_PRAISE = re.compile(
    r"\b(?:not|never|hardly|barely)\s+(?:really\s+|very\s+|that\s+)?"
    r"(?:good|great|amazing|excellent|beautiful|stunning|fun|enjoyable|engaging|satisfying|"
    r"immersive|wonderful|fantastic|incredible|memorable|compelling|rich|rewarding|polished)\b"
    r"|\b(?:is|are|was|were|do|does|did|have|has|had)n['’]?t\s+"
    r"(?:really\s+|very\s+|that\s+)?(?:good|great|amazing|excellent|beautiful|stunning|fun|"
    r"enjoyable|engaging|satisfying|immersive|wonderful|fantastic|incredible|memorable|"
    r"compelling|rich|rewarding|polished|love|like|enjoy|appreciate)\b"
    r"|\b(?:do|does|did)n['’]?t\s+(?:really\s+)?(?:love|like|enjoy|appreciate)\b",
    re.IGNORECASE,
)


def _patterns(targets: str, praise: str) -> tuple[re.Pattern[str], ...]:
    intensifier = r"(?:(?:really|very|extremely|incredibly|surprisingly)\s+)?"
    copula = r"(?:is|are|was|were|feels?|felt|looks?|looked|sounds?|sounded)"
    return (
        re.compile(rf"\b(?:{praise})\s+(?:{targets})\b", re.IGNORECASE),
        re.compile(rf"\b(?:{targets})\s+{copula}\s+{intensifier}(?:{praise})\b", re.IGNORECASE),
        re.compile(
            rf"\b(?:love|loved|enjoy|enjoyed|adore|adored|appreciate|appreciated)\s+"
            rf"(?:the\s+)?(?:{targets})\b",
            re.IGNORECASE,
        ),
    )


ASPECT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Gameplay": _patterns(
        r"gameplay|combat|controls?|movement|mechanics?",
        r"good|great|amazing|excellent|fun|enjoyable|engaging|satisfying|responsive|smooth|"
        r"polished|fantastic|incredible|superb",
    ),
    "Graphics / Visuals": _patterns(
        r"graphics?|visuals?|art(?:\s+style)?|animations?|character\s+design|environment\s+design",
        r"good|great|amazing|excellent|beautiful|stunning|gorgeous|impressive|polished|"
        r"fantastic|incredible|superb",
    ),
    "Sound / Music": _patterns(
        r"soundtrack|music|audio|sound(?:\s+design)?|voice\s+acting|songs?|score",
        r"good|great|amazing|excellent|beautiful|catchy|atmospheric|immersive|memorable|"
        r"fantastic|incredible|superb",
    ),
    "Story / Narrative": _patterns(
        r"story|plot|narrative|writing|characters?|ending",
        r"good|great|amazing|excellent|engaging|immersive|memorable|compelling|well[-\s]written|"
        r"wonderful|fantastic|incredible|superb",
    ),
    "Content / Exploration": _patterns(
        r"content|open\s+world|exploration|quests?|missions?|levels?|replayability|activities",
        r"good|great|amazing|excellent|fun|enjoyable|engaging|rich|rewarding|varied|immersive|"
        r"wonderful|fantastic|incredible|superb",
    ),
}

EXTRA_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Content / Exploration": (
        re.compile(r"\b(?:love|loved|enjoy|enjoyed)\s+explor(?:e|ing)\b", re.IGNORECASE),
        re.compile(r"\bexplor(?:ing|ation)\s+(?:is|was|feels?|felt)\s+(?:fun|rewarding|enjoyable)\b", re.IGNORECASE),
    ),
}


def classify_positive_aspects(text: str) -> list[str]:
    """Return concrete praised aspects without using Steam vote or sentiment labels."""
    matches: list[str] = []
    clauses = [part.strip() for part in CLAUSE_BOUNDARY.split(str(text)) if part.strip()]
    for clause in clauses:
        effective = NEGATED_PRAISE.sub(" ", clause)
        for aspect, patterns in ASPECT_PATTERNS.items():
            candidates = patterns + EXTRA_PATTERNS.get(aspect, ())
            if aspect not in matches and any(pattern.search(effective) for pattern in candidates):
                matches.append(aspect)
    return matches


def add_positive_aspects(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    source = result["review_text"].fillna("").astype(str)
    result["positive_aspects"] = source.map(classify_positive_aspects)
    return result


def summarize_positive_aspects(
    df: pd.DataFrame, representative_count: int = 3
) -> list[dict[str, Any]]:
    total = len(df)
    summaries: list[dict[str, Any]] = []
    for aspect in ASPECT_PATTERNS:
        mask = df["positive_aspects"].map(lambda labels: aspect in labels)
        group = df.loc[mask]
        if group.empty:
            continue
        representatives = group.sort_values("sentiment_score", ascending=False).head(representative_count)
        examples = [
            {"review_id": _native(row.get("review_id")), "text": str(row["review_text"])}
            for _, row in representatives.iterrows()
        ]
        summaries.append({
            "aspect_type": aspect,
            "review_count": int(len(group)),
            "review_ratio": float(len(group) / total),
            "representative_reviews": examples,
        })
    return sorted(summaries, key=lambda item: (-item["review_count"], item["aspect_type"]))


def _native(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value
