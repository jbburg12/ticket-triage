"""Project-wide settings. Everything tunable lives here, not scattered through the code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

# Day-to-day model under test, the comparison model, and the fixed judge.
DEFAULT_MODEL = "claude-haiku-5-5"
COMPARISON_MODEL = "claude-opus-5-5"
JUDGE_MODEL = "claude-sonnet-5-5"

DEFAULT_TRIAGE_PROMPT = "v3"
DEFAULT_JUDGE_PROMPT = "v3"  # validated against hand labels: results/agreement-judge-v3.md

# USD per million tokens (input, output). Used for the cost numbers in traces and reports.
# Source: Anthropic pricing, November 2026. Haiku's price is for prompts under 100K tokens,
# which is always true here.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of one request, or None if the model isn't in the price table."""
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000
