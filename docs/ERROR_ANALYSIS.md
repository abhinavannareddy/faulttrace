# Where FaultTrace goes wrong

Numbers below come from `python tools/analyze_errors.py 400` (400 single-fault incidents per vehicle, raw
output in `results/error_analysis.txt`) and from two one-off experiments described at the end. Top-1
accuracy overall is about 75%, and the mistakes are not random.

## Accuracy by size of the code burst

| Distinct codes in the burst | Top-1 accuracy | Incidents |
|---|---|---|
| 1 to 2 | 71.1% | 956 |
| 3 to 5 | 85.0% | 193 |
| 6 to 9 | 79.6% | 142 |
| 10 or more | 63.9% | 194 |

The pattern is not monotonic. A burst of one or two codes is ambiguous because many components could
produce it. Three to five is the sweet spot: enough evidence to separate candidates, not yet a
system-wide failure. Large bursts come from faults high up in the graph (battery, alternator, power
distribution, CAN backbone), and those three or four candidates explain nearly the same set of codes.
That last point is my reading of the numbers and the graph structure, not something tested separately.

## The dominant error: a silent component confused with its only neighbour

The most frequent mistakes in the 400-incident run:

| Vehicle | True cause | Diagnosed as | Count |
|---|---|---|---|
| car | steering_ecu | power_steering | 23 |
| car | body_ecu | hvac | 19 |
| excavator | alternator | battery | 18 |
| car | climate_ecu | hvac | 17 |
| truck | fuel_rail | injectors | 16 |
| car | wheel_speed_sensors | abs_ecu | 16 |
| bus | alternator | battery | 15 |
| excavator | pump_controller | hydraulic_pump | 15 |
| truck | wheel_speed_sensors | abs_ecu | 14 |
| truck | alternator | battery | 14 |

For the pairs checked in the configs (car steering ECU and wheel speed sensors, truck fuel rail and
alternator, excavator pump controller), the true cause is a **silent component with exactly one
downstream component, and that neighbour logs a code**. The other rows follow the same pattern in the
table but were not inspected one by one. A fault in the silent part and a fault in its neighbour produce
nearly the same observation, apart from whatever the neighbour would additionally break, and the model
prefers the neighbour because its own code is directly explained.

This is an **identifiability limit of the graph**, not a tuning problem. No ranking function can reliably
separate two hypotheses that predict the same evidence.

## What FaultTrace does about it

Since the ranking cannot be improved here (see the ceiling below), the tool changes what it reports.
When a rival hypothesis is within half the leader's probability, the verdict is `ambiguous`, the rivals
are named, and the report says how they relate in the graph. The inspection plan then orders the checks
by probability per minute of work, using repair times from the config.

On 369 single-fault incidents through the full workflow:

| Verdict | Share | Root cause correct |
|---|---|---|
| verified | 62.3% | 92.2% |
| ambiguous | 30.9% | 50.0% |
| unverified | 6.8% | 36.0% |

In 93.0% of the ambiguous cases the true cause is the leader or a named rival, and in 92.4% of all cases it
is among the first two steps of the inspection plan. So the confusion above becomes "check these two",
which is the honest answer.

## Experiment 1: is there more accuracy to find? No.

If a better ranking existed, comparing the observation with whole simulated code sets (which captures
the correlation between codes that the independent-code likelihood ignores) should find it. Simulating
3,000 incidents per candidate root and scoring by agreement, on 1,502 test incidents:

| Method | Top-1 |
|---|---|
| Ranking used by FaultTrace | 74.4% |
| Whole-code-set comparison, kernel widths 3, 5, 8 | 74.9%, 74.8%, 74.8% |

Half a point, inside the noise of this sample size. The simple ranking is already close to the best any
method can do on incidents from this generator, which also says the remaining 25% is irreducible given
these graphs.

## Experiment 2: timestamps do not help here

Hop delays are 20 to 120 ms, so the order of codes might separate an upstream cause from a downstream
one. A timing term (simulated mean onset per component, one fitted offset because the fault start is
unknown, residuals scaled and capped) was added to the log-likelihood with a weight:

| Timing weight | Top-1 (all) | Top-1 (10+ codes) |
|---|---|---|
| 0 (not used) | 74.4% | 65.5% |
| 0.5 | 74.0% | 62.1% |
| 1 | 72.7% | 58.6% |
| 2 | 71.2% | 54.3% |
| 4 | 65.8% | 43.1% |

It made things worse at every weight, because with this much randomness in the delays and an unknown
fault start the timing mostly adds noise. The code was removed. This does not say timing can never help,
only that on this model it does not, and I changed the roadmap accordingly. Real logs may behave
differently.

## Two simultaneous faults

Tuning the penalty for claiming two faults (`PAIR_PRIOR`) on 964 mixed incidents:

| Penalty | False pair claims on single faults | Double faults named exactly | At least one true cause |
|---|---|---|---|
| 0.02 | 0.0% | 2.8% | 74.9% |
| 0.05 (used) | 1.7% | 18.7% | 79.5% |
| 0.1 | 2.6% | 19.5% | 78.9% |
| 0.3 | 8.4% | 21.5% | 78.5% |
| 1.0 | 69.7% | 27.9% | 81.9% |

Recovering the exact pair is hard because two cascades overlap and many components are silent. A pair
claim is nonetheless reliable: at 0.05, 93% of "two faults" claims were truly double faults. The feature
is therefore a high-precision warning (it finds about a third of double faults) and not a complete search.
