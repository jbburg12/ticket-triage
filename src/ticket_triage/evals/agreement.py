"""How often does the judge agree with you?

Re-runs the judge on the exact outputs you labelled by hand (stored in human_labels.jsonl)
and compares verdicts per criterion: percent agreement, Cohen's kappa, and every
disagreement, so you can decide whether the rubric or your label is wrong.
"""

import anthropic

from ticket_triage import tracing
from ticket_triage.config import DEFAULT_JUDGE_PROMPT, JUDGE_MODEL
from ticket_triage.evals.dataset import load_golden, load_human_labels
from ticket_triage.evals.judge import CRITERIA, judge
from ticket_triage.evals.metrics import cohen_kappa
from ticket_triage.llm import Parsed

# A criterion counts as "validated" (allowed to gate CI) at this agreement or above,
# with no disagreements on injection tickets.
VALIDATION_AGREEMENT = 0.90


def run_agreement(
    *,
    judge_model: str = JUDGE_MODEL,
    judge_prompt: str = DEFAULT_JUDGE_PROMPT,
    client: anthropic.Anthropic | None = None,
) -> dict:
    labels = load_human_labels()
    if not labels:
        raise SystemExit("No hand labels yet. Run `uv run triage label` first.")
    tickets = {t.id: t for t in load_golden()}
    client = client or anthropic.Anthropic()

    pairs: dict[str, list[tuple[bool, bool]]] = {c: [] for c in CRITERIA}
    disagreements, judge_failures = [], []
    for label in labels:
        ticket = tickets[label.ticket_id]
        with tracing.trace(
            "check-agreement",
            input={"ticket": ticket.text, "output": label.output.model_dump(mode="json")},
            tags=["agreement"],
            metadata={"dataset_item_id": ticket.id, "judge_prompt": judge_prompt},
        ) as tr:
            outcome = judge(
                ticket.text,
                label.output,
                client=client,
                model=judge_model,
                prompt_version=judge_prompt,
            )
            if isinstance(outcome, Parsed):
                tr.update(output={"judge": outcome.value.as_bools(), "human": label.labels})
                for c in CRITERIA:
                    verdict = getattr(outcome.value, c)
                    tr.score(f"judge_{c}", verdict.passed, verdict.reason)
                    tr.score(f"agree_{c}", verdict.passed == label.labels[c])
        if not isinstance(outcome, Parsed):
            judge_failures.append(f"{ticket.id}: {outcome.reason}: {outcome.detail}")
            continue
        for c in CRITERIA:
            human, machine = label.labels[c], getattr(outcome.value, c).passed
            pairs[c].append((human, machine))
            if human != machine:
                disagreements.append(
                    {
                        "ticket_id": ticket.id,
                        "criterion": c,
                        "human": human,
                        "judge": machine,
                        "judge_reason": getattr(outcome.value, c).reason,
                        "injection": "injection" in ticket.tags,
                    }
                )

    per_criterion = {}
    for c, ps in pairs.items():
        humans, judges = [h for h, _ in ps], [j for _, j in ps]
        agreement = sum(h == j for h, j in ps) / len(ps) if ps else None
        injection_misses = any(d["criterion"] == c and d["injection"] for d in disagreements)
        per_criterion[c] = {
            "n": len(ps),
            "agreement": agreement,
            "kappa": cohen_kappa(humans, judges),
            "validated": agreement is not None
            and agreement >= VALIDATION_AGREEMENT
            and not injection_misses,
        }
    return {
        "judge_model": judge_model,
        "judge_prompt": judge_prompt,
        "n_labels": len(labels),
        "per_criterion": per_criterion,
        "disagreements": disagreements,
        "judge_failures": judge_failures,
    }
