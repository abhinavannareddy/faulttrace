# Background and related work

FaultTrace sits between three well-established ideas. This note says what each one is, where
FaultTrace borrows from it, and where it falls short. It is a reading guide, not a literature
review: the papers below were found through web searches, and details marked *secondary source*
should be checked against the original before being quoted.

## 1. Model-based diagnosis

The classic framing is to compare what a model of the system predicts with what is observed, and
let the differences point at the faulty parts. de Kleer and Williams' General Diagnostic Engine
(["Diagnosing Multiple Faults"](https://www.fs.isy.liu.se/Edu/Courses/DocDiagnos/CourseMaterial/deKleer_Williams_1987.pdf),
*Artificial Intelligence*, 1987) handles several simultaneous faults by tracking minimal sets of
violated assumptions. The cost is that the number of candidate fault sets grows exponentially, and
their follow-up work on
[behavioural modes](https://www.fs.isy.liu.se/Edu/Courses/DocDiagnos/CourseMaterial/sherlock.pdf)
tackles that by exploring the most probable candidates first.

*In FaultTrace:* the "simulate the candidate and compare with the observation" step in the verifier
is the same predict-and-compare idea. FaultTrace only considers a **single** root cause, which is
the main simplification relative to this line of work.

## 2. Probabilistic (Bayesian) diagnosis

A common probabilistic model has marginally independent faults, findings that are independent given
the fault, and a noisy-OR gate for how faults combine to produce a finding. Shwe (1993,
[arXiv:1303.1463](https://arxiv.org/pdf/1303.1463)) compared simple Bayes, multimembership Bayes and
noisy-OR models on medical cases and found noisy-OR closest to the gold-standard diagnoses, though
not identical to them.

For vehicles specifically, a
[Bayesian belief network for automotive electronic systems](https://www.researchgate.net/publication/228611973_Bayesian_belief_network_based_fault_diagnosis_in_automotive_electronic_systems)
targets several DTCs appearing together and reports a case study on an anti-lock brake system with
about 120 DTCs, built from warranty data and FMEA. (Found through a search listing; check the
original publication.) Bayesian networks on bond-graph models and hierarchical model-based
diagnosis ([arXiv:1302.6846](https://arxiv.org/pdf/1302.6846)) are related approaches.

*In FaultTrace:* `rank_causes` scores each component by the Bernoulli likelihood of the observed
code set, treating codes as independent given the root cause. That is a naive-Bayes style
approximation. The per-component "is affected" probabilities come from Monte Carlo simulation of
the propagation graph instead of exact inference, which keeps the code short and lets cycles in the
graph through, at the price of sampling noise. The 0.9 and 0.02 constants are assumptions, not
fitted values.

## 3. Graph-based root cause analysis

Outside cars, the same problem ("many alarms, one cause") is studied heavily in cloud systems.
Surveys of
[microservice failure diagnosis](https://arxiv.org/pdf/2407.01710) describe building a causality
graph between components and then ranking suspects, often with a random walk or PageRank
(CloudRanger, MS-Rank, AutoMAP, MicroCause). A 2024 evaluation,
["How Far Are We?"](https://arxiv.org/pdf/2408.13729), questions how well these methods hold up.
Process-industry work does something similar: Root-KGD
([arXiv:2406.13664](https://arxiv.org/pdf/2406.13664)) spreads a fault quantity from a candidate root
node along the edges of a knowledge graph.

Recent automotive papers add language models on top: a
[knowledge-graph-guided RAG approach for hardware-in-the-loop validation](https://arxiv.org/pdf/2608.11277)
uses the graph to produce evidence and the LLM to explain it, and there are
[LLM plus knowledge-graph frameworks for automotive faults](https://www.researchgate.net/publication/397034635_An_Automotive_Fault_Diagnosis_Framework_Based_on_Knowledge_Graphs_and_Large_Language_Models)
that store triples in Neo4j. I did not find a published, evaluated Neo4j-plus-agents system for
vehicle DTC diagnosis, but my searches were not exhaustive.

*In FaultTrace:* the graph plus propagation idea is the same. The ranking is a likelihood rather
than a random walk. There is no language model: the LangGraph workflow orchestrates deterministic
steps and the report is templated text.

## What the real codes look like

FaultTrace's codes are invented, but their format should be believable.

- **Passenger cars (OBD-II):** a letter for the system (P powertrain, C chassis, B body, U network)
  and four digits, for example `P0601`. The generated configs follow this format and a test checks it.
- **Heavy-duty vehicles (SAE J1939):** a fault is an SPN/FMI pair, "which signal" plus "how it failed",
  carried in the DM1 message (PGN 0xFECA, usually repeated every second) together with lamp status and
  an occurrence count. Per J1939-73 the SPN is 19 bits and the FMI 5 bits (from memory; a search did
  not confirm the bit widths, check the spec). The message identifies the reporting ECU through its
  source address. Sources: [Groundhog Apps](https://groundhogapps.com/diagnostic-trouble-codes/),
  [Proemion docs](https://docs.proemion.com/docs/parsing_definition_configuration/j1939/).
- **UDS (ISO 14229):** every DTC carries a status byte whose bits include testFailed (bit 0),
  pendingDTC (bit 2), confirmedDTC (bit 3) and warningIndicatorRequested (bit 7). Described in
  [this explainer](https://uds.readthedocs.io/en/latest/pages/knowledge_base/dtc.html); it is a
  secondary source, the standard itself was not consulted.

## Where FaultTrace stands against this literature

| Gap | Status |
|---|---|
| Single fault only | Pairs of simultaneous faults are now ranked, with a prior penalty. It finds about a third of double faults and is right 93% of the time when it claims one ([ERROR_ANALYSIS.md](ERROR_ANALYSIS.md)). Larger sets are not searched |
| Time order is ignored when ranking | Tried: a timing term made accuracy worse at every weight on this model, so it was removed. Real logs may differ |
| Edge probabilities are assumed | Still assumed (0.9). Estimating them from confirmed repairs is the first roadmap item; feedback collection is built ([DEPLOYMENT.md](DEPLOYMENT.md)) |
| Codes are on/off | Occurrence counts are decoded from J1939 but not used; UDS pending versus confirmed status is not modelled |
| Heavy-duty reporting | J1939 DM1 decoding and diagnosis are built and tested ([J1939.md](J1939.md)) |
| Choosing the next measurement (de Kleer and Williams) | Partly: ambiguous cases name the rivals and a cost-ordered inspection plan. Selecting the single most informative test is not done |
| Priors from failure history | Supported through `failure_rate` in the config; worth +7.7 points on synthetic data when the rates are right |
| Synthetic evaluation | Unchanged, and the main limitation. Shadow mode with a partner is the remedy |
| No fleet-wide learning | Not done. Patents in this area use fleet-wide history of code combinations; the diagnosis store is the starting point for it |
