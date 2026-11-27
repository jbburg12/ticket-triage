"""The CI gates: the checks that can fail the build.

Every gate here is scored by plain code against the dataset labels. Judge scores are not
gates yet: a judge can only gate a criterion after it agrees with the hand labels
(see SPEC.md section 6, "after judge validation").
"""

from dataclasses import dataclass

# Set from triage/v3 on the 30-ticket golden set: its worst normal run, minus a margin for
# run-to-run noise (about one ticket). v3 scored 29-30/30 on category and 30/30 on priority
# over 4 runs, so a gate trips only on a real regression, not on a single unlucky ticket:
#   category >= 0.90 -> fails at 4+ misses     priority >= 0.87 -> fails at 5+ misses
#   failure rate <= 0.05 -> fails at 2+ failed triages
# Re-derive these whenever the default prompt, model or golden set changes.
THRESHOLDS = {
    "category_accuracy": 0.90,  # at least
    "priority_accuracy": 0.87,  # at least
    "failure_rate": 0.05,  # at most
}


@dataclass
class Gate:
    name: str
    passed: bool
    actual: str
    required: str


def check_gates(summary: dict) -> list[Gate]:
    m = summary["metrics"]
    inj = summary["injection"]
    non_english = summary.get("non_english_summaries", [])
    return [
        Gate(
            "category accuracy",
            m["category_accuracy"] >= THRESHOLDS["category_accuracy"],
            f"{m['category_accuracy']:.2f}",
            f">= {THRESHOLDS['category_accuracy']:.2f}",
        ),
        Gate(
            "priority accuracy",
            m["priority_accuracy"] >= THRESHOLDS["priority_accuracy"],
            f"{m['priority_accuracy']:.2f}",
            f">= {THRESHOLDS['priority_accuracy']:.2f}",
        ),
        Gate(
            "failure rate",
            m["failure_rate"] <= THRESHOLDS["failure_rate"],
            f"{m['failure_rate']:.2f}",
            f"<= {THRESHOLDS['failure_rate']:.2f}",
        ),
        Gate(
            "injection check",
            inj["passed"] == inj["total"],
            f"{inj['passed']}/{inj['total']}",
            "all pass",
        ),
        # Summaries are for the internal team and must be English. triage/v2 broke this on
        # every non-English ticket while accuracy stayed high, so it gets its own gate.
        Gate(
            "summaries in English",
            not non_english,
            f"{len(non_english)} not English" if non_english else "all",
            "all",
        ),
    ]
