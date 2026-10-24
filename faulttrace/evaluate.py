"""Evaluation on synthetic incidents: simulation-based diagnosis versus an earliest-code baseline."""
import json
import random
import sys
from pathlib import Path

from .agents import diagnose
from .diagnose import baseline_earliest_code, rank_causes, triage
from .model import load_vehicle, make_incident

VEHICLES = ["truck", "car", "bus", "excavator"]


def perturbed(v, rng, lo=0.6, hi=1.0):
    """Copy of the vehicle whose edge probabilities differ from what the diagnoser assumes."""
    import copy
    w = copy.deepcopy(v)
    w._cache = {}
    for a, b in w.graph.edges:
        w.graph[a][b]["p"] = rng.uniform(lo, hi)
    return w


def run(n_per_vehicle: int = 200, seed: int = 11, mismatch: bool = False):
    out = {}
    for name in VEHICLES:
        v = load_vehicle(name)
        rng = random.Random(f"{seed}:{name}")
        roots = v.components
        truth = perturbed(v, rng) if mismatch else v
        stats = dict(n=0, top1=0, top3=0, base=0, silent_n=0, silent_top1=0, silent_base=0,
                     accepted=0, accepted_correct=0)
        for _ in range(n_per_vehicle):
            root = rng.choice(roots)
            events = make_incident(truth, root, rng)
            if not events:
                continue
            burst = {c for c, _ in triage(v, events)["burst"]}
            ranking = rank_causes(v, burst)
            silent = root not in v.component_dtcs
            stats["n"] += 1
            stats["top1"] += ranking[0]["component"] == root
            stats["top3"] += root in [r["component"] for r in ranking[:3]]
            stats["base"] += baseline_earliest_code(v, events) == root
            if silent:
                stats["silent_n"] += 1
                stats["silent_top1"] += ranking[0]["component"] == root
                stats["silent_base"] += baseline_earliest_code(v, events) == root
        out[name] = stats
    return out


def run_agent_check(n: int = 40, seed: int = 5):
    """Runs the full LangGraph workflow and measures verifier behaviour."""
    res = {}
    for name in VEHICLES:
        v = load_vehicle(name)
        rng = random.Random(f"agent:{seed}:{name}")
        st = dict(n=0, accepted=0, accepted_correct=0, correct=0)
        for _ in range(n):
            root = rng.choice(v.components)
            events = make_incident(v, root, rng)
            if not events:
                continue
            rep = diagnose(v, events)
            st["n"] += 1
            st["correct"] += rep.get("root_cause") == root
            if rep["verdict"] == "verified":
                st["accepted"] += 1
                st["accepted_correct"] += rep["root_cause"] == root
        res[name] = st
    return res


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    ev = run(n)
    mm = run(n, mismatch=True)
    ag = run_agent_check()
    lines = ["| Vehicle | Incidents | Simulation top-1 | Simulation top-3 | Earliest-code baseline | Silent-root incidents | Silent: ours / baseline |",
             "|---|---|---|---|---|---|---|"]
    tot = dict(n=0, top1=0, top3=0, base=0, silent_n=0, silent_top1=0, silent_base=0)
    for name, s in ev.items():
        for k in tot:
            tot[k] += s[k]
        lines.append(f"| {name} | {s['n']} | {pct(s['top1'], s['n'])}% | {pct(s['top3'], s['n'])}% | "
                     f"{pct(s['base'], s['n'])}% | {s['silent_n']} | {pct(s['silent_top1'], s['silent_n'])}% / {pct(s['silent_base'], s['silent_n'])}% |")
    s = tot
    lines.append(f"| **all** | {s['n']} | {pct(s['top1'], s['n'])}% | {pct(s['top3'], s['n'])}% | {pct(s['base'], s['n'])}% | "
                 f"{s['silent_n']} | {pct(s['silent_top1'], s['silent_n'])}% / {pct(s['silent_base'], s['silent_n'])}% |")
    m = {k: sum(x[k] for x in mm.values()) for k in ("n", "top1", "top3", "base")}
    lines.append("")
    lines.append(f"Model mismatch (incidents generated with edge probabilities 0.6 to 1.0, diagnosed assuming 0.9; {m['n']} incidents): "
                 f"top-1 {pct(m['top1'], m['n'])}%, top-3 {pct(m['top3'], m['n'])}%, baseline {pct(m['base'], m['n'])}%.")
    a = {k: sum(x[k] for x in ag.values()) for k in ("n", "accepted", "accepted_correct", "correct")}
    lines.append("")
    lines.append(f"LangGraph workflow ({a['n']} incidents): verified {a['accepted']} "
                 f"({pct(a['accepted'], a['n'])}%), of which correct {a['accepted_correct']} ({pct(a['accepted_correct'], a['accepted'])}%); "
                 f"overall correct root cause {pct(a['correct'], a['n'])}%.")
    text = "\n".join(lines)
    print(text)
    Path("results").mkdir(exist_ok=True)
    Path("results/latest.md").write_text(text + "\n")
    Path("results/latest.json").write_text(json.dumps({"per_vehicle": ev, "agent": ag}, indent=2))


if __name__ == "__main__":
    main()
