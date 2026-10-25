| Vehicle | Incidents | FaultTrace top-1 | FaultTrace top-3 | Set-cover rule | Earliest-code rule | Silent-root incidents | Silent: FaultTrace / set-cover / earliest |
|---|---|---|---|---|---|---|---|
| truck | 193 | 70.5% | 92.7% | 68.9% | 61.7% | 56 | 30.4% / 21.4% / 0.0% |
| car | 183 | 74.3% | 94.0% | 74.9% | 62.8% | 53 | 37.7% / 35.8% / 0.0% |
| bus | 190 | 77.9% | 94.2% | 76.8% | 60.5% | 57 | 56.1% / 52.6% / 0.0% |
| excavator | 188 | 78.2% | 94.1% | 75.0% | 57.4% | 62 | 72.6% / 58.1% / 0.0% |
| **all** | 754 | 75.2% | 93.8% | 73.9% | 60.6% | 228 | 50.0% / 42.5% / 0.0% |

Model mismatch (incidents generated with edge probabilities 0.6 to 1.0, diagnosed assuming 0.9; 733 incidents): top-1 67.3%, top-3 90.3%, set-cover rule 64.9%, earliest-code rule 57.8%.

Full workflow, 369 single-fault incidents. Overall the reported root cause is correct 75.3% of the time; the true cause is in the top two of the inspection plan 92.4%.

| Verdict | Share of incidents | Root cause correct |
|---|---|---|
| verified | 62.3% | 92.2% |
| ambiguous | 30.9% | 50.0% |
| unverified | 6.8% | 36.0% |

When the verdict is ambiguous, the true cause is the leader or a named rival 93.0% of the time.

Two simultaneous faults (462 single-fault and 499 double-fault incidents): the tool claimed two faults in 159 cases (94.3% of those were truly double faults, 57.2% named exactly the right pair), catching 30.1% of the double faults. Even when it did not claim a pair, its leading answer contained a true cause in 79.2% of double-fault incidents.

Fleet failure rates (1114 incidents, made-up uneven rates): top-1 80.3% with the rates configured, 72.6% with a uniform prior.
