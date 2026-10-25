import random
import re

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from faulttrace.agents import diagnose
from faulttrace.diagnose import baseline_earliest_code, rank_causes, triage, verify
from faulttrace.model import CONFIG_DIR, load_vehicle, make_incident, propagate

VEHICLES = ["truck", "car", "bus", "excavator"]


@pytest.mark.parametrize("name", VEHICLES)
def test_configs_load_and_are_consistent(name):
    v = load_vehicle(name)
    assert len(v.components) > 15
    assert set(v.dtc_component.values()) <= set(v.components)
    assert len(v.dtc_component) == len({c for c in v.dtc_component})
    assert all(re.fullmatch(r"[PCBU][0-3][0-9A-F]{3}", code) for code in v.dtc_component)


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
    assert rep["verdict"] in {"verified", "unverified"}
    assert rep["codes_used"] and rep["checks"] and rep["text"]


def test_workflow_handles_empty_input():
    rep = diagnose(load_vehicle("car"), [])
    assert rep["verdict"] == "no_data"


def test_api():
    from faulttrace.api import app
    c = TestClient(app)
    assert set(c.get("/vehicles").json()) == set(VEHICLES)
    v = load_vehicle("truck")
    events = make_incident(v, "injectors", random.Random(2))
    r = c.post("/diagnose", json={"vehicle": "truck", "events": [{"code": a, "time_ms": t} for a, t in events]})
    assert r.status_code == 200 and "text" in r.json()
    assert c.post("/diagnose", json={"vehicle": "tractor", "events": []}).status_code == 404


@pytest.mark.parametrize("name", ["config/vehicles/truck.yaml", "requirements.txt", "../README.md"])
def test_api_does_not_treat_vehicle_name_as_a_file_path(name):
    from faulttrace.api import app
    r = TestClient(app).post("/diagnose", json={"vehicle": name, "events": []})
    assert r.status_code == 404


def test_simulation_diagnosis_beats_baseline_overall():
    from faulttrace.evaluate import run
    res = run(60, seed=3)
    top1 = sum(s["top1"] for s in res.values())
    base = sum(s["base"] for s in res.values())
    assert top1 > base
