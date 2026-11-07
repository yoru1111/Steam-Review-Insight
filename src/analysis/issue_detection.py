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

CONTRAST_OR_BOUNDARY = re.compile(
    r"(?:[.!?;\n]+|\b(?:but|however|although|though|yet|and)\b)", re.IGNORECASE
)
NEGATED_PROBLEM = re.compile(
    r"\b(?:no|never|without|(?:have|has|had|do|does|did|is|are|was|were)n['’]?t)\b"
    r"(?:\W+\w+){0,4}\W+"
    r"(?:bugs?|crash(?:es|ed|ing)?|freez(?:e|es|ing)|glitches?|errors?|issues?|problems?|"
    r"lag(?:ging)?|stutters?|low\s+fps|broken)\b",
    re.IGNORECASE,
)
RESOLVED_PROBLEM = re.compile(
    r"\b(?:fixed|resolved|patched|no longer)\b(?:\W+\w+){0,3}\W+"
    r"(?:bugs?|crash(?:es|ed|ing)?|issues?|problems?|glitches?)\b"
    r"|\b(?:bugs?|crash(?:es|ed|ing)?|issues?|problems?|glitches?)\b"
    r"(?:\W+\w+){0,3}\W+\b(?:fixed|resolved|patched|gone)\b",
    re.IGNORECASE,
)
PRAISE = re.compile(
    r"\b(?:love|loved|like|liked|great|good|amazing|awesome|excellent|best|fun|smooth|"
    r"beautiful|fantastic|perfect|well|enjoy|enjoyed|enjoyable|solid|nice)\b",
    re.IGNORECASE,
)
PROBLEM = re.compile(
    r"\b(?:bad|awful|terrible|worst|hate|hated|frustrat(?:ed|ing)|struggl(?:e|es|ed|ing)|"
    r"issues?|problems?|cannot|can't|couldn't|unable|fails?|failed|failing|broken|buggy|"
    r"crash(?:es|ed|ing)?|freez(?:e|es|ing)|glitches?|errors?|lag(?:ging)?|stutters?|"
    r"boring|repetitive|disappoint(?:ed|ing)|limited|flaws?|sucks?|unplayable|unfinished|"
    r"missing|waste|wasted|annoying|clunky|confus(?:ed|ing)|overpriced|expensive|scam|not\s+worth)\b",
    re.IGNORECASE,
)
PROGRESS_BLOCKED = re.compile(
    r"\b(?:cannot|can't|couldn't|unable\s+to|won't)\s+"
    r"(?:finish|complete|continue|progress|advance|start|launch|open|use|pull\s+out)\b"
    r"|\b(?:stuck|softlock(?:ed)?|progression\s+block(?:ed|er)?)\b",
    re.IGNORECASE,
)

STRONG_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Bugs / Crashes": (
        re.compile(r"\b(?:bugs?|buggy|crash(?:es|ed|ing)?|freez(?:e|es|ing)|glitches?|errors?|broken)\b", re.I),
        PROGRESS_BLOCKED,
    ),
    "Performance / Optimization": (
        re.compile(r"\b(?:low\s+fps|frame\s+drops?|stutters?|lag(?:ging)?|poorly\s+optimized|"
                   r"bad\s+performance|runs?\s+(?:very\s+)?slow(?:ly)?|slow(?:ly)?\s+even\s+on\s+low\s+settings)\b", re.I),
    ),
    "Game Balance": (
        re.compile(r"\b(?:unbalanced|overpowered|underpowered|too\s+(?:easy|hard|difficult)|unfair\s+difficulty)\b", re.I),
    ),
    "Gameplay": (
        re.compile(r"\b(?:boring|repetitive|clunky\s+(?:combat|movement|controls?)|"
                   r"bad\s+(?:gameplay|combat|movement|controls?))\b", re.I),
    ),
    "UI / Usability": (
        re.compile(r"\b(?:bad|confusing|clunky|broken|unusable)\s+(?:ui|interface|menus?|inventory|navigation)\b", re.I),
    ),
    "Monetization": (
        re.compile(r"\b(?:overpriced|too\s+expensive|not\s+worth|paywall|microtransactions?|cash\s+grab|price\s+is\s+(?:bad|high))\b", re.I),
    ),
}


def _clauses(text: str) -> list[str]:
    return [clause.strip() for clause in CONTRAST_OR_BOUNDARY.split(str(text)) if clause.strip()]


def _clause_result(clause: str) -> tuple[bool, list[str]]:
    effective = NEGATED_PROBLEM.sub(" ", clause)
    effective = RESOLVED_PROBLEM.sub(" ", effective)
    tokens = set(re.findall(r"[a-z]+", effective.lower()))
    has_problem = bool(PROBLEM.search(effective) or PROGRESS_BLOCKED.search(effective))
    praised = bool(PRAISE.search(effective))
    issues: list[str] = []

    for issue, terms in ISSUE_KEYWORDS.items():
        keyword_match = bool(tokens & terms)
        strong_match = any(pattern.search(effective) for pattern in STRONG_PATTERNS[issue])
        if issue == "Bugs / Crashes" and PROGRESS_BLOCKED.search(effective):
            strong_match = True
        if not keyword_match and not strong_match:
            continue
        if strong_match:
            issues.append(issue)
        elif has_problem and not (praised and not PROBLEM.search(effective)):
            issues.append(issue)

    complaint = bool(issues or has_problem)
    return complaint, issues


def detect_complaint(text: str) -> bool:
    """Return whether the text asserts a current game problem, independent of Steam vote."""
    return any(_clause_result(clause)[0] for clause in _clauses(text))


def classify_text(text: str) -> list[str]:
    complaint = False
    matches: list[str] = []
    for clause in _clauses(text):
        clause_complaint, clause_issues = _clause_result(clause)
        complaint = complaint or clause_complaint
        for issue in clause_issues:
            if issue not in matches:
                matches.append(issue)
    return matches or (["Other / Unclassified"] if complaint else [])


def add_issue_types(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    source = result["review_clean"].fillna("").astype(str)
    result["is_complaint"] = source.map(detect_complaint)
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
