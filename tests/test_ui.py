"""The web UI's API: triage through a fake client, and reading eval results from disk."""

import json

import pytest
from conftest import GOOD_OUTPUT, FakeClient, fake_response
from fastapi.testclient import TestClient

from ticket_triage.config import PROMPTS_DIR
from ticket_triage.ui.app import create_app

TICKET = {
    "id": "t001",
    "text": "I was charged twice.",
    "expected_category": "billing",
    "expected_priority": "high",
    "tags": ["clear"],
    "notes": "Incorrect charge = high.",
}


def _run(run_id: str, timestamp: str, dataset: str | None = "golden") -> dict:
    run = {
        "run_id": run_id,
        "timestamp": timestamp,
        "model": "claude-haiku-5-5",
        "prompt_version": "v3",
        "judge_model": None,
        "repeats": 1,
        "n_tickets": 1,
        "metrics": {"category_accuracy": 1.0, "priority_accuracy": 1.0, "failure_rate": 0.0},
        "gates": [{"name": "category accuracy", "passed": True}],
        "rows": [{"id": "t001", "repeat": 0, "tags": ["clear"], "predicted": GOOD_OUTPUT}],
    }
    if dataset is not None:
        run["dataset"] = dataset
    return run


@pytest.fixture
def dirs(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "golden.jsonl").write_text(json.dumps(TICKET) + "\n", encoding="utf-8")
    results = tmp_path / "results"
    (results / "history").mkdir(parents=True)
    old = _run("old-run", "2026-11-01T00:00:00+00:00", dataset=None)  # predates `dataset`
    new = _run("new-run", "2026-11-02T00:00:00+00:00")
    (results / "history" / "old-run.json").write_text(json.dumps(old), encoding="utf-8")
    (results / "history" / "new-run.json").write_text(json.dumps(new), encoding="utf-8")
    (results / "latest.json").write_text(json.dumps(new), encoding="utf-8")
    return data, results


def _client(dirs, *responses) -> TestClient:
    data, results = dirs
    fake = FakeClient(*responses) if responses else None
    return TestClient(create_app(client=fake, data_dir=data, results_dir=results))


def test_index_and_static_files_are_served(dirs):
    ui = _client(dirs)
    assert "ticket-triage" in ui.get("/").text
    assert ui.get("/static/app.js").status_code == 200


def test_options_list_models_and_prompt_versions(dirs):
    opts = _client(dirs).get("/api/options").json()
    assert "claude-haiku-5-5" in opts["models"]
    expected = sorted(p.stem for p in (PROMPTS_DIR / "triage").glob("*.md"))
    assert sorted(opts["prompt_versions"]) == expected
    assert opts["default_prompt_version"] in opts["prompt_versions"]


def test_examples_come_from_the_golden_set(dirs):
    [ex] = _client(dirs).get("/api/examples").json()
    assert ex["id"] == "t001"
    assert ex["expected"] == {"category": "billing", "priority": "high"}


def test_triage_success(dirs, good_text):
    res = _client(dirs, fake_response(good_text)).post("/api/triage", json={"text": "hi"})
    body = res.json()
    assert res.status_code == 200 and body["ok"]
    assert body["result"] == GOOD_OUTPUT
    assert body["stats"]["input_tokens"] == 1000


def test_triage_failure_is_a_normal_response(dirs):
    res = _client(dirs, fake_response("not json")).post("/api/triage", json={"text": "hi"})
    body = res.json()
    assert res.status_code == 200 and not body["ok"]
    assert body["failure"]["error"] == "invalid_json"


@pytest.mark.parametrize(
    "payload",
    [
        {"text": ""},
        {"text": "x" * 10_001},
        {"text": "hi", "model": "gpt-4"},
        {"text": "hi", "prompt_version": "v99"},
    ],
)
def test_bad_triage_requests_are_rejected(dirs, payload):
    assert _client(dirs).post("/api/triage", json=payload).status_code == 422


def test_missing_api_key_is_a_clear_error(dirs, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    res = _client(dirs).post("/api/triage", json={"text": "hi"})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]


VERDICTS = {
    "faithful_summary": {"reason": "Only facts from the ticket.", "passed": True},
    "helpful_reply": {"reason": "Asks for the invoice numbers.", "passed": True},
    "safe_reply": {"reason": "Promises a refund.", "passed": False},
    "tone_and_language": {"reason": "Calm and in English.", "passed": True},
}


def test_judge_returns_verdicts_with_reasons(dirs):
    client = FakeClient(fake_response(json.dumps(VERDICTS), model="claude-sonnet-5-5"))
    ui = TestClient(create_app(client=client, data_dir=dirs[0], results_dir=dirs[1]))
    res = ui.post("/api/judge", json={"text": "I was charged twice.", "output": GOOD_OUTPUT})
    body = res.json()

    assert res.status_code == 200 and body["ok"]
    assert body["verdicts"] == VERDICTS
    assert body["stats"]["model"] == "claude-sonnet-5-5"
    # The judge sees the ticket and the output it grades.
    sent = client.requests[0]["messages"][0]["content"]
    assert "I was charged twice." in sent and GOOD_OUTPUT["suggested_reply"] in sent


def test_judge_failure_is_a_normal_response(dirs):
    res = _client(dirs, fake_response("nope")).post(
        "/api/judge", json={"text": "hi", "output": GOOD_OUTPUT}
    )
    assert res.status_code == 200 and res.json()["failure"]["error"] == "invalid_json"


def test_judge_rejects_an_invalid_output(dirs):
    bad = {**GOOD_OUTPUT, "summary": "Two sentences. Not allowed."}
    res = _client(dirs).post("/api/judge", json={"text": "hi", "output": bad})
    assert res.status_code == 422


def test_runs_are_listed_newest_first_without_duplicates(dirs):
    runs = _client(dirs).get("/api/runs").json()
    assert [r["run_id"] for r in runs] == ["new-run", "old-run"]
    assert runs[1]["dataset"] == "golden"  # filled in for runs that predate the field
    assert runs[0]["gates_passed"] is True


def test_run_detail_joins_ticket_text(dirs):
    run = _client(dirs).get("/api/runs/old-run").json()
    assert run["dataset"] == "golden"
    assert run["rows"][0]["text"] == TICKET["text"]
    assert run["rows"][0]["notes"] == TICKET["notes"]


@pytest.mark.parametrize("run_id", ["nope", "..%2Flatest", "..%2F..%2Fpyproject"])
def test_unknown_runs_are_404(dirs, run_id):
    assert _client(dirs).get(f"/api/runs/{run_id}").status_code == 404
