"""Loads the generated Cypher into a real Neo4j server. Skipped unless NEO4J_URI is set, for example

    docker run -d -p 7687:7687 -e NEO4J_AUTH=none neo4j:5
    NEO4J_URI=bolt://localhost:7687 pytest tests/test_neo4j.py
"""
import os

import networkx as nx
import pytest

from faulttrace.cypher import to_cypher
from faulttrace.model import load_vehicle

URI = os.environ.get("NEO4J_URI")
pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_URI not set")


@pytest.fixture
def session():
    from neo4j import GraphDatabase
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]) if os.environ.get("NEO4J_USER") else None
    driver = GraphDatabase.driver(URI, auth=auth)
    with driver.session() as s:
        s.run("MATCH (n) WHERE n.vehicle STARTS WITH 'it_' DETACH DELETE n").consume()
        yield s
        s.run("MATCH (n) WHERE n.vehicle STARTS WITH 'it_' DETACH DELETE n").consume()
    driver.close()


def load(session, name, vehicle_label):
    for stmt in to_cypher(name).replace(f"'{name}'", f"'{vehicle_label}'").split("\n"):
        session.run(stmt).consume()


@pytest.mark.parametrize("name", ["truck", "excavator", "truck_j1939"])
def test_counts_and_reachability_match_the_python_model(session, name):
    v = load_vehicle(name)
    label = f"it_{name}"
    load(session, name, label)
    load(session, name, label)                                   # loading twice must not duplicate anything

    def count(query):
        return session.run(query, vehicle=label).single()[0]

    assert count("MATCH (n:Component {vehicle: $vehicle}) RETURN count(n)") == len(v.components)
    assert count("MATCH (:Component {vehicle: $vehicle})-[r:AFFECTS]->() RETURN count(r)") == v.graph.number_of_edges()
    assert count("MATCH (n:Dtc {vehicle: $vehicle}) RETURN count(n)") == len(v.dtc_component)
    assert count("MATCH (:Component {vehicle: $vehicle})-[r:RAISES]->() RETURN count(r)") == len(v.dtc_component)

    root = "power_dist"
    reachable = {r["id"] for r in session.run(
        "MATCH (:Component {id: $root, vehicle: $vehicle})-[:AFFECTS*1..]->(c) RETURN DISTINCT c.id AS id",
        root=root, vehicle=label)}
    assert reachable == nx.descendants(v.graph, root) - {root}

