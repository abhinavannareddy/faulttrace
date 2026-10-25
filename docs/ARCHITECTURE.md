# How FaultTrace works

This document describes the model, the ranking maths, the verification step, how uncertainty is reported and
the reasoning behind the main design choices. The package is small (about 1,200 lines of Python), so it is meant
to be read next to `faulttrace/model.py`, `faulttrace/diagnose.py` and `faulttrace/agents.py`.

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
- Optional per component: `failure_rate` (how often it is the root cause, relative to the others, default 1)
  and `service` (repair action, minutes, part).

`load_vehicle` validates the file and rejects duplicate ids, edges or codes that refer to unknown components,
bad probabilities, duplicate codes and non-positive failure rates. It also records a hash of the file
(`source_sha`) that is stored with every diagnosis.

### Simulating a fault

`propagate(vehicle, root, rng)` is a breadth-first *independent cascade*: starting at the root, every
outgoing edge fires once with its probability, newly affected components try their own outgoing edges,
and a component can only be affected once. Each hop adds a random delay of 20 to 120 ms, which is
where the code timestamps of generated incidents come from. This is the same process that generates the
synthetic incidents used for evaluation, which is why the model-mismatch test in section 8 exists.

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
4. Add the log of the component's prior (its normalised `failure_rate`) and turn the scores into
   probabilities with a softmax. With no `failure_rate` in the config the prior is uniform.

Absent codes count as evidence too, and that is what separates close candidates. A fault in
`engine_ecu` would also take down several downstream components, so if those codes are missing the
likelihood drops.

**What the model is, honestly:** a naive-Bayes style approximation. Codes are not truly independent
given the root, because they share the same cascade. The probabilities it returns are a ranking aid, not
calibrated confidence. A reported "probability 0.729" means "this hypothesis dominates under the model",
not "73% of such incidents are power-distribution faults". An experiment that scored whole simulated code
sets instead (which captures the correlation) gained half a point, so the simplification costs little
([ERROR_ANALYSIS.md](ERROR_ANALYSIS.md)).

### Two simultaneous faults

`rank_hypotheses` adds pairs. Pairs are searched only among the best 8 single candidates, the cascades are
combined as `1 - (1 - f_a)(1 - f_b)`, and a pair carries a prior penalty (`PAIR_PRIOR = 0.05`, the prior odds
of two independent root causes against one). Without the penalty a pair fits at least as well as either member
alone and would always win. The penalty was tuned on 964 mixed incidents: at 0.05 a "two faults" claim is
right 93% of the time, at the cost of finding only about a third of double faults. It is a warning, not a
complete search.

## 3. Verification

`verify` takes a hypothesis (one component or a pair) and re-simulates it 200 times with a fresh seed. A code
is *predicted* when its expected raise rate (`0.9 * P(component affected)`) is at least 0.5. The predicted set is
compared with the observed set using Jaccard overlap, and the hypothesis is accepted at 0.6 or more. The result
also lists codes predicted but not observed, and observed but not explained. Both end up in the report.

What this step is and is not: the verifier uses the same model as the ranker, so it is a **consistency check**,
not independent confirmation. Its value is practical. A candidate can win the likelihood ranking by a small
margin yet predict a very different code set, for example an upstream component that would also have triggered
five more codes. The overlap test rejects that, the workflow moves to the next hypothesis, and the report says
which checks failed.

## 4. Ambiguity and the inspection plan

Accuracy cannot be pushed much higher, because some faults are identical in the data (a silent component with a
single downstream neighbour that has a code). So the tool reports that instead.

`ambiguity` flags the result when a rival hypothesis has at least half the leader's probability, names the
rivals, and, when two components are connected in the graph, says so: *a fault in X produces the same codes as
one in Y plus whatever X breaks elsewhere, so the codes alone cannot separate them.*

`inspection_plan` turns the hypotheses into work. Each component's weight is its total probability across the
hypotheses it appears in, and components are ordered by probability per minute of repair work (the classic rule
for finding a fault with the least expected effort), using `service.minutes` from the config, or 30 minutes when
there is none. The first two steps of the plan contain the true cause in 92.4% of synthetic incidents.

## 5. The workflow

The steps are nodes in a LangGraph `StateGraph`:

```text
triage --burst found--> investigator --> verifier --accepted, or 3 tried--> reporter
   |                                        ^  |
   |                                        +--+  rejected: next hypothesis
   +--no usable codes------------------------------------------------------> reporter
```

- **triage** groups events into bursts (a gap above 500 ms starts a new one), keeps the largest burst, and sets
  aside isolated codes and codes the vehicle does not define. Both lists appear in the report.
- **investigator** ranks single and paired hypotheses once.
- **verifier** works down the ranking, one hypothesis per pass, at most `MAX_CANDIDATES = 3`.
- **reporter** builds the verdict: `verified` (accepted and clearly ahead), `ambiguous` (accepted but a rival is
  close), `unverified` (nothing passed the check, best guess only) or `no_data`. It adds the ambiguity analysis,
  the inspection plan and the evidence.

There is no language model in the workflow, deliberately. A diagnosis tool that a company audits and a regulator
may ask about should give the same answer for the same input, and every number in the report is reproducible
from the stored input and config hash. A language model could be added later to rephrase the report; it should
not decide the verdict.

## 6. Design decisions

| Decision | Why | Cost |
|---|---|---|
| Simulate instead of solving exactly | Exact inference on a cyclic graph with noisy edges is awkward; sampling is a few lines and handles cycles | Sampling noise, kept reproducible with fixed seeds |
| One YAML file per vehicle | The code never mentions a vehicle, so adding one is a data change | The graph has to be written by hand or learned elsewhere |
| Rank on absent codes as well as present ones | Separates a high-up cause from a local one | Misleads if the log is truncated; triage keeps only one burst |
| Report ambiguity instead of forcing an answer | Some cases are identical in the data; a confident wrong answer costs a wrong part | More "check these two" results |
| Order checks by probability per minute | Matches how a workshop spends time | Needs repair times in the config; falls back to 30 minutes |
| Deterministic, no language model | Auditable and reproducible | Plain report wording |
| Fixed seeds per vehicle and root | The same input always gives the same output | Results are deterministic, not independent across calls |
| Store every diagnosis with config hash and version | Traceability and field accuracy | A database to look after ([DEPLOYMENT.md](DEPLOYMENT.md)) |
| Validate configs when loading | A typo in an edge used to create a phantom component silently | A few lines of checks |
| API serves only shipped vehicles | The vehicle name used to be read as a file path | Custom vehicles go in `config/vehicles/` |

## 7. Performance

Measured on a laptop with Python 3.13: the first diagnosis for a vehicle takes about 60 ms, because 300
simulations are run for each of its 20 candidate roots. After that the per-root results are cached and a
diagnosis takes a few milliseconds (about 12 ms through the HTTP test client, including storing the result).
The API loads each vehicle once per process so the cache survives between requests. The one-off cost is roughly
components x 300 x edges, and each request after that costs components x codes, plus a few hundred cheap
evaluations for the pairs.

## 8. How accuracy was tested, and what that does not show

`python -m faulttrace.evaluate` generates incidents with `make_incident` on the same graph and compares the
diagnosis with the known cause. It reports:

1. **Ranking accuracy** against two rule-based baselines: the earliest-code rule and a set-cover rule (the
   component whose downstream reach covers the most observed codes). FaultTrace is at 75.2% top-1 and 93.8%
   top-3; the set-cover rule is at 73.9%.
2. **Model mismatch.** Incidents are generated with edge probabilities drawn from 0.6 to 1.0 while the diagnoser
   still assumes 0.9. Top-1 drops from 75.2% to 67.3%, so accuracy degrades gradually.
3. **Verdict reliability** through the full workflow: verified 92.2% correct, ambiguous 50.0% (93.0% with the
   rivals), unverified 36.0%.
4. **Two simultaneous faults** and 5. **fleet failure rates**, described above and in the README.

All of it uses synthetic incidents from the same model family. It shows that the maths and the code agree and
that the method tolerates wrong edge weights. It says nothing about how well these graphs match real vehicles;
that is what shadow mode and `/stats` are for.

See [ERROR_ANALYSIS.md](ERROR_ANALYSIS.md) for where the diagnoser fails, the accuracy ceiling, and the
timing experiment that did not work.
