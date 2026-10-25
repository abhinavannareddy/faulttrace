"""Prints Cypher statements that load a vehicle model into Neo4j (not run in tests)."""
import sys

from .model import load_vehicle


def to_cypher(name: str) -> str:
    """Cypher statements for one vehicle. Names come from our own YAML files, so they are not escaped."""
    v = load_vehicle(name)
    lines = []
    for n, d in v.graph.nodes(data=True):
        lines.append(f"MERGE (:Component {{id: '{n}', vehicle: '{v.name}', system: '{d['system']}'}});")
    for a, b, d in v.graph.edges(data=True):
        lines.append(f"MATCH (a:Component {{id:'{a}', vehicle:'{v.name}'}}), (b:Component {{id:'{b}', vehicle:'{v.name}'}}) "
                     f"MERGE (a)-[:AFFECTS {{p: {d['p']}}}]->(b);")
    for code, comp in v.dtc_component.items():
        lines.append(f"MATCH (c:Component {{id:'{comp}', vehicle:'{v.name}'}}) MERGE (c)-[:RAISES]->(:Dtc {{code:'{code}', vehicle:'{v.name}'}});")
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_cypher(sys.argv[1] if len(sys.argv) > 1 else "truck"))
