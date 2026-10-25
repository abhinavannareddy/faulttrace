# Where FaultTrace goes wrong

Generated with `python tools/analyze_errors.py 400` (400 incidents per vehicle, raw output in
`results/error_analysis.txt`). Top-1 accuracy overall is about 75%. The mistakes are not random.

## Accuracy by size of the code burst

| Distinct codes in the burst | Top-1 accuracy | Incidents |
|---|---|---|
| 1 to 2 | 71.1% | 956 |
| 3 to 5 | 85.0% | 193 |
| 6 to 9 | 79.6% | 142 |
| 10 or more | 63.9% | 194 |

The pattern is not monotonic. A burst of one or two codes is ambiguous because many components could
produce it. Three to five is the sweet spot: enough evidence to separate candidates, not yet a
system-wide failure. Large bursts are hard for a different reason. They come from faults high up in
the graph (battery, alternator, power distribution, CAN backbone), and those three or four
candidates explain nearly the same set of codes. That last point is my reading of the numbers and
the graph structure, not something I tested separately.

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

For the five pairs I checked in the configs (car steering ECU and wheel speed sensors, truck fuel rail
and alternator), the true cause is a **silent component with exactly one downstream component, and
that neighbour logs a code**. The other rows follow the same pattern in the table but I did not
inspect them individually. A fault in the silent part and a fault in its neighbour produce nearly
the same observation, apart from whatever the neighbour would additionally break. The model
prefers the neighbour because it has a code of its own that the observation explains directly.

This looks like an **identifiability limit of the graph**, not a tuning problem. No ranking function
can reliably separate two hypotheses that predict the same evidence. In practice the diagnosis is
still useful, because the neighbour is next to the true cause on the technician's path, and top-3
accuracy (93.8%) shows the true cause is nearly always listed among the alternatives.

## What would help

- **A discriminating test.** Instead of one answer, return the check that would separate the top
  two candidates (for example "measure the signal between the steering ECU and the pump"). This is
  the second half of de Kleer and Williams' approach, where measurements are chosen to narrow the
  candidate set.
- **Timing.** Hop delays are 20 to 120 ms. If the neighbour's code arrives *before* any downstream
  code, a cause upstream of it is more likely. The ranking ignores timestamps today.
- **Priors.** A uniform prior treats a battery and a dashboard as equally likely to fail. Fleet
  failure rates would break many ties.
