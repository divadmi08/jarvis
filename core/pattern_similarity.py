from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SynonymRegistry:
    aliases: dict[str, str] = field(
        default_factory=lambda: {
            "cursor": "vscode",
            "cursor.exe": "vscode",
            "code.exe": "vscode",
            "code": "vscode",
            "visual studio code": "vscode",
            "brave": "chrome",
            "brave.exe": "chrome",
            "arc": "chrome",
            "arc.exe": "chrome",
            "msedge": "chrome",
            "msedge.exe": "chrome",
            "windows terminal": "terminal",
            "windowsterminal.exe": "terminal",
            "windowsterminal": "terminal",
            "powershell.exe": "terminal",
            "powershell": "terminal",
            "cmd.exe": "terminal",
            "cmd": "terminal",
        }
    )

    def canonicalize(self, app: str) -> str:
        normalized = app.lower().strip()
        normalized = normalized.removesuffix(".exe")
        return self.aliases.get(normalized, normalized)

    def normalize_sequence(self, apps: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        return tuple(self.canonicalize(app) for app in apps)


def jaccard_similarity(left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def levenshtein_distance(left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, left_value in enumerate(left, start=1):
        curr = [i]
        for j, right_value in enumerate(right, start=1):
            cost = 0 if left_value == right_value else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def weighted_edit_distance(
    left: list[str] | tuple[str, ...],
    right: list[str] | tuple[str, ...],
    insertion_cost: float = 1.0,
    deletion_cost: float = 1.0,
    substitution_cost: float = 0.75,
) -> float:
    if not left:
        return len(right) * insertion_cost
    if not right:
        return len(left) * deletion_cost
    prev = [index * insertion_cost for index in range(len(right) + 1)]
    for i, left_value in enumerate(left, start=1):
        curr = [i * deletion_cost]
        for j, right_value in enumerate(right, start=1):
            replace = prev[j - 1] + (0.0 if left_value == right_value else substitution_cost)
            insert = curr[-1] + insertion_cost
            delete = prev[j] + deletion_cost
            curr.append(min(replace, insert, delete))
        prev = curr
    return prev[-1]


class PatternSimilarity:
    def __init__(self, synonyms: SynonymRegistry | None = None):
        self.synonyms = synonyms or SynonymRegistry()

    def normalize(self, apps: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        return self.synonyms.normalize_sequence(apps)

    def sequence_similarity(self, left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> float:
        left_norm = self.normalize(left)
        right_norm = self.normalize(right)
        if not left_norm and not right_norm:
            return 1.0
        jaccard = jaccard_similarity(left_norm, right_norm)
        edit_distance = weighted_edit_distance(left_norm, right_norm)
        max_len = max(len(left_norm), len(right_norm), 1)
        order_score = max(0.0, 1.0 - (edit_distance / max_len))
        exact_distance = levenshtein_distance(left_norm, right_norm)
        exact_score = max(0.0, 1.0 - (exact_distance / max_len))
        return (0.35 * jaccard) + (0.4 * order_score) + (0.25 * exact_score)
