"""Sanity checks on the files the eval depends on."""

from collections import Counter

from ticket_triage.evals.dataset import load_golden, load_human_label_ids
from ticket_triage.evals.judge import CRITERIA
from ticket_triage.prompts import load_prompt


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
    for t in load_golden():
        if "injection" in t.tags:
            assert t.forbidden_phrases, t.id


def test_human_label_ids_exist_in_golden():
    ids = {t.id for t in load_golden()}
    assert set(load_human_label_ids()) <= ids


def test_prompts_load_with_metadata():
    triage = load_prompt("triage", "v1")
    assert triage.id == "triage/v1"
    assert triage.meta["effort"] == "low"
    assert not triage.text.startswith("---")


def test_judge_prompt_names_every_criterion():
    text = load_prompt("judge", "v1").text
    for criterion in CRITERIA:
        assert f"## {criterion}" in text
