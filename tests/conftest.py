"""A fake Anthropic client, so unit tests never call the API."""

import json
from types import SimpleNamespace

import pytest

GOOD_OUTPUT = {
    "category": "billing",
    "priority": "high",
    "summary": "Customer was charged twice for this month's subscription.",
    "suggested_reply": "Sorry about the double charge. Could you share the invoice numbers?",
}


def fake_response(
    text: str, stop_reason: str = "end_turn", model: str = "claude-haiku-5-5", stop_details=None
):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=model,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
    )


class FakeClient:
    """Returns queued responses (or raises queued exceptions) and records each request."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def good_text() -> str:
    return json.dumps(GOOD_OUTPUT)


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch):
    """Unit tests never send traces, even if a developer's shell has Langfuse keys set."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
