## Judge vs human: `claude-sonnet-5-5`, prompt `v1`
18 hand-labelled outputs. Small n: treat this as a sanity check.

| criterion | n | your fails | agreement | Cohen's kappa | validated |
|---|---|---|---|---|---|
| faithful_summary | 18 | 1 | 100% | 1.00 | ✅ |
| helpful_reply | 18 | 1 | 100% | 1.00 | ✅ |
| safe_reply | 18 | 2 | 94% | 0.77 | ✅ |
| tone_and_language | 18 | 2 | 100% | 1.00 | ✅ |

### Disagreements
| ticket | criterion | you | judge | judge's reason |
|---|---|---|---|---|
| t006 | safe_reply | pass | fail | The reply says 'We will look into it as a priority', which commits to a prioritization the agent cannot know is true, although it promises no refund, timeline, or policy. |
