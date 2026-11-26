"""Loading the golden dataset and the hand labels."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ticket_triage.config import DATA_DIR
from ticket_triage.schema import Category, Priority, TriageResult

GOLDEN_PATH = DATA_DIR / "golden.jsonl"
HUMAN_LABEL_IDS_PATH = DATA_DIR / "human_label_ids.txt"
HUMAN_LABELS_PATH = DATA_DIR / "human_labels.jsonl"


class GoldenTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    expected_category: Category
    expected_priority: Priority
    tags: list[str] = []
    notes: str = ""
    # Only for injection tickets: text whose presence in the reply shows the injected
    # instruction was followed. Matched case-insensitively.
    forbidden_phrases: list[str] = []


class HumanLabel(BaseModel):
    """Your pass/fail grades for one stored triage output.

    The output is stored with the labels, so the judge is later run on exactly what you saw.
    """

    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    model: str
    prompt_version: str
    output: TriageResult
    labels: dict[str, bool]
    note: str = ""


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenTicket]:
    tickets = [GoldenTicket.model_validate(row) for row in read_jsonl(path)]
    ids = [t.id for t in tickets]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate ticket ids in {path}: {sorted(duplicates)}")
    return tickets


def load_human_label_ids(path: Path = HUMAN_LABEL_IDS_PATH) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def load_human_labels(path: Path = HUMAN_LABELS_PATH) -> list[HumanLabel]:
    return [HumanLabel.model_validate(row) for row in read_jsonl(path)]


def append_human_label(label: HumanLabel, path: Path = HUMAN_LABELS_PATH) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(label.model_dump_json() + "\n")
