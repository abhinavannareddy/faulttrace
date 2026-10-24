| Vehicle | Incidents | Simulation top-1 | Simulation top-3 | Earliest-code baseline | Silent-root incidents | Silent: ours / baseline |
|---|---|---|---|---|---|---|
| truck | 193 | 71.0% | 92.7% | 61.7% | 56 | 30.4% / 0.0% |
| car | 183 | 74.3% | 94.0% | 62.8% | 53 | 37.7% / 0.0% |
| bus | 190 | 77.9% | 94.2% | 60.5% | 57 | 56.1% / 0.0% |
| excavator | 188 | 78.2% | 94.1% | 57.4% | 62 | 72.6% / 0.0% |
| **all** | 754 | 75.3% | 93.8% | 60.6% | 228 | 50.0% / 0.0% |

Model mismatch (incidents generated with edge probabilities 0.6 to 1.0, diagnosed assuming 0.9; 733 incidents): top-1 67.4%, top-3 90.2%, baseline 57.8%.

LangGraph workflow (147 incidents): verified 137 (93.2%), of which correct 112 (81.8%); overall correct root cause 78.9%.
