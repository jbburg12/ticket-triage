## Eval: `claude-haiku-5-5`, prompt `v3`
25 tickets from `holdout` × 3 repeat(s) · judge: `off` · run `20261127T182035Z-claude-haiku-5-5-v3-holdout`

### Gates (scored by code)
| gate | actual | required |  |
|---|---|---|---|
| category accuracy | 0.95 | >= 0.85 | ✅ |
| priority accuracy | 0.87 | >= 0.70 | ✅ |
| failure rate | 0.01 | <= 0.05 | ✅ |
| injection check | 3/3 | all pass | ✅ |

### Classification
| metric | value | range across repeats |
|---|---|---|
| category accuracy | 95% | 92% – 96% |
| priority accuracy | 87% | 84% – 88% |
| failure rate | 1% |  |

Failures: schema_violation ×1

#### Category confusion matrix
| expected \ predicted | billing | login | bug | feature_request | other | (failed) |
|---|---|---|---|---|---|---|
| billing | 11 | 3 | · | · | · | 1 |
| login | · | 21 | · | · | · | · |
| bug | · | · | 21 | · | · | · |
| feature_request | · | · | · | 9 | · | · |
| other | · | · | · | · | 9 | · |

#### Priority confusion matrix
| expected \ predicted | low | medium | high | (failed) |
|---|---|---|---|---|
| low | 24 | · | · | · |
| medium | 2 | 10 | 3 | · |
| high | · | 4 | 31 | 1 |

#### Accuracy by slice
| tag | n | category | priority |
|---|---|---|---|
| ambiguous | 24 | 88% | 67% |
| angry | 3 | 100% | 67% |
| clear | 33 | 100% | 100% |
| es | 3 | 100% | 67% |
| injection | 3 | 100% | 100% |
| it | 3 | 100% | 100% |
| multi_issue | 6 | 83% | 83% |
| non_english | 9 | 100% | 89% |
| pt | 3 | 100% | 100% |

### Cost and latency
Triage $0.0207 · judge $0.0000 · triage per 1k tickets ≈ $0.28 · p50 triage latency 1.8s

### Misses
| ticket | expected | got |
|---|---|---|
| h14 | bug/high | bug/medium |
| h21 | other/high | other/medium |
| h24 | billing/medium | login/high |
| h03 | login/medium | login/low |
| h11 | billing/high | (failed) schema_violation |
| h21 | other/high | other/medium |
| h24 | billing/medium | login/high |
| h03 | login/medium | login/low |
| h21 | other/high | other/medium |
| h24 | billing/medium | login/high |
