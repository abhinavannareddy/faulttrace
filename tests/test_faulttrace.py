import random
import re

import networkx as nx
import pytest

from faulttrace.agents import diagnose
from faulttrace.diagnose import (
    ambiguity,
    baseline_earliest_code,
    baseline_set_cover,
    inspection_plan,
    rank_causes,
    rank_hypotheses,
    triage,
    verify,
)
from faulttrace.model import CONFIG_DIR, load_vehicle, make_incident, propagate

VEHICLES = ["truck", "car", "bus", "excavator"]
ALL_VEHICLES = VEHICLES + ["truck_j1939"]


@pytest.mark.parametrize("name", ALL_VEHICLES)
def test_configs_load_and_are_consistent(name):
    v = load_vehicle(name)
    assert len(v.components) > 15
    assert set(v.dtc_component.values()) <= set(v.components)
    assert len(v.dtc_component) == len({c for c in v.dtc_component})
    pattern = r"SPN\d+-FMI\d+" if name.endswith("j1939") else r"[PCBU][0-3][0-9A-F]{3}"
    assert all(re.fullmatch(pattern, code) for code in v.dtc_component)
    assert all(v.service(c).get("minutes", 0) > 0 for c in v.components)


@pytest.mark.parametrize("edit, message", [
    (lambda d: d["edges"].append({"from": "battery", "to": "typo_part", "p": 0.9}), "unknown component 'typo_part'"),
    (lambda d: d["dtcs"].append({"code": "P9999", "component": "nope"}), "unknown component 'nope'"),
    (lambda d: d["dtcs"].append(dict(d["dtcs"][0])), "duplicate code"),
    (lambda d: d["components"].append(dict(d["components"][0])), "duplicate component"),
    (lambda d: d["edges"][0].update(p=1.5), "probability 1.5"),
])
def test_invalid_configs_are_rejected(tmp_path, edit, message):
    import yaml
    cfg = yaml.safe_load((CONFIG_DIR / "truck.yaml").read_text())
    edit(cfg)
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match=message):
        load_vehicle(str(bad))


def test_propagation_only_follows_edges():
    v = load_vehicle("truck")
    rng = random.Random(1)
    for root in v.components:
        affected = propagate(v, root, rng)
        reachable = nx.descendants(v.graph, root) | {root}
        assert set(affected) <= reachable


def test_triage_drops_isolated_codes_and_unknown_codes():
    v = load_vehicle("truck")
    codes = list(v.dtc_component)
    events = [(codes[0], 3000), (codes[1], 3100), (codes[2], 3200), (codes[5], 9000), ("X9999", 3150)]
    t = triage(v, events)
    assert [c for c, _ in t["burst"]] == codes[:3]
    assert t["ignored_codes"] == [codes[5]] and t["unknown_codes"] == ["X9999"]


def test_silent_root_cause_is_found_which_the_baseline_cannot_name():
    v = load_vehicle("truck")
    rng = random.Random(3)
    hits = base_hits = n = 0
    for _ in range(60):
        events = make_incident(v, "power_dist", rng)       # power_dist raises no code itself
        if len({c for c, _ in events}) < 3:
            continue
        n += 1
        burst = {c for c, _ in triage(v, events)["burst"]}
        hits += rank_causes(v, burst)[0]["component"] == "power_dist"
        base_hits += baseline_earliest_code(v, events) == "power_dist"
    assert n > 20 and base_hits == 0 and hits / n > 0.5


def test_verifier_accepts_true_cause_and_rejects_unrelated_one():
    v = load_vehicle("excavator")
    rng = random.Random(4)
    events = make_incident(v, "hydraulic_pump", rng)
    burst = {c for c, _ in triage(v, events)["burst"]}
    assert verify(v, "hydraulic_pump", burst)["jaccard"] > verify(v, "cab_display", burst)["jaccard"]
    assert verify(v, "cab_display", burst)["accepted"] is False


def test_workflow_returns_a_report_with_evidence():
    v = load_vehicle("bus")
    rng = random.Random(5)
    events = make_incident(v, "air_compressor", rng)
    rep = diagnose(v, events)
    assert rep["verdict"] in {"verified", "ambiguous", "unverified"}
    assert rep["codes_used"] and rep["checks"] and rep["text"]


def test_workflow_handles_empty_input():
    rep = diagnose(load_vehicle("car"), [])
    assert rep["verdict"] == "no_data"


def test_simulation_diagnosis_beats_baseline_overall():
    from faulttrace.evaluate import run
    res = run(60, seed=3)
    top1 = sum(s["top1"] for s in res.values())
    base = sum(s["base"] for s in res.values())
    assert top1 > base


def test_ambiguity_is_reported_for_a_silent_component_and_its_only_neighbour():
    v = load_vehicle("car")
    # steering_ecu has no code and one downstream component, so its fault looks like power_steering's
    burst = {"C1202"}
    hyps = rank_hypotheses(v, burst, max_faults=1)
    amb = ambiguity(v, hyps)
    assert amb["ambiguous"] and "cannot separate" in amb["note"]
    assert {"steering_ecu", "power_steering"} <= {c for h in hyps[:2] for c in h["components"]}


def test_clear_cases_are_not_ambiguous():
    v = load_vehicle("truck")                       # a leaf sensor with its own code and no silent upstream partner
    clear = 0
    for seed in range(20):
        events = make_incident(v, "coolant_sensor", random.Random(seed))
        burst = {c for c, _ in triage(v, events)["burst"]} if events else set()
        if burst:
            hyps = rank_hypotheses(v, burst)
            clear += hyps[0]["components"] == ["coolant_sensor"] and not ambiguity(v, hyps)["ambiguous"]
    assert clear >= 15


def test_two_simultaneous_faults_can_be_reported():
    v = load_vehicle("truck")
    found = 0
    for seed in range(30):
        events = make_incident(v, ["transmission", "lighting"], random.Random(seed))
        burst = {c for c, _ in triage(v, events)["burst"]}
        if burst and len(rank_hypotheses(v, burst)[0]["components"]) == 2:
            found += 1
    assert found >= 5


def test_a_single_fault_is_rarely_reported_as_two():
    v = load_vehicle("bus")
    rng = random.Random(9)
    pairs = n = 0
    for _ in range(80):
        events = make_incident(v, rng.choice(v.components), rng)
        burst = {c for c, _ in triage(v, events)["burst"]} if events else set()
        if burst:
            n += 1
            pairs += len(rank_hypotheses(v, burst)[0]["components"]) == 2
    assert pairs / n < 0.08


def test_inspection_plan_prefers_cheap_checks_when_probabilities_are_equal():
    v = load_vehicle("truck")
    hyps = [{"components": ["injectors"], "probability": 0.5}, {"components": ["coolant_sensor"], "probability": 0.5}]
    plan = inspection_plan(v, hyps)
    assert plan[0]["component"] == "coolant_sensor"          # 20 minutes against 35
    assert plan[0]["action"] and plan[0]["est_minutes"] == 20


def test_failure_rates_act_as_a_prior():
    v = load_vehicle("car")
    flat = rank_causes(v, {"C1202"})
    v.graph.nodes["power_steering"]["failure_rate"] = 20.0
    biased = rank_causes(v, {"C1202"})
    assert next(r for r in biased if r["component"] == "power_steering")["probability"] >         next(r for r in flat if r["component"] == "power_steering")["probability"]
    assert abs(sum(v.prior().values()) - 1) < 1e-9


def test_set_cover_baseline_names_a_component():
    v = load_vehicle("truck")
    events = make_incident(v, "injectors", random.Random(2))
    assert baseline_set_cover(v, {c for c, _ in triage(v, events)["burst"]}) in v.components


def test_report_contains_a_plan_and_checks_for_every_verdict():
    v = load_vehicle("car")
    rep = diagnose(v, make_incident(v, "steering_ecu", random.Random(7)))
    assert rep["verdict"] in {"ambiguous", "verified"} and rep["inspection_plan"]
    assert rep["root_causes"] and isinstance(rep["multiple_faults"], bool)


def test_cypher_string_literals_are_escaped():
    from faulttrace.cypher import q, to_cypher
    assert q("it's") == "'it" + chr(92) + "'s'"
    assert q("a" + chr(92) + "b") == "'a" + chr(92) * 2 + "b'"
    assert len(to_cypher("truck").splitlines()) == 20 + 23 + 14        # one statement per node, edge and code
