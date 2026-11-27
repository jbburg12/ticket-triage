"""Render eval results as Markdown (for the terminal, results/latest.md and the CI summary)."""

from ticket_triage.evals.gates import Gate
from ticket_triage.evals.metrics import FAILED


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _confusion(matrix: dict[str, dict[str, int]]) -> str:
    columns = list(next(iter(matrix.values())).keys())
    header = ["expected \\ predicted", *columns]
    rows = [[exp, *(counts[c] or "·" for c in columns)] for exp, counts in matrix.items()]
    return _table(header, rows)


def render_eval(summary: dict, gates: list[Gate]) -> str:
    m = summary["metrics"]
    out = [
        f"## Eval: `{summary['model']}`, prompt `{summary['prompt_version']}`",
        f"{summary['n_tickets']} tickets from `{summary.get('dataset', 'golden')}` × "
        f"{summary['repeats']} repeat(s) · "
        f"judge: `{summary['judge_model'] or 'off'}` · run `{summary['run_id']}`",
        "",
        "### Gates (scored by code)",
        _table(
            ["gate", "actual", "required", ""],
            [[g.name, g.actual, g.required, "✅" if g.passed else "❌"] for g in gates],
        ),
        "",
        "### Classification",
        _table(
            ["metric", "value", "range across repeats"],
            [
                [
                    "category accuracy",
                    _pct(m["category_accuracy"]),
                    " – ".join(_pct(x) for x in m["category_accuracy_range"]),
                ],
                [
                    "priority accuracy",
                    _pct(m["priority_accuracy"]),
                    " – ".join(_pct(x) for x in m["priority_accuracy_range"]),
                ],
                ["failure rate", _pct(m["failure_rate"]), ""],
            ],
        ),
    ]
    if summary["failures"]:
        out += ["", "Failures: " + ", ".join(f"{k} ×{v}" for k, v in summary["failures"].items())]
    if bad := summary.get("non_english_summaries"):
        out += ["", f"Summaries not in English: {len(bad)} ({', '.join(bad)})"]
    out += [
        "",
        "#### Category confusion matrix",
        _confusion(summary["confusion"]["category"]),
        "",
        "#### Priority confusion matrix",
        _confusion(summary["confusion"]["priority"]),
        "",
        "#### Accuracy by slice",
        _table(
            ["tag", "n", "category", "priority"],
            [
                [t, v["n"], _pct(v["category"]), _pct(v["priority"])]
                for t, v in summary["by_tag"].items()
            ],
        ),
    ]
    if summary["judge_pass_rates"]:
        out += [
            "",
            "### Judge pass rates (reported, not gating)",
            _table(
                ["criterion", "pass rate"],
                [[c, _pct(r)] for c, r in summary["judge_pass_rates"].items()],
            ),
        ]
    cost = summary["cost_usd"]
    p50 = summary["triage_latency_p50_s"]
    out += [
        "",
        "### Cost and latency",
        f"Triage ${cost['triage']:.4f} · judge ${cost['judge']:.4f} · "
        f"triage per 1k tickets ≈ ${cost['triage_per_1k_tickets']} · "
        f"p50 triage latency {'n/a' if p50 is None else f'{p50:.1f}s'}",
    ]
    wrong = [
        r
        for r in summary["rows"]
        if r["failure"]
        or r["predicted"].get("category") != r["expected"]["category"]
        or r["predicted"].get("priority") != r["expected"]["priority"]
    ]
    if wrong:
        out += [
            "",
            "### Misses",
            _table(
                ["ticket", "expected", "got"],
                [
                    [
                        r["id"],
                        f"{r['expected']['category']}/{r['expected']['priority']}",
                        r["failure"]
                        and f"{FAILED} {r['failure']}"
                        or f"{r['predicted']['category']}/{r['predicted']['priority']}",
                    ]
                    for r in wrong
                ],
            ),
        ]
    return "\n".join(out) + "\n"


def render_agreement(result: dict) -> str:
    rows = [
        [
            c,
            v["n"],
            v["human_fails"],
            _pct(v["agreement"]),
            "n/a" if v["kappa"] is None else f"{v['kappa']:.2f}",
            "✅"
            if v["validated"]
            else ("— (no failures to catch)" if not v["human_fails"] else "—"),
        ]
        for c, v in result["per_criterion"].items()
    ]
    out = [
        f"## Judge vs human: `{result['judge_model']}`, prompt `{result['judge_prompt']}`",
        f"{result['n_labels']} hand-labelled outputs. Small n: treat this as a sanity check.",
        "",
        _table(["criterion", "n", "your fails", "agreement", "Cohen's kappa", "validated"], rows),
    ]
    if result["disagreements"]:
        out += [
            "",
            "### Disagreements",
            _table(
                ["ticket", "criterion", "you", "judge", "judge's reason"],
                [
                    [
                        d["ticket_id"],
                        d["criterion"],
                        "pass" if d["human"] else "fail",
                        "pass" if d["judge"] else "fail",
                        d["judge_reason"],
                    ]
                    for d in result["disagreements"]
                ],
            ),
        ]
    if result["judge_failures"]:
        out += ["", "Judge failures: " + "; ".join(result["judge_failures"])]
    return "\n".join(out) + "\n"
