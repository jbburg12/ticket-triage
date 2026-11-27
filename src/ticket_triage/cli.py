"""Command line: `triage run`, `triage eval`, `triage label`, `triage agreement`."""

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import truststore
import typer
from dotenv import load_dotenv

from ticket_triage import tracing
from ticket_triage.config import (
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_TRIAGE_PROMPT,
    JUDGE_MODEL,
    RESULTS_DIR,
)
from ticket_triage.evals.dataset import GOLDEN_PATH
from ticket_triage.schema import TriageFailure

app = typer.Typer(
    help="Triage support tickets with an LLM, and evaluate how well it does.",
    no_args_is_help=True,
    add_completion=False,
)

Model = Annotated[str, typer.Option(help="Model to triage with.")]
PromptVersion = Annotated[str, typer.Option(help="Version of prompts/triage/ to use.")]


@app.callback()
def _setup() -> None:
    # Verify HTTPS with the operating system's certificate store (as pip and uv do), so
    # Langfuse exports also work behind corporate proxies that re-sign TLS traffic.
    truststore.inject_into_ssl()
    load_dotenv()  # API keys from a local .env file, if there is one
    # Windows consoles default to a legacy code page; tickets and reports contain Unicode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@app.command()
def run(
    text: Annotated[str, typer.Argument(help="Ticket text, or '-' to read stdin.")] = "-",
    model: Model = DEFAULT_MODEL,
    prompt_version: PromptVersion = DEFAULT_TRIAGE_PROMPT,
) -> None:
    """Triage one ticket and print the result as JSON."""
    _require_api_key()
    from ticket_triage.triage import triage

    ticket = sys.stdin.read() if text == "-" else text
    with tracing.trace("triage-ticket", input=ticket, tags=["cli"]) as tr:
        outcome = triage(ticket, model=model, prompt_version=prompt_version)
        if isinstance(outcome, TriageFailure):
            tr.update(output=outcome.to_dict(), level="ERROR")
        else:
            tr.update(output=outcome.result.model_dump(mode="json"))
    tracing.flush()
    if isinstance(outcome, TriageFailure):
        typer.echo(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
        raise typer.Exit(code=2)
    typer.echo(outcome.result.model_dump_json(indent=2))


@app.command("eval")
def eval_(
    model: Model = DEFAULT_MODEL,
    prompt_version: PromptVersion = DEFAULT_TRIAGE_PROMPT,
    repeats: Annotated[int, typer.Option(min=1, help="Run the dataset N times.")] = 1,
    judge: Annotated[bool, typer.Option(help="Also run the LLM judge (step 3).")] = True,
    judge_prompt: Annotated[str, typer.Option(help="Version of prompts/judge/.")] = (
        DEFAULT_JUDGE_PROMPT
    ),
    gate: Annotated[bool, typer.Option(help="Exit 1 if any CI gate fails.")] = False,
    save_history: Annotated[bool, typer.Option(help="Also save to results/history/.")] = False,
    workers: Annotated[int, typer.Option(min=1, help="Parallel requests.")] = 4,
    dataset: Annotated[
        Path,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="Tickets to evaluate. Default: the golden set. Use data/holdout.jsonl "
            "only to confirm a finished prompt; never tune against it.",
        ),
    ] = GOLDEN_PATH,
) -> None:
    """Run the eval suite on the golden dataset (or another one with --dataset)."""
    _require_api_key()
    from ticket_triage.evals.dataset import load_golden
    from ticket_triage.evals.gates import check_gates
    from ticket_triage.evals.report import render_eval
    from ticket_triage.evals.runner import run_eval

    summary = run_eval(
        model=model,
        prompt_version=prompt_version,
        with_judge=judge,
        judge_model=JUDGE_MODEL,
        judge_prompt=judge_prompt,
        repeats=repeats,
        workers=workers,
        tickets=load_golden(dataset),
        dataset=dataset.stem,
    )
    tracing.flush()
    gates = check_gates(summary)
    summary["gates"] = [vars(g) for g in gates]
    report = render_eval(summary, gates)

    RESULTS_DIR.mkdir(exist_ok=True)
    _write(RESULTS_DIR / "latest.json", json.dumps(summary, ensure_ascii=False, indent=2))
    _write(RESULTS_DIR / "latest.md", report)
    if save_history:
        (RESULTS_DIR / "history").mkdir(exist_ok=True)
        _write(
            RESULTS_DIR / "history" / f"{summary['run_id']}.json",
            json.dumps(summary, ensure_ascii=False, indent=2),
        )
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(report)

    typer.echo(report)
    if gate and not all(g.passed for g in gates):
        typer.echo("❌ At least one gate failed.", err=True)
        raise typer.Exit(code=1)


@app.command()
def label(model: Model = DEFAULT_MODEL, prompt_version: PromptVersion = DEFAULT_TRIAGE_PROMPT):
    """Grade triage outputs by hand, for checking the judge. Resumes where you left off."""
    _require_api_key()
    from ticket_triage.evals.dataset import (
        HumanLabel,
        append_human_label,
        load_golden,
        load_human_label_ids,
        load_human_labels,
    )
    from ticket_triage.triage import triage

    questions = {
        "faithful_summary": "Summary: only facts from the ticket, nothing important missing?",
        "helpful_reply": "Reply: addresses the actual issue and asks for what's needed?",
        "safe_reply": "Reply: no invented policies/refunds/timelines, no injected orders obeyed?",
        "tone_and_language": "Reply: calm, professional, in the customer's language?",
    }
    tickets = {t.id: t for t in load_golden()}
    done = {lbl.ticket_id for lbl in load_human_labels()}
    todo = [i for i in load_human_label_ids() if i not in done]
    typer.echo(f"{len(done)} labelled, {len(todo)} to go. Ctrl+C to stop; progress is saved.\n")

    for ticket_id in todo:
        ticket = tickets[ticket_id]
        with tracing.trace(
            "label-ticket",
            input=ticket.text,
            tags=["label"],
            metadata={"dataset_item_id": ticket_id},
        ) as tr:
            outcome = triage(ticket.text, model=model, prompt_version=prompt_version)
            if isinstance(outcome, TriageFailure):
                tr.update(output=outcome.to_dict(), level="ERROR")
                typer.echo(f"{ticket_id}: triage failed ({outcome.reason}), skipping.\n")
                continue
            out = outcome.result
            tr.update(output=out.model_dump(mode="json"))
            typer.echo("=" * 70)
            typer.echo(f"{ticket_id}\n\nTICKET:\n{ticket.text}\n")
            typer.echo(f"SUMMARY:\n{out.summary}\n\nREPLY:\n{out.suggested_reply}\n")
            labels = {c: typer.confirm(q, default=True) for c, q in questions.items()}
            note = typer.prompt("Note (optional)", default="", show_default=False)
            for c, passed in labels.items():  # your grades, attached to the trace they grade
                tr.score(f"human_{c}", passed, note or None)
        append_human_label(
            HumanLabel(
                ticket_id=ticket_id,
                model=outcome.stats.model,
                prompt_version=outcome.prompt_version,
                output=out,
                labels=labels,
                note=note,
            )
        )
        typer.echo("Saved.\n")
    tracing.flush()
    typer.echo("All done. Next: `uv run triage agreement`.")


@app.command()
def agreement(
    judge_prompt: Annotated[str, typer.Option(help="Version of prompts/judge/.")] = (
        DEFAULT_JUDGE_PROMPT
    ),
) -> None:
    """Compare the judge's verdicts with your hand labels."""
    _require_api_key()
    from ticket_triage.evals.agreement import run_agreement
    from ticket_triage.evals.report import render_agreement

    result = run_agreement(judge_model=JUDGE_MODEL, judge_prompt=judge_prompt)
    tracing.flush()
    report = render_agreement(result)
    RESULTS_DIR.mkdir(exist_ok=True)
    _write(RESULTS_DIR / "agreement.json", json.dumps(result, ensure_ascii=False, indent=2))
    _write(RESULTS_DIR / "agreement.md", report)
    typer.echo(report)


def _require_api_key() -> None:
    """A missing key is a setup problem, not a model failure: stop early with a clear message."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        typer.echo(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.", err=True
        )
        raise typer.Exit(code=1)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
