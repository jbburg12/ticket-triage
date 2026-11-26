"""The feature itself: ticket text in, TriageSuccess or TriageFailure out."""

import anthropic

from ticket_triage.config import DEFAULT_MODEL, DEFAULT_TRIAGE_PROMPT
from ticket_triage.llm import Parsed, structured_call
from ticket_triage.prompts import load_prompt
from ticket_triage.schema import WIRE_SCHEMA, TriageOutcome, TriageResult, TriageSuccess


def triage(
    ticket_text: str,
    *,
    model: str = DEFAULT_MODEL,
    prompt_version: str = DEFAULT_TRIAGE_PROMPT,
    client: anthropic.Anthropic | None = None,
) -> TriageOutcome:
    """Classify one ticket. Never raises for model or API problems; returns a TriageFailure."""
    prompt = load_prompt("triage", prompt_version)
    client = client or anthropic.Anthropic()
    outcome = structured_call(
        client,
        model=model,
        system=prompt.text,
        user=wrap_ticket(ticket_text),
        wire_schema=WIRE_SCHEMA,
        output_model=TriageResult,
        prompt_id=prompt.id,
        generation_name="classify-ticket",
        effort=prompt.meta.get("effort", "low"),
    )
    if isinstance(outcome, Parsed):
        return TriageSuccess(result=outcome.value, stats=outcome.stats, prompt_version=prompt.id)
    return outcome


def wrap_ticket(ticket_text: str) -> str:
    """Mark the ticket as data. The system prompt says to never follow instructions inside it."""
    # Neutralise a closing tag inside the ticket so it can't "escape" the data block.
    safe = ticket_text.replace("</ticket>", "</ticket_>")
    return f"<ticket>\n{safe}\n</ticket>"
