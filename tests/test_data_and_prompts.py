"""Sanity checks on the files the eval depends on."""

from collections import Counter

from ticket_triage.config import DATA_DIR
from ticket_triage.evals.dataset import load_golden, load_human_label_ids
from ticket_triage.evals.judge import CRITERIA
from ticket_triage.prompts import load_prompt

HOLDOUT = DATA_DIR / "holdout.jsonl"


def test_golden_dataset_is_valid_and_covers_every_slice():
    tickets = load_golden()
    assert 25 <= len(tickets) <= 40
    tags = Counter(tag for t in tickets for tag in t.tags)
    for slice_ in ["clear", "ambiguous", "multi_issue", "angry", "non_english", "injection"]:
        assert tags[slice_] >= 3, slice_
    assert {t.expected_category for t in tickets} == {
        "billing",
        "login",
        "bug",
        "feature_request",
        "other",
    }


def test_injection_tickets_have_forbidden_phrases():
    for t in [*load_golden(), *load_golden(HOLDOUT)]:
        if "injection" in t.tags:
            assert t.forbidden_phrases, t.id


def test_holdout_is_valid_and_separate_from_golden():
    """The held-out set only means something if no golden ticket leaks into it."""
    golden, holdout = load_golden(), load_golden(HOLDOUT)
    assert holdout
    assert all(t.id.startswith("h") for t in holdout)
    assert not {t.id for t in golden} & {t.id for t in holdout}
    normalise = lambda text: " ".join(text.lower().split())  # noqa: E731
    assert not {normalise(t.text) for t in golden} & {normalise(t.text) for t in holdout}


def test_human_label_ids_exist_in_golden():
    ids = {t.id for t in load_golden()}
    assert set(load_human_label_ids()) <= ids


def test_prompts_load_with_metadata():
    triage = load_prompt("triage", "v1")
    assert triage.id == "triage/v1"
    assert triage.meta["effort"] == "low"
    assert not triage.text.startswith("---")


def test_every_judge_prompt_names_every_criterion():
    for version in ("v1", "v2", "v3"):
        text = load_prompt("judge", version).text
        for criterion in CRITERIA:
            assert f"## {criterion}" in text, (version, criterion)
