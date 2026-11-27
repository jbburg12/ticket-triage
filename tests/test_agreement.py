"""Judge-vs-human agreement, with a fake client and in-memory labels."""

import json

from conftest import GOOD_OUTPUT, FakeClient, fake_response

from ticket_triage.evals import agreement
from ticket_triage.evals.dataset import GoldenTicket, HumanLabel
from ticket_triage.evals.judge import CRITERIA
from ticket_triage.schema import TriageResult

TICKET = GoldenTicket(id="a", text="x", expected_category="billing", expected_priority="high")


def _label(**fails: bool) -> HumanLabel:
    return HumanLabel(
        ticket_id="a",
        model="m",
        prompt_version="v1",
        output=TriageResult.model_validate(GOOD_OUTPUT),
        labels={c: not fails.get(c, False) for c in CRITERIA},
    )


def _verdict(**fails: bool) -> str:
    return json.dumps({c: {"reason": "r", "passed": not fails.get(c, False)} for c in CRITERIA})


def _run(monkeypatch, labels, verdicts):
    monkeypatch.setattr(agreement, "load_human_labels", lambda: labels)
    monkeypatch.setattr(agreement, "load_golden", lambda: [TICKET])
    client = FakeClient(*(fake_response(v, model="claude-sonnet-5-5") for v in verdicts))
    return agreement.run_agreement(client=client)["per_criterion"]


def test_perfect_agreement_on_passes_alone_does_not_validate(monkeypatch):
    result = _run(monkeypatch, [_label(), _label()], [_verdict(), _verdict()])
    assert result["safe_reply"]["agreement"] == 1.0
    assert result["safe_reply"]["human_fails"] == 0
    assert not result["safe_reply"]["validated"]


def test_catching_a_human_failure_validates(monkeypatch):
    labels = [_label(), _label(safe_reply=True)]
    result = _run(monkeypatch, labels, [_verdict(), _verdict(safe_reply=True)])
    assert result["safe_reply"]["human_fails"] == 1
    assert result["safe_reply"]["validated"]
    assert not result["helpful_reply"]["validated"]  # no failures labelled for this one


def test_missing_a_human_failure_does_not_validate(monkeypatch):
    labels = [_label(), _label(safe_reply=True)]
    result = _run(monkeypatch, labels, [_verdict(), _verdict()])
    assert result["safe_reply"]["agreement"] == 0.5
    assert not result["safe_reply"]["validated"]
