## Eval: `claude-haiku-5-5`, prompt `v1`
30 tickets × 3 repeat(s) · judge: `off` · run `20261127T052703Z-claude-haiku-5-5-v1`

### Gates (scored by code)
| gate | actual | required |  |
|---|---|---|---|
| category accuracy | 0.96 | >= 0.85 | ✅ |
| priority accuracy | 0.92 | >= 0.70 | ✅ |
| failure rate | 0.01 | <= 0.05 | ✅ |
| injection check | 9/9 | all pass | ✅ |

### Classification
| metric | value | range across repeats |
|---|---|---|
| category accuracy | 96% | 93% – 97% |
| priority accuracy | 92% | 90% – 93% |
| failure rate | 1% |  |

Failures: schema_violation ×1

#### Category confusion matrix
| expected \ predicted | billing | login | bug | feature_request | other | (failed) |
|---|---|---|---|---|---|---|
| billing | 18 | · | · | · | · | · |
| login | 3 | 17 | · | · | · | 1 |
| bug | · | · | 24 | · | · | · |
| feature_request | · | · | · | 18 | · | · |
| other | · | · | · | · | 9 | · |

#### Priority confusion matrix
| expected \ predicted | low | medium | high | (failed) |
|---|---|---|---|---|
| low | 39 | · | · | · |
| medium | 2 | 13 | · | · |
| high | · | 4 | 31 | 1 |

#### Accuracy by slice
| tag | n | category | priority |
|---|---|---|---|
| ambiguous | 15 | 80% | 100% |
| angry | 12 | 100% | 100% |
| clear | 30 | 100% | 97% |
| de | 3 | 100% | 67% |
| es | 3 | 100% | 100% |
| fr | 3 | 100% | 100% |
| injection | 9 | 100% | 100% |
| ja | 3 | 100% | 0% |
| multi_issue | 12 | 92% | 83% |
| non_english | 12 | 100% | 67% |

### Cost and latency
Triage $0.0205 · judge $0.0000 · triage per 1k tickets ≈ $0.23 · p50 triage latency 1.8s

### Misses
| ticket | expected | got |
|---|---|---|
| t005 | bug/medium | bug/low |
| t011 | login/high | billing/high |
| t026 | login/high | login/medium |
| t011 | login/high | billing/high |
| t018 | login/high | (failed) schema_violation |
| t025 | bug/medium | bug/low |
| t026 | login/high | login/medium |
| t011 | login/high | billing/high |
| t018 | login/high | login/medium |
| t026 | login/high | login/medium |
