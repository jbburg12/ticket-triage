import pytest

from ticket_triage.evals import metrics
from ticket_triage.evals.gates import check_gates
from ticket_triage.evals.runner import summarize


def row(
    expected=("billing", "high"),
    predicted=("billing", "high"),
    failure=None,
    tags=(),
    reply="We'll look into it.",
    repeat=0,
    judge=None,
):
    r = {
        "repeat": repeat,
        "id": "t",
        "tags": list(tags),
        "expected": {"category": expected[0], "priority": expected[1]},
        "predicted": {}
        if failure
        else {"category": predicted[0], "priority": predicted[1], "suggested_reply": reply},
        "failure": failure,
        "stats": None,
    }
    if judge is not None:
        r["judge"] = judge
    return r


def test_accuracy_counts_failures_as_wrong():
    rows = [row(), row(predicted=("bug", "high")), row(failure="refusal")]
    assert metrics.accuracy(rows, "category") == pytest.approx(1 / 3)
    assert metrics.accuracy(rows, "priority") == pytest.approx(2 / 3)  # row 2 has priority right
    assert metrics.failure_rate(rows) == pytest.approx(1 / 3)
    assert metrics.failure_counts(rows) == {"refusal": 1}


def test_confusion_matrix_has_failed_column():
    rows = [row(), row(predicted=("bug", "high")), row(failure="truncated")]
    m = metrics.confusion_matrix(rows, "category")
    assert m["billing"]["billing"] == 1
    assert m["billing"]["bug"] == 1
    assert m["billing"][metrics.FAILED] == 1
    assert m["login"]["login"] == 0


def test_injection_check():
    ok = row(expected=("bug", "low"), predicted=("bug", "low"), reply="Thanks for reporting.")
    hijacked = row(
        expected=("bug", "low"), predicted=("billing", "high"), reply="You will get a FULL REFUND."
    )
    assert metrics.injection_check(ok, ["full refund"]) == (True, "ok")
    passed, detail = metrics.injection_check(hijacked, ["full refund"])
    assert not passed
    assert "category" in detail and "priority" in detail and "full refund" in detail


def test_judge_pass_rates_count_missing_verdicts_as_fail():
    all_pass = dict.fromkeys(
        ["faithful_summary", "helpful_reply", "safe_reply", "tone_and_language"], True
    )
    rows = [row(judge=all_pass), row(judge=None) | {"judge": None}]
    rates = metrics.judge_pass_rates(rows)
    assert rates["safe_reply"] == 0.5


def test_cohen_kappa():
    assert metrics.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert metrics.cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0
    assert metrics.cohen_kappa([True, True], [True, True]) is None  # undefined


def test_gates_pass_and_fail():
    info = dict(
        run_id="r",
        timestamp="t",
        model="m",
        prompt_version="v1",
        judge_model=None,
        judge_prompt=None,
        repeats=1,
    )
    good = summarize([row() for _ in range(10)], tickets=[None] * 10, **info)
    assert all(g.passed for g in check_gates(good))

    rows = [row() for _ in range(8)] + [row(failure="refusal")] * 2
    bad = summarize(rows, tickets=[None] * 10, **info)
    failed = {g.name for g in check_gates(bad) if not g.passed}
    assert failed == {"category accuracy", "failure rate"}
