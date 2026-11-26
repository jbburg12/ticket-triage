"""The CI gates: the checks that can fail the build.

Every gate here is scored by plain code against the dataset labels. Judge scores are not
gates yet: a judge can only gate a criterion after it agrees with the hand labels
(see SPEC.md section 6, "after judge validation").
"""

from dataclasses import dataclass

# Starting values. Reset after the first baseline run to "baseline minus a small margin".
THRESHOLDS = {
    "category_accuracy": 0.85,  # at least
    "priority_accuracy": 0.70,  # at least
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
    ]
