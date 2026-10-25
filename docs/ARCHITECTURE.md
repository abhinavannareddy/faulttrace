# How FaultTrace works

This document describes the model, the ranking maths, the verification step and the reasoning behind
the main design choices. The package is small (about 440 lines of Python), so it is meant to be read next to
`faulttrace/model.py`, `faulttrace/diagnose.py` and `faulttrace/agents.py`.

## 1. The vehicle model

A vehicle is a directed graph of components.

- An edge `A -> B` with probability `p` means: when A is faulty, B misbehaves with probability `p`,
  independently of everything else. In the shipped configs every `p` is 0.9.
- Each component may own zero or more diagnostic trouble codes (DTCs). A component with none is
  **silent**: it fails without logging anything itself, so it can only be found through what it breaks
  downstream. Silent components are 6 or 7 of the 20 or 21 components in each shipped vehicle.
- Two constants describe the logging process (`faulttrace/model.py`): an affected component raises
  each of its codes with probability `P_DTC_RAISED = 0.90`, and any code appears by accident with
  probability `P_SPURIOUS = 0.02`.

### Simulating a fault

`propagate(vehicle, root, rng)` is a breadth-first *independent cascade*: starting at the root, every
outgoing edge fires once with its probability, newly affected components try their own outgoing edges,
and a component can only be affected once. Each hop adds a random delay of 20 to 120 ms, which is
where code timestamps come from. This is the same process that generates the synthetic incidents
used for evaluation, which is why the model-mismatch test in section 7 exists.

## 2. Ranking candidate causes

`rank_causes` answers: *for each component, how likely is the set of codes we saw, if that component
were the single root cause?*

1. For a candidate root `r`, estimate `f_r(c)`, the probability that component `c` is affected, by
   running 300 simulations (`Vehicle.affected_frequency`, cached per root and seeded by vehicle and
   root so results are reproducible).
2. The chance that a code owned by component `c` shows up is
   `q = f_r(c) * 0.90 + (1 - f_r(c) * 0.90) * 0.02`.
3. Treat codes as independent given the root. The log-likelihood of the observation is the sum over
   **all** known codes of `log(q + eps)` if the code was observed, else `log(1 - q + eps)`, with
   `eps = 1e-3` to avoid `log(0)`.
4. Turn log-likelihoods into probabilities with a softmax. The prior is uniform over components.

Absent codes count as evidence too, and that is what separates close candidates. A fault in
`engine_ecu` would also take down several downstream components, so if those codes are missing the
likelihood drops.

**What the model is, honestly:** a naive-Bayes style approximation. Codes are not truly independent
given the root, because they share the same cascade. The probabilities it returns are a ranking aid,
not calibrated confidence. A reported "probability 0.883" means "this candidate dominates under the
model", not "88% of such incidents are power-distribution faults".

## 3. Verification

`verify` takes a candidate and re-simulates it 200 times with a fresh seed. A code is *predicted*
when its expected raise rate (`0.9 * P(component affected)`) is at least 0.5. The predicted set is
compared with the observed set using Jaccard overlap, and the candidate is accepted at 0.6 or more.
The result also lists codes predicted but not observed, and observed but not explained. Both end up
in the report as evidence.

What this step is and is not: the verifier uses the same model as the ranker, so it is a
**consistency check**, not independent confirmation. Its value is practical. A candidate can win the
likelihood ranking by a small margin yet predict a very different code set, for example an upstream
component that would also have triggered five more codes. The overlap test rejects that, the
workflow moves to the next candidate, and the report says which checks failed.

## 4. The workflow

The four steps are nodes in a LangGraph `StateGraph`:

```text
triage --burst found--> investigator --> verifier --accepted, or 3 tried--> reporter
   |                                        ^  |
   |                                        +--+  rejected: next candidate
   +--no usable codes------------------------------------------------------> reporter
```

- **triage** groups events into bursts (a gap above 500 ms starts a new one), keeps the largest
  burst, and sets aside isolated codes and codes the vehicle does not define. Both lists appear in
  the report, so nothing is dropped silently.
- **investigator** runs the ranking above once.
- **verifier** works down the ranking, one candidate per pass, at most `MAX_CANDIDATES = 3`.
- **reporter** builds one of three verdicts: `verified`, `unverified` (best guess, a technician must
  confirm) or `no_data`.

There is no language model in the workflow. LangGraph is used for what it does well here: an
explicit state object, conditional edges, and a retry loop that is visible in the graph definition
instead of being buried in `while` logic.

## 5. Design decisions

| Decision | Why | Cost |
|---|---|---|
| Simulate instead of solving exactly | Exact inference on a cyclic graph with noisy edges is awkward; sampling is a few lines and handles cycles | Sampling noise, kept reproducible with fixed seeds |
| One YAML file per vehicle | The code never mentions a vehicle, so adding one is a data change | The graph has to be written by hand or learned elsewhere |
| Rank on absent codes as well as present ones | Separates a high-up cause from a local one | Misleads if the log is truncated; triage keeps only one burst |
| Fixed seeds per vehicle and root | The same input always gives the same output, which makes tests and bug reports reproducible | Results are deterministic, not independent across calls |
| Report alternatives and failed checks | A technician needs to see what else was plausible | Longer response |
| Validate configs when loading | A typo in an edge used to create a phantom component without any error | A few lines of checks in `load_vehicle` |
| API serves only the shipped vehicles | The vehicle name used to be read as a file path | Custom vehicles must be placed in `config/vehicles/` |

## 6. Performance

Measured on a laptop with Python 3.13: the first diagnosis for a vehicle takes about 60 ms, because
300 simulations are run for each of its 20 candidate roots. After that the per-root results are
cached and a diagnosis takes a few milliseconds. The API loads each vehicle once per process so the
cache survives between requests (first request about 130 ms including startup, later ones about
12 ms through the test client). The one-off cost is roughly components x 300 x edges, and each
request after that costs components x codes.

## 7. How accuracy was tested, and what that does not show

`python -m faulttrace.evaluate` picks a random root, generates an incident with `make_incident` on
the same graph, and compares the diagnosis with the known root. Three checks are reported:

1. **Baseline comparison.** The "earliest code" rule blames the component behind the first logged
   code. It can never name a silent root cause, so it scores 0% on those by construction.
2. **Model mismatch.** Incidents are generated with edge probabilities drawn from 0.6 to 1.0 while
   the diagnoser still assumes 0.9. Top-1 drops from 75.3% to 67.4% and top-3 from 93.8% to 90.2%,
   so accuracy degrades gradually rather than collapsing.
3. **Workflow check.** The verifier accepts about 93% of cases, and about 82% of the accepted
   diagnoses are correct.

All three use synthetic incidents from the same model family. They show that the maths and the code
agree and that the method tolerates wrong edge weights. They say nothing about how well these
graphs match real vehicles.

See [ERROR_ANALYSIS.md](ERROR_ANALYSIS.md) for where the diagnoser fails and why.
