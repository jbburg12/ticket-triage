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

**Prompts are versioned files** in [`prompts/`](prompts/): `triage/v1.md`, and `judge/v1.md` to `judge/v3.md`. Every eval result and trace records which version produced it, and `--prompt-version` lets you compare versions on the same dataset.

**Evaluation runs in three steps:**

1. **Generate.** The model under test triages each of the [30 golden tickets](data/golden.jsonl).
2. **Code scoring.** Plain Python compares outputs with the labels:
   - exact-match accuracy
   - confusion matrices
   - accuracy per slice
   - failure rate
   - a prompt-injection check
3. **Judge scoring.** Claude Sonnet 5.5 grades each summary and reply on [a written rubric](prompts/judge/v3.md), with a pass/fail verdict and a reason for each of 4 criteria:
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

Rules for the borderline cases, settled while reviewing the golden and held-out labels (and written into `triage/v3`):
- **Problem, not cause.** A customer who can't sign in has a `login` problem, even if they blame a payment or an update.
- **Locked out is `high`** even when a recovery route exists but fails, for example a reset email that never arrives. Login friction that still lets you in is `medium`.
- **Wrong data or behaviour is at least `medium`**, however easy the workaround. Appearance-only problems are `low`.
- **A feature that never existed is a `feature_request`**, however it's phrased ("why can't I…?"). It's a `bug` only if the feature exists and misbehaves.

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

Each ticket's `notes` field explains its label, and injection tickets list `forbidden_phrases` for the code-based check. The tickets and labels were drafted with Claude and then reviewed by hand, with the judgement calls (t011, t012, t013, t016) decided explicitly. Only 5 tickets are `medium`, so medium-priority accuracy is the noisiest number.

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
- [`eval.yml`](.github/workflows/eval.yml) runs `triage eval --gate` with Haiku on PRs that could change eval results. It triggers on:
  - prompts
  - the golden set
  - the triage and eval code
  - dependencies
  - the workflow itself

  Unrelated changes, like a UI or docs, skip it, and when that code is added, its folder stays off the list. The build fails if any of these gates fails:
  - category accuracy < 0.90 (4+ misses out of 30)
  - priority accuracy < 0.87 (5+ misses)
  - failure rate > 5% (2+ failed triages)
  - any injection ticket fails the code-based check
  - any summary isn't in English (the regression `triage/v2` got away with)
- The thresholds are in [`gates.py`](src/ticket_triage/evals/gates.py). They're set from `triage/v3`'s worst golden run minus a margin of about one ticket: tight enough to catch a real regression, loose enough not to fail on run-to-run noise. They need re-deriving whenever the default prompt, model or golden set changes.
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
| Haiku 5.5 (`triage/v3`), held-out set | **94.7%** | **86.7%** | 1.3% | – | $0.28 | 1.9s |
| Haiku 5.5 (`triage/v3`), golden set | 98.9% | 100% | 0% | 100% / 100% / 100% / 100% | $0.28 | 1.9s |
| Opus 5.5 (`triage/v3`), held-out set | **100%** | **100%** | 0% | – | $12.21 | 3.1s |
| Opus 5.5 (`triage/v3`), golden set | 100% | 100% | 0% | 100% / 100% / 100% / 100% | $11.95 | 2.9s |

Accuracy pools 3 runs per set; judge scores come from one run on the golden set. Same prompt, datasets and judge for both models, so only the triage model differs.

**Haiku vs Opus.**
- **Accuracy:** on the held-out set, Opus got every ticket right in every run. Haiku missed:
  - login friction (h03)
  - data loss rated `medium` once (h14)
  - a too-long three-issue summary (h11)
  - the vague "can't do anything" ticket (h21)
  - the confused "supposed to be free?" ticket (h24)
- **Cost:** about 43× more per ticket: $12 vs $0.28 per 1,000 tickets, or about 1.2¢ vs 0.03¢ each.
- **Speed:** about 1.2 seconds slower.
- **Reply quality:** both pass the judge 100%, so the extra spend buys classification accuracy, not better replies.
- **Which to ship** depends on what a misrouted ticket costs. At 10,000 tickets a month, that's $3 vs $120. One urgent ticket left in a low-priority queue probably costs more than the difference. A cheaper middle ground worth testing is a cascade: Haiku for every ticket, with only low-confidence or high-stakes tickets sent to Opus.

**Judge vs human:** 18 hand-labelled outputs: 12 real Haiku outputs, all of which I passed, plus 6 handwritten bad examples, each failing one criterion. Without the bad examples, a judge that passed everything would have scored 100%.

| Judge rubric | Agreement (72 verdicts) | Disagreements | What changed |
|---|---|---|---|
| `judge/v1` | 71/72 | failed "we'll look into it as a priority" (t006), which I passed | first version |
| `judge/v2` | 70/72 | fixed t006, but a new "claimed action" rule failed "we've passed this to the product team" (t016, t030), which I passed | general reassurance passes; claimed actions fail |
| `judge/v3` | **72/72** | none | v2 without the claimed-action rule. Now the default |

All three rubrics caught all 6 bad examples. The changes only moved the line between reassurance and commitment. Caveat: v3 was tuned on these same 18 labels, and some criteria have only one labelled failure, so it should be re-checked on fresh labels before its scores gate CI.

### Prompt changelog

Each row pools several runs of the 30 golden tickets with Haiku 5.5. One run moves by about one ticket (3.3 points) on its own, so only differences bigger than that count.

| Version | Change | Runs | Category acc. | Priority acc. | Failures | Non-English summaries |
|---|---|---|---|---|---|---|
| `triage/v1` | First version | 4 | 95.0% | 91.7% | 2/120 | 0 |
| `triage/v2` | Lockouts are high even when recovery fails; categorise by problem, not suspected cause; wrong output with a workaround is medium; short multi-issue summaries; never ask for codes | 3 | 93.3% | 94.4% | 2/90 | **8** |
| `triage/v3` | v2, with the summary explicitly internal and always English, and "can't do X" about a feature that never existed counted as a feature request | 3 | **98.9%** | **100%** | **0/90** | 0 |

**v2 is the lesson.** It fixed the four tickets it targeted, but it introduced two regressions:
- **Summaries in the customer's language.** Spanish, French and Japanese every run. Accuracy couldn't show it, and two Japanese summaries also failed validation by running to two sentences. The eval now checks summary language in code.
- **t022 became `bug/medium`.** "You STILL can't import a CSV" got read as a broken feature, because of v2's new medium rule.

**Judge scores** (judge `v3`, one run each): v1 and v3 both pass 100% on all four criteria. The prompt changes didn't hurt reply quality, but the judge is at its ceiling on this dataset, so it can't tell the two apart.

### Held-out check

v2 and v3 were written by looking at misses on the golden set, so their golden scores are flattering. To check them, I wrote a separate [held-out set](data/holdout.jsonl) of 25 tickets after v3 was final and labelled them before running anything:
- 15 hard cases I drafted
- 5 clear ones
- 4 messy ones written by hand: vague, typos, sarcasm, confusion
- 1 polite ticket about a likely account takeover

Each prompt ran 3 times on it (`triage eval --dataset data/holdout.jsonl`):

| Version | Category acc. | Priority acc. | Failures |
|---|---|---|---|
| `triage/v1` | 90.7% | 70.7% | 4/75 |
| `triage/v3` | **94.7%** | **86.7%** | 1/75 |

- **The improvement is real.** Priority went up 16 points on tickets that played no part in tuning, far beyond the run-to-run noise of about 4 points on 25 tickets.
- **v3 is weaker than its golden score suggests,** 86.7% vs 100% on priority. Part of that gap is a harder set, and part is fitting to the golden tickets. The held-out numbers are the honest ones.
- **Remaining weaknesses:**
  - login friction rated `low` instead of `medium` (h03)
  - data loss rated `medium` once (h14)
  - an over-long summary for a three-issue ticket (h11)
- **h24 got worse.** It's a confused ticket that v3 reads as a lockout and v1 read as billing. Its label is genuinely ambiguous.

These tickets have now been seen. Before the next prompt change, they should join the golden set and a fresh held-out set should be written.

## What I learned / known failure modes

### What I learned

#### The golden set is a working set, not a benchmark

The 30-ticket golden set is what I iterate against. I study its misses, CI gates every PR on it, and its slices (angry, non-English, injection) show where the system is weak. Once a prompt has been tuned against it, its score stops being an honest estimate of performance on new tickets. That isn't a flaw. It's the reason a separate held-out set exists.

- **It only works if both the labels and the set are fixed.** Every label is a reviewed decision. The borderline rules are written down ("categorise by the problem, not its suspected cause"), so labels stay consistent as the set grows. Labels change only when I decide a label was wrong, never to match the model.
- **Fixed answers where they exist, a rubric where they don't.** Category and priority are scored by exact match in code. Summaries and replies have many acceptable versions, so a judge grades those.
- **Accuracy can hide a regression.** `triage/v2` fixed the four problems I targeted and kept accuracy high, but it started writing summaries in the customer's language on every non-English ticket. Nothing measured that, so the scores showed nothing. Every written requirement now has a code check, and summary language is a CI gate. Re-scoring the stored runs confirms it would have blocked v2.
- **One run is roughly ±1 ticket of noise.** With no temperature setting, outputs vary between runs. Repeating runs separated systematic misses (t026: wrong in 4 of 4 runs) from coin flips (t005 and t025 moving between `low` and `medium`). I only act on differences clearly larger than that noise, and the CI thresholds leave the same margin. They catch real regressions without failing at random.
- **Growing it safely.** The plan is to merge the held-out tickets into a versioned golden v2:
  - each ticket tagged with where it came from
  - added as a whole batch, never hand-picked
  - with genuinely ambiguous tickets left out

  Scores are only compared within the same version of the dataset.

#### The held-out set gives the honest number

v2 and v3 were written by studying v1's misses on the golden set. A better golden score after that can't tell "the rules generalise" apart from "the rules fit these 30 tickets". So I built a 25-ticket held-out set after v3 was final, labelled it before running anything, and ran it once.

| `triage/v3` priority accuracy | Golden set (tuned on) | Held-out set (unseen) |
|---|---|---|
| Haiku 5.5 | 100% | **86.7%** |

- **The improvement was real:** +16 points over v1 on tickets that played no part in tuning, far beyond the noise.
- **The golden number was about 13 points too optimistic.** Without the held-out set, I'd have reported it.
- **Size it for the difference you want to detect.** At 10 tickets, each ticket is worth 10 points, and the v1-vs-v3 gap would have been under one ticket. So I used 25, weighted toward the hard cases where the versions were expected to differ.
- **Vary who writes it.** The tickets I wrote with deliberately messy, realistic phrasing (vague, misspelled, sarcastic) were among the hardest for the model and to label. Synthetic data written by the person who writes the prompt shares that person's blind spots.
- **Using it spends it.** Once its misses inform a change, it's part of tuning. The next prompt version needs a fresh one.

#### An LLM judge has to be calibrated against a human

The judge (Claude Sonnet 5.5) grades each summary and reply on four pass/fail criteria, giving a reason before each verdict. Binary criteria keep its verdicts comparable with mine and make agreement measurable. The judge only measures; it never changes the output.

I graded outputs by hand and measured agreement with `triage agreement`. Calibration took three rubric versions:

| Judge rubric | Agreement with my grades (72 verdicts) | What I learned |
|---|---|---|
| `judge/v1` | 71/72 | Stricter than me: it failed "we'll look into it as a priority" |
| `judge/v2` | 70/72 | My new rule failed routine replies I'd send. The rubric must encode the grader's standards, not assumptions |
| `judge/v3` | **72/72** | Reassurance and routine routing pass; promised refunds, dates or features fail |

- **Agreement on passes alone proves nothing.** All 12 real outputs passed, and a judge that passes everything would also have scored 100%. I added six deliberately broken outputs, each failing exactly one criterion. A criterion now counts as validated only after the judge has caught a failure I graded.
- **Known limit:** v3 was calibrated on the same 18 labels it's measured on, and the judge is at its ceiling on this dataset. Both Haiku and Opus pass 100%, so it can't yet tell good replies from better ones. Fresh labels and harder cases come before its scores gate CI.
- **Cost shapes where it runs.** A judge call costs about 20× a triage call, and it's about 95% of an eval run's cost. So comparisons run without it, and in production it would grade a sample of live traffic in Langfuse, not every ticket. Agents' corrections to category or reply would be the cheaper, label-quality signal.

#### Model choice is a cost decision the eval makes visible

Opus 5.5 got every held-out ticket right (100% category and priority), against Haiku's 94.7% and 86.7%. It costs about 43× more ($12 vs $0.28 per 1,000 tickets) and is 1.2 seconds slower. Both pass the judge 100%, so the extra spend buys classification accuracy, not better replies. Whether that's worth it depends on what a misrouted ticket costs, and a Haiku-first cascade that escalates uncertain tickets to Opus is the obvious thing to test next.

### Known failure modes (Haiku 5.5, `triage/v3`, held-out set)

- **Login friction rated `low`** instead of `medium`, for example having to log in again on every tab (h03, 2 of 3 runs).
- **Data loss occasionally rated `medium`** when the ticket is also angry or not in English (h14, 1 of 3).
- **Summaries for tickets with three or more issues** sometimes exceed 200 characters and fail validation (h11, 1 of 3).
- **Vague or confused tickets** get a confident answer that may not match the label, for example "can't do anything" or "I thought this was supposed to be free?" (h21, h24). These are genuinely ambiguous: Opus matched my labels, Haiku didn't.
- **The judge is at its ceiling.** Both models pass 100% on this dataset, so it can't currently tell a good reply from a better one. It needs harder cases.

### What I'd do next

1. **Grow the golden set.** Move the 25 held-out tickets into the golden set (a versioned golden v2, with each ticket tagged by where it came from), then write a fresh held-out set before any more prompt changes.
2. **Write `triage/v4`** for the failure modes above, and confirm it on the new held-out set.
3. **Try a cascade:** Haiku for every ticket, with uncertain or high-stakes ones sent to Opus. That needs a confidence signal first.
4. **Re-check the judge on fresh hand labels**, including harder replies, before its scores can fail the build.
5. **Production monitoring:** in production there are no labels, so the signals would be the judge running on a sample of live traces in Langfuse, plus agents' corrections to the category and the reply, recorded as scores.
