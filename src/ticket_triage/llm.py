"""One structured-output call to Claude, with every failure mode turned into a value.

Both the triage step and the judge go through `structured_call`, so they share the same
error handling, validation, and tracing.
"""

import json
import time
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, ValidationError

from ticket_triage import tracing
from ticket_triage.config import cost_usd
from ticket_triage.schema import CallStats, TriageFailure


@dataclass
class Parsed[T: BaseModel]:
    value: T
    stats: CallStats


def structured_call[T: BaseModel](
    client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    user: str,
    wire_schema: dict,
    output_model: type[T],
    prompt_id: str,
    generation_name: str,
    effort: str = "low",
    max_tokens: int = 4000,
) -> Parsed[T] | TriageFailure:
    with tracing.generation(
        name=generation_name,
        model=model,
        prompt_id=prompt_id,
        system=system,
        user=user,
        model_parameters={"effort": effort, "max_tokens": max_tokens},
    ) as gen:
        outcome, extra = _call(
            client, model, system, user, wire_schema, output_model, effort, max_tokens
        )
        gen.record(outcome, extra)
        return outcome


def _call(client, model, system, user, wire_schema, output_model, effort, max_tokens):
    """Returns the outcome, plus extra details that only the trace needs."""
    outcome, response = _call_inner(
        client, model, system, user, wire_schema, output_model, effort, max_tokens
    )
    extra: dict = {}
    if response is not None:
        extra["stop_reason"] = response.stop_reason
        if request_id := getattr(response, "_request_id", None):
            extra["request_id"] = request_id  # quote this to Anthropic support
        thinking = "".join(b.thinking for b in response.content if b.type == "thinking")
        if thinking:
            extra["thinking"] = thinking
    return outcome, extra


def _call_inner(client, model, system, user, wire_schema, output_model, effort, max_tokens):
    start = time.perf_counter()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": wire_schema},
            },
        )
    except anthropic.APIError as exc:
        # Rate limits, 5xx and network errors are already retried by the SDK (2 retries).
        # Whatever is left is counted, not raised.
        stats = CallStats(model=model, latency_s=time.perf_counter() - start)
        return TriageFailure("api_error", f"{type(exc).__name__}: {exc}", stats=stats), None

    stats = CallStats(
        # The model that actually served the request, as reported by the API.
        model=response.model,
        latency_s=time.perf_counter() - start,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=cost_usd(model, response.usage.input_tokens, response.usage.output_tokens),
    )
    text = "".join(block.text for block in response.content if block.type == "text")

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        return TriageFailure(
            "refusal", f"refused (category={category})", raw=text, stats=stats
        ), response
    if response.stop_reason == "max_tokens":
        return TriageFailure(
            "truncated", f"hit max_tokens={max_tokens}", raw=text, stats=stats
        ), response

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return TriageFailure("invalid_json", str(exc), raw=text, stats=stats), response
    try:
        value = output_model.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return TriageFailure("schema_violation", errors, raw=text, stats=stats), response
    return Parsed(value=value, stats=stats), response
