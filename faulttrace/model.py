"""Vehicle fault-propagation model and simulator.

A vehicle is a directed graph: an edge A -> B with probability p means "a fault in A can make
B misbehave". Each component may own diagnostic trouble codes (DTCs). The same code runs for
a truck, car, bus or excavator, because only the YAML configuration differs.
"""
import hashlib
import random
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "vehicles"
P_DTC_RAISED = 0.90      # a faulty component raises its own code with this probability
P_SPURIOUS = 0.02        # an unrelated code appears with this probability
HOP_DELAY_MS = (20, 120)


@dataclass
class Vehicle:
    name: str
    graph: nx.DiGraph
    dtc_component: dict            # code -> component
    component_dtcs: dict           # component -> [codes]
    _cache: dict = field(default_factory=dict, repr=False)
    source_sha: str = ""           # first 12 hex digits of the config file's SHA-256, for traceability

    def prior(self) -> dict:
        """Relative chance that each component is the root cause, from the optional `failure_rate`
        field in the config (uniform when absent). Sums to 1."""
        rates = {c: self.graph.nodes[c].get("failure_rate", 1.0) for c in self.components}
        total = sum(rates.values())
        return {c: r / total for c, r in rates.items()}

    def service(self, component: str) -> dict:
        """Repair information for a component: {action, minutes, part} (any key may be missing)."""
        return self.graph.nodes[component].get("service", {})

    @property
    def components(self):
        return list(self.graph.nodes)

    def affected_frequency(self, root: str, runs: int = 300) -> dict:
        """P(component is affected | fault at root), estimated by simulation (cached)."""
        if root not in self._cache:
            rng = random.Random(f"{self.name}:{root}")
            counts = dict.fromkeys(self.components, 0)
            for _ in range(runs):
                for c in propagate(self, root, rng):
                    counts[c] += 1
            self._cache[root] = {c: n / runs for c, n in counts.items()}
        return self._cache[root]


def load_vehicle(name_or_path: str) -> Vehicle:
    path = Path(name_or_path)
    if not path.exists():
        path = CONFIG_DIR / f"{name_or_path}.yaml"
    raw = path.read_bytes()
    cfg = yaml.safe_load(raw)
    g = nx.DiGraph()
    for c in cfg["components"]:
        if c["id"] in g:
            raise ValueError(f"{path.name}: duplicate component '{c['id']}'")
        rate = c.get("failure_rate", 1.0)
        if not rate > 0:
            raise ValueError(f"{path.name}: component '{c['id']}' has failure_rate {rate}, expected > 0")
        g.add_node(c["id"], system=c["system"], failure_rate=rate, service=c.get("service", {}))
    for e in cfg["edges"]:
        for end in (e["from"], e["to"]):
            if end not in g:
                raise ValueError(f"{path.name}: edge {e['from']} -> {e['to']} uses unknown component '{end}'")
        if not 0 < e["p"] <= 1:
            raise ValueError(f"{path.name}: edge {e['from']} -> {e['to']} has probability {e['p']}, expected (0, 1]")
        g.add_edge(e["from"], e["to"], p=e["p"])
    dtc_component = {}
    for d in cfg["dtcs"]:
        if d["component"] not in g:
            raise ValueError(f"{path.name}: code {d['code']} belongs to unknown component '{d['component']}'")
        if d["code"] in dtc_component:
            raise ValueError(f"{path.name}: duplicate code '{d['code']}'")
        dtc_component[d["code"]] = d["component"]
    component_dtcs = {}
    for code, comp in dtc_component.items():
        component_dtcs.setdefault(comp, []).append(code)
    return Vehicle(cfg["vehicle"], g, dtc_component, component_dtcs, source_sha=hashlib.sha256(raw).hexdigest()[:12])


def propagate(v: Vehicle, root: str, rng: random.Random) -> dict:
    """Simulate one fault. Returns {component: onset_time_ms}."""
    onset = {root: 0.0}
    frontier = [root]
    while frontier:
        nxt = []
        for u in frontier:
            for w in v.graph.successors(u):
                if w not in onset and rng.random() < v.graph[u][w]["p"]:
                    onset[w] = onset[u] + rng.uniform(*HOP_DELAY_MS)
                    nxt.append(w)
        frontier = nxt
    return onset


def make_incident(v: Vehicle, root, rng: random.Random, window_ms: int = 10_000) -> list:
    """A burst of (code, time_ms) events as a diagnostic tool would log them, with missed
    codes and a few unrelated codes spread over the log window. `root` may be a single component
    or a list of components that fail together (each starts its own cascade at the same moment)."""
    roots = [root] if isinstance(root, str) else list(root)
    t0 = rng.uniform(2000, 4000)
    onset = {}
    for r in roots:
        for comp, t in propagate(v, r, rng).items():
            onset[comp] = min(t, onset.get(comp, t))
    events = []
    for comp, t in onset.items():
        for code in v.component_dtcs.get(comp, []):
            if rng.random() < P_DTC_RAISED:
                events.append((code, t0 + t))
    for code in v.dtc_component:
        if rng.random() < P_SPURIOUS:
            events.append((code, rng.uniform(0, window_ms)))
    return sorted(events, key=lambda e: e[1])
