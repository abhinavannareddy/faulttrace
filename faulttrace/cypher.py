"""Prints Cypher statements that load a vehicle model into Neo4j.

Loading is idempotent (every statement uses MERGE), so running it twice does not duplicate anything.
The integration test in tests/test_neo4j.py loads each statement into a real Neo4j server and checks
the counts and a reachability query against the in-memory graph; it runs when NEO4J_URI is set.
"""
import sys

from .model import CONFIG_DIR, load_vehicle


def q(value) -> str:
    """A Cypher string literal."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def to_cypher(name: str) -> str:
    v = load_vehicle(name)
    vehicle = q(v.name)
    lines = []
    for n, d in v.graph.nodes(data=True):
        lines.append(f"MERGE (:Component {{id: {q(n)}, vehicle: {vehicle}, system: {q(d['system'])}, "
                     f"failure_rate: {d['failure_rate']}}});")
    for a, b, d in v.graph.edges(data=True):
        lines.append(f"MATCH (a:Component {{id: {q(a)}, vehicle: {vehicle}}}), (b:Component {{id: {q(b)}, vehicle: {vehicle}}}) "
                     f"MERGE (a)-[:AFFECTS {{p: {d['p']}}}]->(b);")
    for code, comp in v.dtc_component.items():
        lines.append(f"MATCH (c:Component {{id: {q(comp)}, vehicle: {vehicle}}}) "
                     f"MERGE (c)-[:RAISES]->(:Dtc {{code: {q(code)}, vehicle: {vehicle}}});")
    return "\n".join(lines)


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "truck"
    if name not in {p.stem for p in CONFIG_DIR.glob("*.yaml")}:
        raise SystemExit(f"unknown vehicle '{name}'")
    print(to_cypher(name))
