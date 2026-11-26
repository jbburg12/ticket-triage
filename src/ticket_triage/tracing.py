"""Langfuse tracing, optional by design.

With LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY set, every unit of work becomes one Langfuse
trace: a root span (`triage-ticket`, `evaluate-ticket`, ...) whose input and output are the
human-readable ticket and result, with one `generation` per model call nested under it, and
scores (correctness, judge verdicts, hand labels) attached to the trace. Without the keys,
everything here is a no-op, so the CLI, tests and fork PRs work without a Langfuse account.

Names are stable and verb-first; anything that varies (run id, ticket id, model) goes in
attributes or metadata, never in a name.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from typing import Any


def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


# --- masking: real tickets contain personal data. Mask it before it leaves the process. ---

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")  # 13-19 digits, the length of card numbers


def mask_pii(*, data: Any, **_: Any) -> Any:
    """Langfuse `mask` hook: replaces email addresses and card-like numbers in traced data."""
    if isinstance(data, str):
        return _CARD.sub("[CARD]", _EMAIL.sub("[EMAIL]", data))
    if isinstance(data, dict):
        return {k: mask_pii(data=v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_pii(data=v) for v in data]
    return data


@cache
def _client():
    from langfuse import Langfuse  # imported lazily: no cost when tracing is off

    # CI sets unused secrets to "", which Langfuse would treat as real values.
    for var in ("LANGFUSE_BASE_URL", "LANGFUSE_TRACING_ENVIRONMENT"):
        if os.environ.get(var) == "":
            del os.environ[var]
    from langfuse.span_filter import is_langfuse_span

    # The first Langfuse() becomes the process-wide client that get_client() returns.
    return Langfuse(
        mask=mask_pii,
        # The Anthropic SDK emits its own OpenTelemetry span per call. Our generation already
        # records the same call with the prompt, output and prompt version, so exporting both
        # would show every call twice and double-count its cost. Keep only our own spans.
        should_export_span=is_langfuse_span,
    )


# --- traces ---


class Trace:
    """The root span of one trace. `update` sets the trace's output; `score` scores the trace."""

    def __init__(self, span: Any | None):
        self._span = span

    def update(self, **kwargs: Any) -> None:
        if self._span is not None:
            self._span.update(**kwargs)

    def score(self, name: str, passed: bool, comment: str | None = None) -> None:
        """Boolean scores: filter traces by them in the UI, chart pass rates over time."""
        if self._span is not None:
            self._span.score_trace(
                name=name, value=1 if passed else 0, data_type="BOOLEAN", comment=comment
            )


@contextmanager
def trace(
    name: str,
    *,
    input: Any,
    tags: list[str],
    session_id: str | None = None,
    metadata: dict | None = None,
) -> Iterator[Trace]:
    """Start a trace. Everything traced inside the block nests under it and shares its
    attributes (name, tags, session, metadata), so traces can be filtered by them."""
    if not enabled():
        yield Trace(None)
        return
    from langfuse import propagate_attributes

    # propagate_attributes goes outside the root span so the root gets the attributes too.
    with (
        propagate_attributes(trace_name=name, tags=tags, session_id=session_id, metadata=metadata),
        _client().start_as_current_observation(name=name, as_type="span", input=input) as span,
    ):
        yield Trace(span)


# --- generations: one per model call ---


class Generation:
    """Wraps a Langfuse generation (or nothing) behind one `record(outcome)` method."""

    def __init__(self, generation: Any | None):
        self._generation = generation

    def record(self, outcome: Any, extra: dict | None = None) -> None:
        if self._generation is None:
            return
        from ticket_triage.schema import TriageFailure

        stats = outcome.stats
        kwargs: dict[str, Any] = {"metadata": extra or {}}
        if stats is not None:
            kwargs["model"] = stats.model  # the model that served it, not just the one asked for
            if stats.input_tokens is not None:
                kwargs["usage_details"] = {
                    "input": stats.input_tokens,
                    "output": stats.output_tokens,
                }
            if stats.cost_usd is not None:
                kwargs["cost_details"] = {"total": stats.cost_usd}
        if isinstance(outcome, TriageFailure):
            self._generation.update(
                output=outcome.raw,
                level="ERROR",
                status_message=f"{outcome.reason}: {outcome.detail}",
                **kwargs,
            )
        else:
            self._generation.update(output=outcome.value.model_dump(mode="json"), **kwargs)


@contextmanager
def generation(
    *,
    name: str,
    model: str,
    prompt_id: str,
    system: str,
    user: str,
    model_parameters: dict,
    metadata: dict | None = None,
) -> Iterator[Generation]:
    if not enabled():
        yield Generation(None)
        return
    with _client().start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        # Chat-message form, so the UI shows exactly what the model saw.
        input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        model_parameters=model_parameters,
        version=prompt_id,
        metadata={"prompt_version": prompt_id, **(metadata or {})},
    ) as gen:
        yield Generation(gen)


def flush() -> None:
    """Send buffered traces and scores before the process exits (short-lived CLI runs)."""
    if enabled():
        _client().flush()
