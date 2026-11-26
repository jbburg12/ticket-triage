"""Trace structure, checked offline against a fake Langfuse client."""

import json
from contextlib import contextmanager

import langfuse
import pytest
from conftest import GOOD_OUTPUT, FakeClient, fake_response

from ticket_triage import tracing
from ticket_triage.evals.dataset import GoldenTicket
from ticket_triage.evals.judge import CRITERIA
from ticket_triage.evals.runner import run_eval


class FakeObservation:
    def __init__(self, name, as_type, parent, attributes, **kwargs):
        self.name, self.as_type, self.parent = name, as_type, parent
        self.attributes = attributes  # what propagate_attributes set at creation
        self.created = kwargs
        self.updates: dict = {}
        self.scores: dict = {}

    def update(self, **kwargs):
        self.updates.update(kwargs)

    def score_trace(self, *, name, value, data_type, comment=None):
        self.scores[name] = (value, data_type, comment)


class FakeLangfuse:
    def __init__(self):
        self.observations: list[FakeObservation] = []
        self._stack: list[FakeObservation] = []
        self.attributes: dict = {}

    @contextmanager
    def start_as_current_observation(self, *, name, as_type, **kwargs):
        parent = self._stack[-1] if self._stack else None
        obs = FakeObservation(name, as_type, parent, dict(self.attributes), **kwargs)
        self.observations.append(obs)
        self._stack.append(obs)
        try:
            yield obs
        finally:
            self._stack.pop()

    @contextmanager
    def propagate(self, **attributes):
        saved = self.attributes
        self.attributes = {**saved, **attributes}
        try:
            yield
        finally:
            self.attributes = saved


@pytest.fixture
def fake_langfuse(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "enabled", lambda: True)
    monkeypatch.setattr(tracing, "_client", lambda: fake)
    monkeypatch.setattr(langfuse, "propagate_attributes", fake.propagate)
    return fake


def test_eval_traces_one_tree_per_ticket_with_scores(fake_langfuse):
    ticket = GoldenTicket(
        id="a", text="charged twice", expected_category="billing", expected_priority="low"
    )
    verdict = {c: {"reason": f"{c} ok", "passed": c != "helpful_reply"} for c in CRITERIA}
    client = FakeClient(
        fake_response(json.dumps(GOOD_OUTPUT)),
        fake_response(json.dumps(verdict), model="claude-sonnet-5-5"),
    )
    run_eval(model="claude-haiku-5-5", tickets=[ticket], client=client, workers=1)

    root, triage_gen, judge_gen = fake_langfuse.observations
    assert (root.name, root.as_type, root.parent) == ("evaluate-ticket", "span", None)
    assert root.attributes["trace_name"] == "evaluate-ticket"
    assert root.attributes["tags"] == ["eval"]
    assert root.attributes["metadata"]["dataset_item_id"] == "a"
    assert root.attributes["session_id"] == root.attributes["metadata"]["run_id"]
    assert root.created["input"]["ticket"] == "charged twice"
    assert root.updates["output"]["category"] == "billing"

    # One generation per model call, nested under the ticket's trace.
    assert [(g.name, g.as_type, g.parent) for g in (triage_gen, judge_gen)] == [
        ("classify-ticket", "generation", root),
        ("judge-output", "generation", root),
    ]
    assert triage_gen.created["version"] == "triage/v1"
    assert triage_gen.created["input"][0]["role"] == "system"
    assert triage_gen.created["model_parameters"] == {"effort": "low", "max_tokens": 4000}
    assert triage_gen.updates["usage_details"] == {"input": 1000, "output": 200}
    assert triage_gen.updates["metadata"]["stop_reason"] == "end_turn"
    assert judge_gen.updates["model"] == "claude-sonnet-5-5"

    assert root.scores["category_correct"][:2] == (1, "BOOLEAN")
    assert root.scores["priority_correct"] == (0, "BOOLEAN", "expected low, got high")
    assert root.scores["judge_helpful_reply"] == (0, "BOOLEAN", "helpful_reply ok")
    assert "injection_check" not in root.scores


def test_failed_call_is_an_error_generation(fake_langfuse):
    ticket = GoldenTicket(
        id="a", text="x", expected_category="bug", expected_priority="low", tags=["injection"]
    )
    run_eval(
        model="claude-haiku-5-5",
        tickets=[ticket],
        client=FakeClient(fake_response("garbage")),
        with_judge=False,
        workers=1,
    )
    root, gen = fake_langfuse.observations
    assert gen.updates["level"] == "ERROR"
    assert gen.updates["status_message"].startswith("invalid_json")
    assert root.updates["output"] == {"failure": "invalid_json"}
    assert root.scores["category_correct"][0] == 0
    assert root.scores["injection_check"][0] == 0


def test_mask_pii():
    data = {
        "ticket": "Mail me at jane.doe+x@example.co.uk, card 4111 1111 1111 1111.",
        "nested": ["order 12345 is fine", 3],
    }
    assert tracing.mask_pii(data=data) == {
        "ticket": "Mail me at [EMAIL], card [CARD].",
        "nested": ["order 12345 is fine", 3],
    }
