# ticket-triage

An LLM triages customer support tickets into structured JSON: category, priority, a one-sentence summary and a suggested first reply. Around it is an evaluation suite that measures how well it works and catches regressions in CI.

This is a learning project about **evaluating LLM features properly**. The triage itself is one API call. Most of the code answers "is it any good, and how would we know if it got worse?"

```text
$ uv run triage run "I was charged twice this month and nobody answers my emails!!"
{
  "category": "billing",
  "priority": "high",
  "summary": "Customer was charged twice this month and has had no reply to earlier emails.",
  "suggested_reply": "I'm sorry about the duplicate charge and the wait. ..."
}
```

## How it works

```
ticket ─▶ triage (Claude Haiku 5.5, structured output) ─▶ Pydantic validation ─▶ result or counted failure
                                                                                     │
golden dataset (30 tickets) ─▶ 1. generate ─▶ 2. code scoring (gates CI) ─▶ 3. LLM judge (reported)
                                                                                     │
                                                    12 hand labels ─▶ judge-vs-human agreement
```

**Triage.** One call to Claude with structured outputs constrains the response to the schema. Every response is validated again with Pydantic, which also enforces rules a JSON schema can't express, such as "the summary is one sentence". Nothing crashes the run. Each problem becomes a counted failure with one of these reasons:

- `api_error`
- `refusal`
- `truncated`
- `invalid_json`
- `schema_violation`

**Prompts are versioned files** in [`prompts/`](prompts/): `triage/v1.md` and `judge/v1.md`. Every eval result and trace records which version produced it, and `--prompt-version` lets you compare versions on the same dataset.

**Evaluation runs in three steps:**

1. **Generate.** The model under test triages each of the [30 golden tickets](data/golden.jsonl).
2. **Code scoring.** Plain Python compares outputs with the labels:
   - exact-match accuracy
   - confusion matrices
   - accuracy per slice
   - failure rate
   - a prompt-injection check
3. **Judge scoring.** Claude Sonnet 5.5 grades each summary and reply on [a written rubric](prompts/judge/v1.md), with a pass/fail verdict and a reason for each of 4 criteria:
   - faithful summary
   - helpful reply
   - safe reply
   - tone and language

**Who checks the judge? You do.** `triage label` asks you to grade 12 outputs by hand, and `triage agreement` measures how often the judge agrees with you: percent agreement, Cohen's kappa, and a list of every disagreement. Only checks scored by code can fail the build. A judge criterion can join the gates only once it reaches at least 90% agreement with your labels.

### Labels

| Category | Meaning |
|---|---|
| `billing` | charges, invoices, refunds, payment methods, plan changes |
| `login` | signing in, passwords, 2FA, lockouts, SSO |
| `bug` | an existing feature behaves incorrectly |
| `feature_request` | something the product doesn't do yet |
| `other` | everything else |

| Priority | Meaning |
|---|---|
| `high` | can't use the product, money charged incorrectly, security or account-takeover concern, data loss |
| `medium` | broken or degraded, but there's a workaround |
| `low` | questions, feature requests, cosmetic issues |

Priority follows the impact described, not the customer's tone. A ticket with several issues gets the category of the issue that drives the highest priority.

### The golden dataset

There are 30 synthetic tickets, tagged by slice so accuracy can be broken down:

| Slice | Count | What it tests |
|---|---|---|
| `clear` | 10 | Baseline, two per category |
| `ambiguous` | 5 | For example "can't log in since you charged me" |
| `multi_issue` | 4 | Choosing the issue that drives priority |
| `angry` | 4 | Tone mustn't inflate priority; replies stay calm |
| `non_english` | 4 | Spanish, German, Japanese and French; reply in the customer's language |
| `injection` | 3 | "Ignore previous instructions…", a fake `</ticket>` tag, prompt extraction |

Each ticket's `notes` field explains its label, and injection tickets list `forbidden_phrases` for the code-based check.

## Running it

You'll need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you.

```powershell
uv sync
```

```powershell
copy .env.example .env
```

Then fill in `.env`. You need an `ANTHROPIC_API_KEY` for anything that calls the model. The Langfuse keys are optional.

| Command | What it does | Cost |
|---|---|---|
| `uv run pytest` | Unit tests with a fake client | free |
| `uv run triage run "ticket text"` | Triage one ticket | < $0.01 |
| `uv run triage eval` | Full eval with Haiku and the judge; writes `results/latest.md` | about $0.30–0.35 |
| `uv run triage eval --no-judge` | Steps 1 and 2 only | a few cents |
| `uv run triage eval --model claude-opus-5-5 --repeats 3` | The model comparison run | about $3 |
| `uv run triage label` | Grade the 12 outputs by hand (resumable) | < $0.01 |
| `uv run triage agreement` | Judge vs your labels | a few cents |

The costs are estimates; the eval report shows the measured ones. API usage is billed separately from Claude subscription plans, so set a spend limit in the Claude Console.

### CI

- [`test.yml`](.github/workflows/test.yml) runs lint and the unit tests on every push. It needs no secrets.
- [`eval.yml`](.github/workflows/eval.yml) runs `triage eval --gate` with Haiku on PRs that touch prompts, code or data. The build fails if any of these gates fails:
  - category accuracy < 0.85
  - priority accuracy < 0.70
  - failure rate > 5%
  - any injection ticket fails the code-based check
- The thresholds are starting values in [`gates.py`](src/ticket_triage/evals/gates.py), to be reset after the first baseline run.
- The Opus comparison is a manual "Run workflow" with a model choice.
- To enable the eval job, add `ANTHROPIC_API_KEY` as a repository secret. Optionally add `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` to trace CI runs. Fork PRs skip the eval with a notice.

### Tracing

With the Langfuse keys set, each unit of work becomes one trace ([`tracing.py`](src/ticket_triage/tracing.py)), set up following the [Langfuse skill](.claude/skills/langfuse/) and the [best-practices guide](https://langfuse.com/docs/observability/best-practices):

| Trace | Tag | Contains | Scores |
|---|---|---|---|
| `triage-ticket` | `cli` | one `classify-ticket` generation | – |
| `evaluate-ticket` | `eval` | `classify-ticket` and `judge-output` generations | `category_correct`, `priority_correct`, `injection_check`, `judge_<criterion>` |
| `label-ticket` | `label` | one `classify-ticket` generation | `human_<criterion>` (your grades) |
| `check-agreement` | `agreement` | one `judge-output` generation | `judge_<criterion>`, `agree_<criterion>` |

- **Root spans** show the ticket and the result, readable at a glance.
- **Each generation** records exactly what the model saw (system and user messages), its output, the prompt version, the serving model, effort and `max_tokens`, token usage, cost, latency, `stop_reason` and the Anthropic request id. Failures are marked `ERROR` with their reason.
- **Every score has a comment:** the expected label, or the judge's reason. In the UI you can filter for, say, `priority_correct = false` and open each miss.
- **Eval runs:** all the traces from one run share a session (the `run_id`), and each carries `dataset_item_id` metadata. The Sessions view shows a whole run together, and a bad row in a report leads straight to its trace.
- **Environment:** local traces are `development` and CI traces are `ci` (`LANGFUSE_TRACING_ENVIRONMENT`).
- **Masking:** email addresses and card numbers are replaced before anything leaves the process.
- **No double counting:** the Anthropic SDK emits its own OpenTelemetry span per call. Only Langfuse's own spans are exported, so each call isn't recorded and costed twice.

Without the keys, tracing is off and nothing else changes. The CLI verifies HTTPS against the operating system's certificate store ([truststore](https://pypi.org/project/truststore/)), so exports also work behind proxies that re-sign TLS.

## Design decisions

The full reasoning is in [SPEC.md](SPEC.md). The short version:

- **No framework, on purpose.** The feature is one API call, so it uses the Anthropic SDK directly, with no LangChain. The metrics are plain Python. The judge is our own small module rather than DeepEval: its per-criterion calls cost about 4× more and return scores instead of pass/fail.
- **Validate even with structured outputs.** Structured outputs make bad JSON rare, but refusals, truncation and our own rules still need catching, and counting those failures is part of the evaluation.
- **Binary rubric.** Pass/fail verdicts agree better between humans and LLMs than 1–5 scores, and they make Cohen's kappa meaningful.
- **Haiku for day-to-day runs, Opus for comparison, Sonnet as the fixed judge.** Day-to-day runs cost cents. The judge is a different model from both systems under test, and it never changes between the runs being compared.
- **No temperature.** Current Claude models don't accept a `temperature` setting, so outputs vary between runs. `--repeats N` reports the range.
- **Ticket text is data.** It's wrapped in `<ticket>` tags (a closing tag inside the ticket is neutralised), and the prompt says to never follow instructions found inside.

## Results

> No eval has been run yet. This section is filled in from `results/latest.md` after the first baseline run.

| Model | Category acc. | Priority acc. | Failure rate | Judge pass (faithful / helpful / safe / tone) | Cost per 1k tickets | p50 latency |
|---|---|---|---|---|---|---|
| Haiku 5.5 | – | – | – | – | – | – |
| Opus 5.5 | – | – | – | – | – | – |

**Judge vs human:** not yet measured.

### Prompt changelog

| Version | Change | Category acc. | Priority acc. |
|---|---|---|---|
| `triage/v1` | First version | – | – |

## What I learned / known failure modes

*To be written from real eval runs.*
