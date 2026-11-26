"""LLM-as-judge: grades a triage output's summary and reply against a written rubric.

One call per ticket returns a pass/fail verdict and a one-line reason for each criterion.
The rubric text lives in prompts/judge/<version>.md; the criterion names below must match it.
"""

import json

import anthropic
from pydantic import BaseModel, ConfigDict

from ticket_triage.config import DEFAULT_JUDGE_PROMPT, JUDGE_MODEL
from ticket_triage.llm import Parsed, structured_call
from ticket_triage.prompts import load_prompt
from ticket_triage.schema import TriageFailure, TriageResult
from ticket_triage.triage import wrap_ticket

CRITERIA = ["faithful_summary", "helpful_reply", "safe_reply", "tone_and_language"]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    passed: bool


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    faithful_summary: Verdict
    helpful_reply: Verdict
    safe_reply: Verdict
    tone_and_language: Verdict

    def as_bools(self) -> dict[str, bool]:
        return {c: getattr(self, c).passed for c in CRITERIA}


_VERDICT_SCHEMA = {
    "type": "object",
    # "reason" comes first so the judge explains before it decides.
    "properties": {"reason": {"type": "string"}, "passed": {"type": "boolean"}},
    "required": ["reason", "passed"],
    "additionalProperties": False,
}
JUDGE_WIRE_SCHEMA = {
    "type": "object",
    "properties": {c: _VERDICT_SCHEMA for c in CRITERIA},
    "required": CRITERIA,
    "additionalProperties": False,
}


def judge(
    ticket_text: str,
    output: TriageResult,
    *,
    client: anthropic.Anthropic,
    model: str = JUDGE_MODEL,
    prompt_version: str = DEFAULT_JUDGE_PROMPT,
) -> Parsed[JudgeVerdict] | TriageFailure:
    prompt = load_prompt("judge", prompt_version)
    candidate = {"summary": output.summary, "suggested_reply": output.suggested_reply}
    user = (
        f"{wrap_ticket(ticket_text)}\n\n"
        f"<triage_output>\n{json.dumps(candidate, ensure_ascii=False, indent=2)}\n</triage_output>"
    )
    return structured_call(
        client,
        model=model,
        system=prompt.text,
        user=user,
        wire_schema=JUDGE_WIRE_SCHEMA,
        output_model=JudgeVerdict,
        prompt_id=prompt.id,
        generation_name="judge-output",
        effort=prompt.meta.get("effort", "medium"),
    )
