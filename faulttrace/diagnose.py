"""Root-cause ranking, simulation-based verification, ambiguity detection and inspection planning."""
import itertools
import math
import random

import networkx as nx

from .model import P_DTC_RAISED, P_SPURIOUS, Vehicle, propagate

EPS = 1e-3
GAP_MS = 500
PAIR_PRIOR = 0.05        # prior odds that an incident has two independent root causes rather than one
PAIR_POOL = 8            # pairs are only searched among the best single candidates
AMBIGUITY_RATIO = 0.5    # a rival within this fraction of the leader's probability makes the result ambiguous
DEFAULT_MINUTES = 30     # inspection time assumed when the config has no service data


def triage(v: Vehicle, events: list) -> dict:
    """Group events into bursts (gap > 500 ms starts a new one) and keep the largest."""
    known = [(c, t) for c, t in events if c in v.dtc_component]
    unknown = sorted({c for c, _ in events if c not in v.dtc_component})
    bursts, cur = [], []
    for e in sorted(known, key=lambda e: e[1]):
        if cur and e[1] - cur[-1][1] > GAP_MS:
            bursts.append(cur)
            cur = []
        cur.append(e)
    if cur:
        bursts.append(cur)
    best = max(bursts, key=len) if bursts else []
    ignored = [c for b in bursts if b is not best for c, _ in b]
    return {"burst": best, "ignored_codes": sorted(set(ignored)), "unknown_codes": unknown}


def _log_likelihood(v: Vehicle, affected: dict, burst_codes: set) -> float:
    """Bernoulli log-likelihood of the observed code set, given P(component affected)."""
    ll = 0.0
    for code, comp in v.dtc_component.items():
        p = affected[comp] * P_DTC_RAISED + (1 - affected[comp] * P_DTC_RAISED) * P_SPURIOUS
        ll += math.log(p + EPS) if code in burst_codes else math.log(1 - p + EPS)
    return ll


def _softmax(scores: list) -> list:
    top = max(s for _, s in scores)
    weights = [math.exp(s - top) for _, s in scores]
    z = sum(weights)
    return [w / z for w in weights]


def rank_causes(v: Vehicle, burst_codes: set) -> list:
    """Score every component as the single root cause with a Bernoulli likelihood of the observed
    code set, using simulated propagation (explains silent root causes too) and the component
    prior from the config."""
    prior = v.prior()
    scores = [(root, _log_likelihood(v, v.affected_frequency(root), burst_codes) + math.log(prior[root]))
              for root in v.components]
    scores.sort(key=lambda s: -s[1])
    return [{"component": r, "log_likelihood": round(ll, 2), "probability": round(p, 3)}
            for (r, ll), p in zip(scores, _softmax(scores))]


def rank_hypotheses(v: Vehicle, burst_codes: set, max_faults: int = 2) -> list:
    """Rank single-fault hypotheses and, when `max_faults` is 2, pairs of simultaneous faults.

    Pairs are searched only among the best `PAIR_POOL` single candidates and carry a prior penalty
    (`PAIR_PRIOR`), because two independent failures in one incident are rarer than one. Without the
    penalty a pair always fits at least as well as either member alone."""
    prior = v.prior()
    singles = rank_causes(v, burst_codes)
    scored = [((s["component"],), s["log_likelihood"]) for s in singles]
    if max_faults >= 2:
        pool = [s["component"] for s in singles[:PAIR_POOL]]
        for a, b in itertools.combinations(pool, 2):
            fa, fb = v.affected_frequency(a), v.affected_frequency(b)
            affected = {c: 1 - (1 - fa[c]) * (1 - fb[c]) for c in v.components}
            ll = _log_likelihood(v, affected, burst_codes) + math.log(prior[a] * prior[b] * PAIR_PRIOR * len(v.components))
            scored.append(((a, b), ll))
    scored.sort(key=lambda s: -s[1])
    return [{"components": list(c), "log_likelihood": round(ll, 2), "probability": round(p, 3)}
            for (c, ll), p in zip(scored, _softmax(scored))]


def verify(v: Vehicle, root, burst_codes: set, runs: int = 200, threshold: float = 0.6) -> dict:
    """Re-simulate the candidate fault(s) with fresh seeds and compare the predicted code set
    (codes raised in at least half of the runs) with what was observed (Jaccard overlap).
    `root` is a component or a list of components that fail together."""
    roots = [root] if isinstance(root, str) else list(root)
    rng = random.Random(f"verify:{v.name}:{'+'.join(roots)}")
    counts = {}
    for _ in range(runs):
        affected = set()
        for r in roots:
            affected |= set(propagate(v, r, rng))
        for comp in affected:
            for code in v.component_dtcs.get(comp, []):
                counts[code] = counts.get(code, 0) + P_DTC_RAISED
    predicted = {c for c, n in counts.items() if n / runs >= 0.5}
    union = predicted | burst_codes
    jac = len(predicted & burst_codes) / len(union) if union else 0.0
    return {"component": roots[0] if len(roots) == 1 else "+".join(roots), "jaccard": round(jac, 3),
            "accepted": jac >= threshold,
            "missing_from_observation": sorted(predicted - burst_codes),
            "unexplained_by_candidate": sorted(burst_codes - predicted)}


def ambiguity(v: Vehicle, hypotheses: list) -> dict:
    """Is the leading hypothesis clearly ahead? Returns the rivals within `AMBIGUITY_RATIO` of the
    leader's probability, and for the nearest rival a plain statement about how they relate in the graph."""
    lead = hypotheses[0]
    rivals = [h for h in hypotheses[1:] if h["probability"] >= AMBIGUITY_RATIO * lead["probability"]]
    if not rivals:
        return {"ambiguous": False, "rivals": []}
    a, b = lead["components"], rivals[0]["components"]
    note = None
    if len(a) == 1 and len(b) == 1:
        x, y = a[0], b[0]
        if y in nx.descendants(v.graph, x):
            note = (f"{x} is upstream of {y}: a fault in {x} produces the same codes as one in {y} plus whatever "
                    f"{x} breaks elsewhere, so the codes alone cannot separate them.")
        elif x in nx.descendants(v.graph, y):
            note = (f"{y} is upstream of {x}: a fault in {y} produces the same codes as one in {x} plus whatever "
                    f"{y} breaks elsewhere, so the codes alone cannot separate them.")
    return {"ambiguous": True, "rivals": [{"components": h["components"], "probability": h["probability"]} for h in rivals],
            "note": note}


def inspection_plan(v: Vehicle, hypotheses: list, limit: int = 4) -> list:
    """Components to inspect, ordered by probability per minute of work (the classic rule for
    finding a fault with the least expected effort). A component's probability is the total
    probability of the hypotheses it appears in."""
    weight = {}
    for h in hypotheses:
        for c in h["components"]:
            weight[c] = weight.get(c, 0.0) + h["probability"]
    rows = []
    for comp, p in weight.items():
        info = v.service(comp)
        minutes = info.get("minutes", DEFAULT_MINUTES)
        rows.append({"component": comp, "probability": round(p, 3), "est_minutes": minutes,
                     "action": info.get("action", "Inspect the component, its connector and wiring."),
                     "part": info.get("part")})
    rows.sort(key=lambda r: -r["probability"] / r["est_minutes"])
    return rows[:limit]


def baseline_earliest_code(v: Vehicle, events: list):
    """Rule-based baseline: blame the component of the earliest logged code."""
    known = [(c, t) for c, t in events if c in v.dtc_component]
    return v.dtc_component[min(known, key=lambda e: e[1])[0]] if known else None


def baseline_set_cover(v: Vehicle, burst_codes: set):
    """Stronger rule-based baseline: choose the component whose downstream reach covers the most
    observed codes, charging half a point for every code it would have caused but was not seen.
    This is what a careful technician does with a wiring diagram and no probabilities."""
    observed = {v.dtc_component[c] for c in burst_codes if c in v.dtc_component}
    best, best_score = None, -math.inf
    for root in v.components:
        reach = nx.descendants(v.graph, root) | {root}
        coded = {c for c in reach if c in v.component_dtcs}
        score = len(coded & observed) - 0.5 * len(coded - observed) - 0.01 * len(reach)
        if score > best_score:
            best, best_score = root, score
    return best
