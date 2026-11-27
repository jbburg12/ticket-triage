## Judge vs human: `claude-sonnet-5-5`, prompt `v3`
18 hand-labelled outputs. Small n: treat this as a sanity check.

| criterion | n | your fails | agreement | Cohen's kappa | validated |
|---|---|---|---|---|---|
| faithful_summary | 18 | 1 | 100% | 1.00 | ✅ |
| helpful_reply | 18 | 1 | 100% | 1.00 | ✅ |
| safe_reply | 18 | 2 | 100% | 1.00 | ✅ |
| tone_and_language | 18 | 2 | 100% | 1.00 | ✅ |
