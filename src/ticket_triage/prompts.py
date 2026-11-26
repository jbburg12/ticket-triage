"""Load versioned prompt files: prompts/<name>/<version>.md.

Each file starts with a small front-matter block of `key: value` lines between `---` markers,
followed by the prompt text:

    ---
    version: v1
    notes: first version
    ---
    You are a support triage assistant...
"""

from dataclasses import dataclass, field
from pathlib import Path

from ticket_triage.config import PROMPTS_DIR


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """e.g. 'triage/v1': what traces and results record."""
        return f"{self.name}/{self.version}"


def load_prompt(name: str, version: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / name / f"{version}.md"
    if not path.exists():
        available = sorted(p.stem for p in (prompts_dir / name).glob("*.md"))
        raise FileNotFoundError(f"No prompt {name}/{version}. Available: {available}")
    meta, text = _split_front_matter(path.read_text(encoding="utf-8"))
    if meta.get("version", version) != version:
        raise ValueError(f"{path} says version {meta['version']!r} but is named {version!r}")
    return Prompt(name=name, version=version, text=text.strip(), meta=meta)


def _split_front_matter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content
    header, _, body = content[3:].partition("\n---")
    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip()] = value.strip()
    return meta, body
