"""Run the eval: triage every golden ticket, score it with code, optionally judge it.

Step 1 (generate): the model under test triages each ticket.
Step 2 (code scoring): accuracy, confusion matrices, failures, injection checks.
Step 3 (judge scoring): the judge grades summaries and replies. Reported only, never gating.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import anthropic

from ticket_triage import tracing
from ticket_triage.config import DEFAULT_JUDGE_PROMPT, DEFAULT_TRIAGE_PROMPT, JUDGE_MODEL
from ticket_triage.evals import metrics
from ticket_triage.evals.dataset import GoldenTicket, load_golden
from ticket_triage.evals.judge import judge
from ticket_triage.llm import Parsed
from ticket_triage.schema import TriageFailure, TriageResult
from ticket_triage.triage import triage


def run_eval(
    *,
    model: str,
    prompt_version: str = DEFAULT_TRIAGE_PROMPT,
    with_judge: bool = True,
    judge_model: str = JUDGE_MODEL,
    judge_prompt: str = DEFAULT_JUDGE_PROMPT,
    repeats: int = 1,
    workers: int = 4,
    tickets: list[GoldenTicket] | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict:
    tickets = tickets if tickets is not None else load_golden()
    client = client or anthropic.Anthropic()
    started = datetime.now(UTC)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{model}-{prompt_version}"

    def evaluate(job: tuple[int, GoldenTicket]) -> dict:
        repeat, ticket = job
        # One trace per ticket: the triage call and the judge call nest under it, and the
        # code checks and judge verdicts are attached as scores. The whole run shares one
        # session, so Langfuse's Sessions view shows every trace of this run together.
        with tracing.trace(
            "evaluate-ticket",
            input={"ticket": ticket.text, "expected": _expected(ticket)},
            tags=["eval"],
            session_id=run_id,
            metadata={
                "run_id": run_id,
                "dataset_item_id": ticket.id,
                "repeat": repeat,
                "slices": ",".join(ticket.tags),
            },
        ) as tr:
            row = _triage_row(ticket, repeat, model, prompt_version, client)
            if with_judge:
                _add_judgement(row, ticket, judge_model, judge_prompt, client)
            _record(tr, row)
        return row

    jobs = [(r, t) for r in range(repeats) for t in tickets]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(evaluate, jobs))

    return summarize(
        rows,
        tickets,
        run_id=run_id,
        timestamp=started.isoformat(timespec="seconds"),
        model=model,
        prompt_version=prompt_version,
        judge_model=judge_model if with_judge else None,
        judge_prompt=judge_prompt if with_judge else None,
        repeats=repeats,
    )


def _expected(ticket: GoldenTicket) -> dict:
    return {
        "category": ticket.expected_category.value,
        "priority": ticket.expected_priority.value,
    }


def _record(tr: tracing.Trace, row: dict) -> None:
    """Trace output and scores, so a bad row in the report is one filter away in Langfuse."""
    tr.update(output=row["predicted"] or {"failure": row["failure"]})
    for field in ("category", "priority"):
        got = row["predicted"].get(field)
        tr.score(
            f"{field}_correct",
            got == row["expected"][field],
            comment=f"expected {row['expected'][field]}, got {got or row['failure']}",
        )
    if "injection" in row:
        tr.score("injection_check", row["injection"]["passed"], row["injection"]["detail"])
    for criterion, passed in (row.get("judge") or {}).items():
        tr.score(f"judge_{criterion}", passed, row["judge_reasons"][criterion])


def _triage_row(ticket, repeat, model, prompt_version, client) -> dict:
    outcome = triage(ticket.text, model=model, prompt_version=prompt_version, client=client)
    row = {
        "repeat": repeat,
        "id": ticket.id,
        "tags": ticket.tags,
        "expected": _expected(ticket),
        "predicted": {},
        "failure": None,
        "stats": None,
    }
    if isinstance(outcome, TriageFailure):
        row["failure"] = outcome.reason
        row["failure_detail"] = outcome.detail
    else:
        row["predicted"] = outcome.result.model_dump(mode="json")
    if outcome.stats is not None:
        row["stats"] = vars(outcome.stats)
    if "injection" in ticket.tags:
        passed, detail = metrics.injection_check(row, ticket.forbidden_phrases)
        row["injection"] = {"passed": passed, "detail": detail}
    return row


def _add_judgement(row, ticket, judge_model, judge_prompt, client) -> None:
    row["judge"] = None  # stays None when triage or the judge call failed: counts as fail
    if row["failure"]:
        return
    outcome = judge(
        ticket.text,
        TriageResult.model_validate(row["predicted"]),
        client=client,
        model=judge_model,
        prompt_version=judge_prompt,
    )
    if isinstance(outcome, Parsed):
        row["judge"] = outcome.value.as_bools()
        row["judge_reasons"] = {c: v["reason"] for c, v in outcome.value.model_dump().items()}
        row["judge_stats"] = vars(outcome.stats)
    else:
        row["judge_failure"] = f"{outcome.reason}: {outcome.detail}"
        if outcome.stats is not None:
            row["judge_stats"] = vars(outcome.stats)


def summarize(rows: list[dict], tickets: list[GoldenTicket], **info) -> dict:
    repeats = info["repeats"]
    per_repeat = [[r for r in rows if r["repeat"] == i] for i in range(repeats)]
    cat_runs = [metrics.accuracy(rs, "category") for rs in per_repeat]
    pri_runs = [metrics.accuracy(rs, "priority") for rs in per_repeat]

    def total_cost(key: str) -> float:
        return sum((r.get(key) or {}).get("cost_usd") or 0.0 for r in rows)

    injection_rows = [r for r in rows if "injection" in r]
    triage_cost = total_cost("stats")
    return {
        **info,
        "n_tickets": len(tickets),
        "metrics": {
            # Pooled over all repeats (= the mean), with the per-repeat range alongside.
            "category_accuracy": metrics.accuracy(rows, "category"),
            "category_accuracy_range": [min(cat_runs), max(cat_runs)],
            "priority_accuracy": metrics.accuracy(rows, "priority"),
            "priority_accuracy_range": [min(pri_runs), max(pri_runs)],
            "failure_rate": metrics.failure_rate(rows),
        },
        "failures": metrics.failure_counts(rows),
        "confusion": {
            "category": metrics.confusion_matrix(rows, "category"),
            "priority": metrics.confusion_matrix(rows, "priority"),
        },
        "by_tag": metrics.accuracy_by_tag(rows),
        "injection": {
            "passed": sum(1 for r in injection_rows if r["injection"]["passed"]),
            "total": len(injection_rows),
        },
        "judge_pass_rates": metrics.judge_pass_rates(rows),
        "cost_usd": {
            "triage": round(triage_cost, 4),
            "judge": round(total_cost("judge_stats"), 4),
            "triage_per_1k_tickets": round(1000 * triage_cost / len(rows), 2) if rows else None,
        },
        "triage_latency_p50_s": metrics.p50([r["stats"]["latency_s"] for r in rows if r["stats"]]),
        "rows": rows,
    }
