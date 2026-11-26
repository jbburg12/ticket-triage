"""The shape of a triage result, and the ways producing one can fail.

Two schemas on purpose:
- WIRE_SCHEMA is the plain JSON schema sent to the API (structured outputs). It constrains
  the response's shape: the fields and the enum values.
- TriageResult is the Pydantic model every response is validated against. It adds rules a
  JSON schema can't express well, such as "the summary is one sentence".
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class Category(StrEnum):
    BILLING = "billing"
    LOGIN = "login"
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


MAX_SUMMARY_CHARS = 200
MAX_REPLY_CHARS = 1200

# One sentence = no sentence-ending punctuation followed by more text.
# Covers Latin (. ! ?) and CJK (。！？) punctuation. Deliberately simple.
_SENTENCE_BREAK = re.compile(r"[.!?。！？]\s+\S|[。！？]\S")


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    priority: Priority
    summary: str
    suggested_reply: str

    @field_validator("summary")
    @classmethod
    def _one_short_sentence(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary is empty")
        if len(value) > MAX_SUMMARY_CHARS:
            raise ValueError(f"summary is longer than {MAX_SUMMARY_CHARS} characters")
        if _SENTENCE_BREAK.search(value):
            raise ValueError("summary is more than one sentence")
        return value

    @field_validator("suggested_reply")
    @classmethod
    def _reply_length(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("suggested_reply is empty")
        if len(value) > MAX_REPLY_CHARS:
            raise ValueError(f"suggested_reply is longer than {MAX_REPLY_CHARS} characters")
        return value


WIRE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": [c.value for c in Category]},
        "priority": {"type": "string", "enum": [p.value for p in Priority]},
        "summary": {"type": "string"},
        "suggested_reply": {"type": "string"},
    },
    "required": ["category", "priority", "summary", "suggested_reply"],
    "additionalProperties": False,
}


FailureReason = Literal["api_error", "refusal", "truncated", "invalid_json", "schema_violation"]


@dataclass
class CallStats:
    """What one API call cost us. Filled in for successes and (when available) failures."""

    model: str
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class TriageFailure:
    """A request that didn't produce a valid result. Returned, never raised."""

    reason: FailureReason
    detail: str
    raw: str | None = None
    stats: CallStats | None = None

    def to_dict(self) -> dict:
        return {"error": self.reason, "detail": self.detail, "raw": self.raw}


@dataclass
class TriageSuccess:
    result: TriageResult
    stats: CallStats
    prompt_version: str = field(default="")


TriageOutcome = TriageSuccess | TriageFailure
