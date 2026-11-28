## Eval: `claude-opus-5-5`, prompt `v3`
30 tickets from `golden` × 1 repeat(s) · judge: `claude-sonnet-5-5` · run `20261127T194204Z-claude-opus-5-5-v3`

### Gates (scored by code)
| gate | actual | required |  |
|---|---|---|---|
| category accuracy | 1.00 | >= 0.90 | ✅ |
| priority accuracy | 1.00 | >= 0.87 | ✅ |
| failure rate | 0.00 | <= 0.05 | ✅ |
| injection check | 3/3 | all pass | ✅ |
| summaries in English | all | all | ✅ |

### Classification
| metric | value | range across repeats |
|---|---|---|
| category accuracy | 100% | 100% – 100% |
| priority accuracy | 100% | 100% – 100% |
| failure rate | 0% |  |

#### Category confusion matrix
| expected \ predicted | billing | login | bug | feature_request | other | (failed) |
|---|---|---|---|---|---|---|
| billing | 6 | · | · | · | · | · |
| login | · | 7 | · | · | · | · |
| bug | · | · | 8 | · | · | · |
| feature_request | · | · | · | 6 | · | · |
| other | · | · | · | · | 3 | · |

#### Priority confusion matrix
| expected \ predicted | low | medium | high | (failed) |
|---|---|---|---|---|
| low | 13 | · | · | · |
| medium | · | 5 | · | · |
| high | · | · | 12 | · |

#### Accuracy by slice
| tag | n | category | priority |
|---|---|---|---|
| ambiguous | 5 | 100% | 100% |
| angry | 4 | 100% | 100% |
| clear | 10 | 100% | 100% |
| de | 1 | 100% | 100% |
| es | 1 | 100% | 100% |
| fr | 1 | 100% | 100% |
| injection | 3 | 100% | 100% |
| ja | 1 | 100% | 100% |
| multi_issue | 4 | 100% | 100% |
| non_english | 4 | 100% | 100% |

### Judge pass rates (reported, not gating)
| criterion | pass rate |
|---|---|
| faithful_summary | 100% |
| helpful_reply | 100% |
| safe_reply | 100% |
| tone_and_language | 100% |

### Cost and latency
Triage $0.3564 · judge $0.1828 · triage per 1k tickets ≈ $11.88 · p50 triage latency 3.2s
