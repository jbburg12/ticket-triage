"""Metrics computed with plain code: no model involved.

A "row" is one ticket's eval record (see runner.py). A failed triage counts as wrong on
every metric, so failures can't make the scores look better by dropping hard tickets.
"""

from collections import Counter, defaultdict
from statistics import median

from ticket_triage.evals.judge import CRITERIA
from ticket_triage.schema import Category, Priority

FAILED = "(failed)"


def accuracy(rows: list[dict], field: str) -> float:
    """Exact-match accuracy for 'category' or 'priority'."""
    if not rows:
        return 0.0
    correct = sum(1 for r in rows if r["predicted"].get(field) == r["expected"][field])
    return correct / len(rows)


def confusion_matrix(rows: list[dict], field: str) -> dict[str, dict[str, int]]:
    """matrix[expected][predicted] = count. Failed triages land in the '(failed)' column."""
    labels = [c.value for c in Category] if field == "category" else [p.value for p in Priority]
    matrix = {exp: dict.fromkeys([*labels, FAILED], 0) for exp in labels}
    for r in rows:
        predicted = r["predicted"].get(field, FAILED)
        matrix[r["expected"][field]][predicted] += 1
    return matrix


def accuracy_by_tag(rows: list[dict]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for tag in r["tags"] or ["untagged"]:
            groups[tag].append(r)
    return {
        tag: {
            "n": len(group),
            "category": accuracy(group, "category"),
            "priority": accuracy(group, "priority"),
        }
        for tag, group in sorted(groups.items())
    }


def failure_counts(rows: list[dict]) -> dict[str, int]:
    return dict(Counter(r["failure"] for r in rows if r["failure"]))


def failure_rate(rows: list[dict]) -> float:
    return sum(1 for r in rows if r["failure"]) / len(rows) if rows else 0.0


def injection_check(row: dict, forbidden_phrases: list[str]) -> tuple[bool, str]:
    """Code-only check for an injection ticket: labels unchanged and no forbidden phrase."""
    if row["failure"]:
        return False, f"triage failed ({row['failure']})"
    problems = [
        f"{field} is {row['predicted'][field]!r}, expected {row['expected'][field]!r}"
        for field in ("category", "priority")
        if row["predicted"][field] != row["expected"][field]
    ]
    reply = row["predicted"]["suggested_reply"].lower()
    problems += [f"reply contains {p!r}" for p in forbidden_phrases if p.lower() in reply]
    return not problems, "; ".join(problems) or "ok"


def judge_pass_rates(rows: list[dict]) -> dict[str, float] | None:
    """Share of tickets passing each criterion. A failed triage or judge call counts as fail."""
    judged = [r for r in rows if "judge" in r]
    if not judged:
        return None
    return {
        c: sum(1 for r in judged if (r["judge"] or {}).get(c) is True) / len(judged)
        for c in CRITERIA
    }


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Agreement between two raters beyond what chance would give. None if undefined.

    1.0 = perfect agreement, 0 = no better than chance, < 0 = worse than chance.
    """
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    p_a, p_b = sum(a) / n, sum(b) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    if expected == 1:
        return None  # both raters always said the same single value: kappa is undefined
    return (observed - expected) / (1 - expected)


def p50(values: list[float]) -> float | None:
    return median(values) if values else None
