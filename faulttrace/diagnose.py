"""Root-cause ranking, simulation-based verification and a rule-based baseline."""
import math
import random

from .model import P_DTC_RAISED, P_SPURIOUS, Vehicle, propagate

EPS = 1e-3
GAP_MS = 500


def triage(v: Vehicle, events: list) -> dict:
    """Group events into bursts (gap > 500 ms starts a new burst) and keep the largest."""
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


def rank_causes(v: Vehicle, burst_codes: set) -> list:
    """Score every component as the root cause with a Bernoulli likelihood of the observed
    code set, using simulated propagation (explains silent root causes too)."""
    scores = []
    for root in v.components:
        freq = v.affected_frequency(root)
        ll = 0.0
        for code, comp in v.dtc_component.items():
            p = freq[comp] * P_DTC_RAISED + (1 - freq[comp] * P_DTC_RAISED) * P_SPURIOUS
            ll += math.log(p + EPS) if code in burst_codes else math.log(1 - p + EPS)
        scores.append((root, ll))
    scores.sort(key=lambda s: -s[1])
    top = scores[0][1]
    weights = [math.exp(ll - top) for _, ll in scores]
    z = sum(weights)
    return [{"component": r, "log_likelihood": round(ll, 2), "probability": round(w / z, 3)}
            for (r, ll), w in zip(scores, weights)]


def verify(v: Vehicle, root: str, burst_codes: set, runs: int = 200, threshold: float = 0.6) -> dict:
    """Re-simulate the candidate fault with fresh seeds and compare the predicted code set
    (codes raised in at least half of the runs) with what was observed (Jaccard overlap)."""
    rng = random.Random(f"verify:{v.name}:{root}")
    counts = {}
    for _ in range(runs):
        for comp in propagate(v, root, rng):
            for code in v.component_dtcs.get(comp, []):
                counts[code] = counts.get(code, 0) + P_DTC_RAISED
    predicted = {c for c, n in counts.items() if n / runs >= 0.5}
    union = predicted | burst_codes
    jac = len(predicted & burst_codes) / len(union) if union else 0.0
    return {"component": root, "jaccard": round(jac, 3), "accepted": jac >= threshold,
            "missing_from_observation": sorted(predicted - burst_codes),
            "unexplained_by_candidate": sorted(burst_codes - predicted)}


def baseline_earliest_code(v: Vehicle, events: list):
    """Rule-based baseline: blame the component of the earliest logged code."""
    known = [(c, t) for c, t in events if c in v.dtc_component]
    return v.dtc_component[min(known, key=lambda e: e[1])[0]] if known else None
