"""Where does the diagnoser go wrong? Breaks top-1 accuracy down by burst size and lists the most
frequent confusions. Usage:  python tools/analyze_errors.py [incidents_per_vehicle]
"""
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faulttrace.diagnose import rank_causes, triage
from faulttrace.evaluate import VEHICLES
from faulttrace.model import load_vehicle, make_incident


def main(n=400, seed=21):
    by_size, confusions, per_vehicle = {}, Counter(), {}
    for name in VEHICLES:
        v = load_vehicle(name)
        rng = random.Random(f"{seed}:{name}")
        info = {"components": len(v.components), "edges": v.graph.number_of_edges(),
                    "codes": len(v.dtc_component), "silent": len(v.components) - len(v.component_dtcs)}
        per_vehicle[name] = info
        for _ in range(n):
            root = rng.choice(v.components)
            events = make_incident(v, root, rng)
            if not events:
                continue
            burst = {c for c, _ in triage(v, events)["burst"]}
            guess = rank_causes(v, burst)[0]["component"]
            bucket = "1-2" if len(burst) <= 2 else "3-5" if len(burst) <= 5 else "6-9" if len(burst) <= 9 else "10+"
            ok, tot = by_size.get(bucket, (0, 0))
            by_size[bucket] = (ok + (guess == root), tot + 1)
            if guess != root:
                confusions[(name, root, guess)] += 1
    print("per vehicle:", per_vehicle)
    print("\nTop-1 accuracy by number of distinct codes in the burst")
    for b in ("1-2", "3-5", "6-9", "10+"):
        ok, tot = by_size.get(b, (0, 0))
        print(f"  {b:>4} codes: {100 * ok / tot:5.1f}%  (n={tot})" if tot else f"  {b:>4} codes: no incidents")
    print("\nMost frequent mistakes (vehicle, true cause -> diagnosed as)")
    for (name, t, g), c in confusions.most_common(10):
        print(f"  {c:3d}  {name}: {t} -> {g}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
