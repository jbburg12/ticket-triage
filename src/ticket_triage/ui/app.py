"""A local web UI: a playground for triaging one ticket, and a browser for eval results.

The API is a thin layer over the library. It calls `triage()` exactly as the CLI does and
reads the eval results the CLI already writes to results/. It never changes them.
"""

import json
import os
from pathlib import Path
from typing import Annotated

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ticket_triage import tracing
from ticket_triage.config import (
    DATA_DIR,
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_TRIAGE_PROMPT,
    PRICES_PER_MTOK,
    PROMPTS_DIR,
    RESULTS_DIR,
)
from ticket_triage.evals.dataset import load_golden
from ticket_triage.evals.judge import judge
from ticket_triage.schema import TriageFailure, TriageResult
from ticket_triage.triage import triage

STATIC_DIR = Path(__file__).parent / "static"
MAX_TICKET_CHARS = 10_000


class TriageRequest(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=MAX_TICKET_CHARS)]
    model: str = DEFAULT_MODEL
    prompt_version: str = DEFAULT_TRIAGE_PROMPT


class JudgeRequest(BaseModel):
    """The ticket and the triage output to grade, as the playground received it."""

    text: Annotated[str, Field(min_length=1, max_length=MAX_TICKET_CHARS)]
    output: TriageResult


def create_app(
    *,
    client: anthropic.Anthropic | None = None,
    results_dir: Path = RESULTS_DIR,
    data_dir: Path = DATA_DIR,
    prompts_dir: Path = PROMPTS_DIR,
) -> FastAPI:
    """Build the app. Tests pass a fake client and temporary folders."""
    app = FastAPI(title="ticket-triage", docs_url="/api/docs", redoc_url=None)
    app.state.client = client

    def prompt_versions() -> list[str]:
        files = (prompts_dir / "triage").glob("*.md")
        return sorted((p.stem for p in files), key=lambda v: int(v.lstrip("v") or 0))

    def get_client(request: Request) -> anthropic.Anthropic:
        if request.app.state.client is None:
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise HTTPException(
                    503, "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
                )
            request.app.state.client = anthropic.Anthropic()
        return request.app.state.client

    @app.get("/api/options")
    def options() -> dict:
        return {
            "models": list(PRICES_PER_MTOK),
            "default_model": DEFAULT_MODEL,
            "prompt_versions": prompt_versions(),
            "default_prompt_version": DEFAULT_TRIAGE_PROMPT,
            "max_ticket_chars": MAX_TICKET_CHARS,
        }

    @app.get("/api/examples")
    def examples() -> list[dict]:
        """Golden tickets, to try in the playground with their expected labels alongside."""
        return [
            {
                "id": t.id,
                "text": t.text,
                "tags": t.tags,
                "expected": {"category": t.expected_category, "priority": t.expected_priority},
            }
            for t in load_golden(data_dir / "golden.jsonl")
        ]

    # A plain `def` endpoint: FastAPI runs it in a worker thread, so a slow API call
    # doesn't block other requests.
    @app.post("/api/triage")
    def run_triage(body: TriageRequest, request: Request) -> dict:
        if body.model not in PRICES_PER_MTOK:
            raise HTTPException(422, f"Unknown model {body.model!r}.")
        if body.prompt_version not in prompt_versions():
            raise HTTPException(422, f"Unknown prompt version {body.prompt_version!r}.")
        client = get_client(request)

        with tracing.trace("triage-ticket", input=body.text, tags=["ui"]) as tr:
            outcome = triage(
                body.text, model=body.model, prompt_version=body.prompt_version, client=client
            )
            if isinstance(outcome, TriageFailure):
                tr.update(output=outcome.to_dict(), level="ERROR")
            else:
                tr.update(output=outcome.result.model_dump(mode="json"))
        tracing.flush()

        stats = vars(outcome.stats) if outcome.stats is not None else None
        if isinstance(outcome, TriageFailure):
            # A failed triage is a normal, counted outcome, not an HTTP error.
            return {"ok": False, "failure": outcome.to_dict(), "stats": stats}
        return {
            "ok": True,
            "result": outcome.result.model_dump(mode="json"),
            "prompt_version": outcome.prompt_version,
            "stats": stats,
        }

    # Only on request: the judge measures, it never changes the output, and a judge call
    # costs about 20x a Haiku triage call. In production it would grade a sample after the fact.
    @app.post("/api/judge")
    def run_judge(body: JudgeRequest, request: Request) -> dict:
        client = get_client(request)
        with tracing.trace(
            "judge-ticket",
            input={"ticket": body.text, "output": body.output.model_dump(mode="json")},
            tags=["ui"],
        ) as tr:
            outcome = judge(body.text, body.output, client=client)
            if isinstance(outcome, TriageFailure):
                tr.update(output=outcome.to_dict(), level="ERROR")
            else:
                tr.update(output=outcome.value.model_dump())
                for criterion, verdict in outcome.value.model_dump().items():
                    tr.score(f"judge_{criterion}", verdict["passed"], verdict["reason"])
        tracing.flush()

        stats = vars(outcome.stats) if outcome.stats is not None else None
        if isinstance(outcome, TriageFailure):
            return {"ok": False, "failure": outcome.to_dict(), "stats": stats}
        return {
            "ok": True,
            "verdicts": outcome.value.model_dump(),
            "judge_prompt": f"judge/{DEFAULT_JUDGE_PROMPT}",
            "stats": stats,
        }

    def load_runs() -> dict[str, dict]:
        """Every saved eval run, by run_id. latest.json is included if it isn't in history."""
        runs: dict[str, dict] = {}
        paths = [*sorted((results_dir / "history").glob("*.json")), results_dir / "latest.json"]
        for path in paths:
            if not path.is_file():
                continue
            summary = json.loads(path.read_text(encoding="utf-8"))
            if "run_id" in summary:
                runs.setdefault(summary["run_id"], summary)
        return runs

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        listing = [
            {
                "run_id": s["run_id"],
                "timestamp": s.get("timestamp"),
                "model": s.get("model"),
                "prompt_version": s.get("prompt_version"),
                "dataset": s.get("dataset") or "golden",  # older runs predate the field
                "repeats": s.get("repeats", 1),
                "n_tickets": s.get("n_tickets"),
                "judged": bool(s.get("judge_model")),
                "metrics": s.get("metrics", {}),
                "gates_passed": all(g["passed"] for g in s.get("gates", [])),
            }
            for s in load_runs().values()
        ]
        return sorted(listing, key=lambda r: r["timestamp"] or "", reverse=True)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        # Looked up among the runs on disk, never used as a path, so it can't escape results/.
        summary = load_runs().get(run_id)
        if summary is None:
            raise HTTPException(404, f"No eval run {run_id!r}.")
        summary = {**summary, "dataset": summary.get("dataset") or "golden"}

        # Rows store ids, not ticket text. Join the text and label notes back in.
        dataset_path = data_dir / f"{summary['dataset']}.jsonl"
        tickets = {t.id: t for t in load_golden(dataset_path)} if dataset_path.is_file() else {}
        for row in summary.get("rows", []):
            if ticket := tickets.get(row["id"]):
                row["text"] = ticket.text
                row["notes"] = ticket.notes
        return summary

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
