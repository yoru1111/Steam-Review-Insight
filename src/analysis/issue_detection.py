from collections import Counter, defaultdict
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
    "Story / Narrative": {"story", "plot", "narrative", "writing", "ending"},
    "Story / Dialogue Length": {"dialogue", "dialog", "text", "talking", "conversation", "conversations"},
    "Content / Open World": {"content", "world", "exploration", "activities", "sidequest", "sidequests"},
    "Customization": {"customization", "customisation", "appearance", "outfits", "options"},
    "Developer Support": {"developers", "devs", "support", "updates", "patches", "communication"},
    "Quest / Progression Design": {"quest", "quests", "mission", "missions", "gigs", "progression"},
}

CONTEXT_ONLY_ISSUES = {
    "Story / Narrative",
    "Story / Dialogue Length",
    "Content / Open World",
    "Customization",
    "Developer Support",
    "Quest / Progression Design",
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
    r"(?:bugs?|crash(?:es|ed|ing)?|issues?|problems?|glitches?|black\s+screen|loading|launch)\b"
    r"|\b(?:bugs?|crash(?:es|ed|ing)?|issues?|problems?|glitches?|black\s+screen|loading|launch)\b"
    r"(?:\W+\w+){0,3}\W+\b(?:fixed|resolved|patched|gone)\b",
    re.IGNORECASE,
)
NEGATED_QUALITY = re.compile(
    r"\b(?:is|are|was|were|feels?|seems?|looks?|does|do)n['’]?t\b(?:\W+\w+){0,2}\W+"
    r"(?:bad|poor|weak|rushed|confusing|cluttered|limited|repetitive|disappointing|overpriced|expensive|too\s+long)\b"
    r"|\b(?:is|are|was|were|feels?|seems?|looks?)\s+not\b(?:\W+\w+){0,2}\W+"
    r"(?:bad|poor|weak|rushed|confusing|cluttered|limited|repetitive|disappointing|overpriced|expensive|too\s+long)\b"
    r"|\bnot\s+bad\b",
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
    r"missing|waste|wasted|annoying|clunky|confus(?:ed|ing)|overpriced|expensive|scam|"
    r"not\s+worth|not\s+interesting|uninteresting|sux)\b",
    re.IGNORECASE,
)
PROGRESS_BLOCKED = re.compile(
    r"\b(?:cannot|can't|cant|couldn't|couldnt|unable\s+to|won't|wont)\s+"
    r"(?:finish|complete|continue|progress|advance|start|launch|open|use|pull\s+out)\b"
    r"|\b(?:stuck|softlock(?:ed)?|progression\s+block(?:ed|er)?)\b",
    re.IGNORECASE,
)

# These signals establish that an otherwise-unclassified review is a complaint. They do not
# assign a category by themselves; SECONDARY_PATTERNS still requires explicit issue context.
SECONDARY_COMPLAINT = re.compile(
    r"\b(?:cheaters?|hackers?|unfair|latency|ping\s+spikes?|rubber\s*band(?:ing)?|"
    r"corrupt(?:ed|ing|ion)?\s+(?:save|data)|save\s+(?:file\s+)?corrupt(?:ed|ion)?)\b",
    re.IGNORECASE,
)
NEGATED_SECONDARY = re.compile(
    r"\b(?:no|never|without)\b(?:\W+\w+){0,4}\W+"
    r"(?:cheaters?|hackers?|latency|high\s+ping|ping\s+spikes?|rubber\s*band(?:ing)?|unfair\s+matchmaking)\b"
    r"|\bmatchmaking\s+(?:is|feels?|seems?)\s+not\s+(?:unfair|unbalanced|broken|bad)\b"
    r"|\b(?:cheaters?|hackers?|latency|ping\s+spikes?|rubber\s*band(?:ing)?)\b"
    r"(?:\W+\w+){0,3}\W+\b(?:gone|fixed|resolved)\b",
    re.IGNORECASE,
)

SECONDARY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Gameplay": (
        re.compile(
            r"\b(?:(?:too\s+many|many|constant|full\s+of|plagued\s+by|riddled\s+with)\s+"
            r"(?:cheaters?|hackers?)|(?:cheaters?|hackers?)(?:\W+\w+){0,4}\W+"
            r"(?:ruin|ruins|ruined|destroy|destroys|plague)\w*)\b",
            re.IGNORECASE,
        ),
    ),
    "Game Balance": (
        re.compile(
            r"\b(?:(?:unfair|unbalanced|broken|terrible|awful|bad)\s+matchmaking|"
            r"matchmaking\s+(?:is|feels?|seems?)\s+(?:unfair|unbalanced|broken|terrible|awful|bad))\b",
            re.IGNORECASE,
        ),
    ),
    "Performance / Optimization": (
        re.compile(
            r"\b(?:high\s+ping|ping\s+spikes?|latency\s+(?:issues?|problems?|spikes?)|"
            r"rubber\s*band(?:ing)?)\b",
            re.IGNORECASE,
        ),
    ),
    "Bugs / Crashes": (
        re.compile(
            r"\b(?:corrupt(?:ed|ing|ion)?\s+(?:save|save\s+file|data)|"
            r"(?:save|save\s+file|data)\s+(?:is\s+)?corrupt(?:ed|ing|ion)?)\b",
            re.IGNORECASE,
        ),
    ),
}

STRONG_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Bugs / Crashes": (
        re.compile(r"\b(?:bugs?|buggy|crash(?:es|ed|ing)?|freez(?:e|es|ing)|glitches?|errors?|broken)\b", re.I),
        PROGRESS_BLOCKED,
        re.compile(r"\b(?:(?:cannot|can't|cant|couldn't|couldnt|won't|wont|doesn't|doesnt|fails?\s+to)"
                   r"(?:\W+\w+){0,2}\W+(?:run|launch|start|load|boot)|black\s+screen|"
                   r"(?:stuck|hangs?)\s+(?:on|at|while)\s+"
                   r"(?:the\s+)?(?:loading|startup)|infinite\s+load(?:ing)?(?:\s+screen)?)\b", re.I),
    ),
    "Performance / Optimization": (
        re.compile(r"\b(?:low\s+fps|frame\s+drops?|stutters?|lag(?:ging)?|poorly\s+optimized|"
                   r"bad\s+performance|runs?\s+(?:very\s+)?slow(?:ly)?|slow(?:ly)?\s+even\s+on\s+low\s+settings|"
                   r"(?:hardware|gpu|graphics\s+card|driver)\s+compatibility\s+(?:issue|issues|problem|problems)|"
                   r"unplayable\s+(?:on|with|if\s+you\s+use)\s+(?:(?:a|an)\s+)?(?:old(?:er)?\s+)?"
                   r"(?:hardware|gpus?|graphics\s+cards?))\b", re.I),
    ),
    "Game Balance": (
        re.compile(r"\b(?:unbalanced|overpowered|underpowered|too\s+(?:easy|hard|difficult)|unfair\s+difficulty)\b", re.I),
    ),
    "Gameplay": (
        re.compile(r"\b(?:boring|repetitive|clunky\s+(?:combat|movement|controls?)|"
                   r"bad\s+(?:gameplay|combat|movement|controls?)|"
                   r"(?:bad|poor|awful|shitty|frustrating)\s+level\s+design|"
                   r"(?:enemy\s+)?ai\s+(?:is|feels|seems)\s+(?:bad|broken|dumb|awful)|"
                   r"(?:enemy\s+)?ai\s+(?:still\s+)?has\s+(?:major\s+)?flaws?|"
                   r"(?:bad|poor|slow|uneven)\s+pacing|repetitive\s+(?:missions?|combat|gameplay))\b", re.I),
    ),
    "UI / Usability": (
        re.compile(r"\b(?:(?:bad|confusing|cluttered|clunky|broken|unusable)\s+"
                   r"(?:ui|interface|menus?|inventory|hud|navigation|controls?)|"
                   r"(?:ui|interface|menus?|inventory|hud|navigation|controls?)\s+"
                   r"(?:is|are|feels?|seems?)\s+(?:bad|confusing|cluttered|clunky|broken|unusable)|"
                   r"(?:key\s+)?rebind(?:ing)?\s+(?:is\s+)?(?:broken|buggy|impossible)|"
                   r"(?:key\s+)?rebind(?:ing)?\s+(?:issue|issues|problem|problems)|"
                   r"(?:cannot|can't|unable\s+to)\s+rebind|control\s+(?:issue|issues|problem|problems))\b", re.I),
    ),
    "Monetization": (
        re.compile(r"\b(?:overpriced|too\s+expensive|not\s+worth(?:\s+the\s+(?:money|price))?|"
                   r"poor\s+value|bad\s+value|paywall|microtransactions?|cash\s+grab|"
                   r"price\s+is\s+(?:bad|high|ridiculous)|costs?\s+too\s+much)\b", re.I),
    ),
    "Story / Narrative": (
        re.compile(r"\b(?:(?:bad|poor|weak|rushed|predictable|disappointing|confusing)\s+"
                   r"(?:story|plot|narrative|writing|ending)|(?:story|plot|narrative|writing|ending)\s+"
                   r"(?:is|feels|seems)\s+(?:bad|poor|weak|rushed|predictable|disappointing|confusing)|"
                   r"poorly\s+written|plot\s+holes?|(?:story|narrative)\s+choices?\s+"
                   r"(?:rarely|hardly|do(?:es)?\s+not|don't|dont)\s+matter|"
                   r"contrived\s+(?:story|plot|moments?))\b", re.I),
    ),
    "Story / Dialogue Length": (
        re.compile(r"\b(?:too+\s+much(?:\s+\w+){0,2}\s+(?:text|dialogue|dialog|talking)|"
                   r"(?:dialogues?|dialog|conversations?)\s+"
                   r"(?:is|are|feels?|seems?)\s+(?:way\s+)?(?:too\s+long|endless)|endless\s+(?:dialogue|dialog|talking)|"
                   r"long\s+conversations?|yap\s+fest)\b", re.I),
    ),
    "Content / Open World": (
        re.compile(r"\b(?:(?:limited|shallow|boring)\s+exploration|(?:empty|lifeless|shallow)\s+(?:open\s+)?world|"
                   r"exploration\s+(?:is|feels|seems)\s+(?:limited|shallow|boring)|"
                   r"(?:open\s+)?world\s+(?:is|feels|seems)\s+(?:empty|lifeless|shallow)|"
                   r"shallow\s+map|(?:missing|lacks?)\s+(?:basic\s+)?open[-\s]world\s+features?|"
                   r"(?:cut|missing|not\s+enough|lack\s+of)\s+content|content\s+(?:is|feels|seems)\s+"
                   r"(?:limited|shallow|repetitive)|repetitive\s+(?:side\s+)?activities)\b", re.I),
    ),
    "Customization": (
        re.compile(r"\b(?:(?:limited|poor|disappointing|shallow|missing)\s+(?:character\s+)?customi[sz]ation|"
                   r"(?:character\s+)?customi[sz]ation\s+(?:is|feels|seems)\s+"
                   r"(?:quite\s+|very\s+)?(?:limited|poor|disappointing|shallow)|"
                   r"not\s+enough\s+(?:appearance|customi[sz]ation)\s+options|"
                   r"wish\s+(?:i|we)\s+could\s+customi[sz]e|"
                   r"(?:cannot|can't|unable\s+to)\s+customi[sz]e)\b", re.I),
    ),
    "Developer Support": (
        re.compile(r"\b(?:no\s+(?:developer\s+)?(?:support|communication|fixes|patches)|"
                   r"(?:developers?|devs?)\s+(?:do\s+not|don't|dont|won't|never)\s+(?:fix|patch|respond|communicate)|"
                   r"(?:developers?|devs?|they)\s+(?:do\s+not|don't|dont|never)\s+(?:even\s+)?"
                   r"(?:seem\s+to\s+|bother\s+to\s+)?(?:fix|patch|address)|"
                   r"(?:abandoned|stopped\s+supporting)\s+(?:the\s+)?game|years?\s+without\s+(?:a\s+)?fix)\b", re.I),
    ),
    "Quest / Progression Design": (
        re.compile(r"\b(?:(?:bad|poor|boring|confusing)\s+(?:quest|mission|progression)\s+(?:design|structure|pacing)|"
                   r"(?:quest|mission|progression)\s+(?:design|structure|pacing)\s+(?:is|feels|seems)\s+"
                   r"(?:bad|poor|boring|confusing)|repetitive\s+(?:quests?|missions?|gigs)|too\s+many\s+fetch\s+quests?)\b", re.I),
        re.compile(r"\b(?:wait(?:ing)?|takes?\s+too\s+long)\b(?:\W+\w+){0,5}\W+"
                   r"(?:trigger|start|receive)\b(?:\W+\w+){0,3}\W+(?:quests?|missions?|gigs)\b", re.I),
    ),
}


def _clauses(text: str) -> list[str]:
    return [clause.strip() for clause in CONTRAST_OR_BOUNDARY.split(str(text)) if clause.strip()]


def _effective_clause(clause: str) -> str:
    effective = NEGATED_PROBLEM.sub(" ", clause)
    effective = RESOLVED_PROBLEM.sub(" ", effective)
    effective = NEGATED_QUALITY.sub(" ", effective)
    return NEGATED_SECONDARY.sub(" ", effective)


def _clause_result(clause: str) -> tuple[bool, list[str]]:
    effective = _effective_clause(clause)
    tokens = set(re.findall(r"[a-z]+", effective.lower()))
    has_problem = bool(
        PROBLEM.search(effective) or PROGRESS_BLOCKED.search(effective)
        or SECONDARY_COMPLAINT.search(effective)
    )
    praised = bool(PRAISE.search(effective))
    issues: list[str] = []

    for issue, terms in ISSUE_KEYWORDS.items():
        keyword_match = issue not in CONTEXT_ONLY_ISSUES and bool(tokens & terms)
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


def _primary_classify(text: str) -> list[str]:
    complaint = False
    matches: list[str] = []
    for clause in _clauses(text):
        clause_complaint, clause_issues = _clause_result(clause)
        complaint = complaint or clause_complaint
        for issue in clause_issues:
            if issue not in matches:
                matches.append(issue)
    return matches or (["Other / Unclassified"] if complaint else [])


def classify_other_complaint(text: str) -> list[str]:
    """Refine a first-pass Other result with conservative existing-category patterns."""
    matches: list[str] = []
    for clause in _clauses(text):
        effective = _effective_clause(clause)
        for issue, patterns in SECONDARY_PATTERNS.items():
            if any(pattern.search(effective) for pattern in patterns) and issue not in matches:
                matches.append(issue)
    return matches


def classify_text(text: str) -> list[str]:
    primary = _primary_classify(text)
    if primary != ["Other / Unclassified"]:
        return primary
    secondary = classify_other_complaint(text)
    return secondary or primary


def add_issue_types(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    source = result["review_clean"].fillna("").astype(str)
    result["is_complaint"] = source.map(detect_complaint)
    result["issue_types"] = source.map(classify_text)
    return result


def annotate_cluster_types(clusters: list[dict[str, Any]], reviews: pd.DataFrame | None = None) -> None:
    """Add legacy keyword labels and, when available, review-level cluster profiles.

    Per-issue ratios use complaint reviews as their denominator. A multi-label review
    therefore contributes once to each matching issue, so those ratios need not sum
    to 100 percent.
    """
    for cluster in clusters:
        scores = {issue: len(set(cluster["keywords"]) & terms) for issue, terms in ISSUE_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        cluster["issue_type"] = best if scores[best] else "Other / Unclassified"

        if reviews is None:
            continue

        members = reviews.loc[reviews["cluster_id"] == cluster["cluster_id"]]
        complaint_mask = members["is_complaint"].astype(bool)
        complaint_reviews = members.loc[complaint_mask]
        complaint_count = int(complaint_mask.sum())
        review_count = int(len(members))
        issue_counts: Counter[str] = Counter()
        for issue_types in complaint_reviews["issue_types"]:
            # Count review presence, not label occurrences within a review.
            issue_counts.update(set(issue_types))

        cluster["complaint_review_count"] = complaint_count
        cluster["complaint_ratio"] = complaint_count / review_count if review_count else 0.0
        cluster["issue_review_counts"] = dict(issue_counts)
        cluster["issue_review_ratios"] = {
            issue: count / complaint_count for issue, count in issue_counts.items()
        } if complaint_count else {}

        non_complaint_count = review_count - complaint_count
        if non_complaint_count > complaint_count:
            cluster["label_kind"] = "general"
            cluster["dominant_issue_type"] = None
            continue

        ranked = issue_counts.most_common()
        top_issue, top_count = ranked[0] if ranked else (None, 0)
        second_count = ranked[1][1] if len(ranked) > 1 else 0
        has_strict_issue_majority = top_count * 2 > complaint_count
        has_single_leader = top_count > second_count
        if complaint_count > non_complaint_count and has_strict_issue_majority and has_single_leader:
            cluster["dominant_issue_type"] = top_issue
            cluster["label_kind"] = "other" if top_issue == "Other / Unclassified" else "issue"
        else:
            cluster["label_kind"] = "mixed"
            cluster["dominant_issue_type"] = None


def group_by_issue(df: pd.DataFrame) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for pos, types in enumerate(df["issue_types"]):
        for issue in types:
            groups[issue].append(pos)
    return dict(groups)
