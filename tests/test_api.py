import random

import pytest
from fastapi.testclient import TestClient

from faulttrace.api import create_app
from faulttrace.j1939 import encode_dtc
from faulttrace.model import load_vehicle, make_incident

VIN = "1HGCM82633A004352"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "t.db"), api_key=""))


def events_for(vehicle, root, seed=2):
    """An incident with at least three distinct codes (some random seeds log nothing at all)."""
    v = load_vehicle(vehicle)
    for offset in range(100):
        events = make_incident(v, root, random.Random(seed * 1000 + offset))
        if len({c for c, _ in events}) >= 3:
            return [{"code": c, "time_ms": t} for c, t in events]
    raise AssertionError("no usable incident")


def test_health_and_vehicle_listing(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["vehicles"] == 5
    assert set(client.get("/vehicles").json()) == {"truck", "car", "bus", "excavator", "truck_j1939"}
    d = client.get("/vehicles/truck").json()
    assert len(d["components"]) == 20 and any(c["silent"] for c in d["components"]) and d["config_sha"]
    assert client.get("/vehicles/tractor").status_code == 404


def test_diagnose_returns_a_report_and_stores_it(client):
    r = client.post("/diagnose", json={"vehicle": "truck", "vin": VIN, "events": events_for("truck", "injectors")})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] in {"verified", "ambiguous", "unverified"} and body["inspection_plan"]
    trace = body["trace"]
    assert trace["version"] and trace["config_sha"] == load_vehicle("truck").source_sha
    saved = client.get(f"/diagnoses/{trace['id']}").json()
    assert saved["vehicle"] == "truck" and saved["vin"] == VIN and saved["report"]["verdict"] == body["verdict"]
    text = client.get(f"/diagnoses/{trace['id']}/report")
    assert text.status_code == 200 and "Inspection plan" in text.text and trace["id"] in text.text


def test_an_empty_log_is_handled(client):
    r = client.post("/diagnose", json={"vehicle": "car", "events": []})
    assert r.status_code == 200 and r.json()["verdict"] == "no_data"


@pytest.mark.parametrize("name", ["tractor", "config/vehicles/truck.yaml", "requirements.txt", "../README.md"])
def test_vehicle_name_is_never_treated_as_a_file_path(client, name):
    assert client.post("/diagnose", json={"vehicle": name, "events": []}).status_code == 404


def test_input_limits(client):
    ok = {"code": "P0601", "time_ms": 3000}
    assert client.post("/diagnose", json={"vehicle": "truck", "events": [ok] * 501}).status_code == 422
    assert client.post("/diagnose", json={"vehicle": "truck", "events": [{"code": "P0601", "time_ms": -1}]}).status_code == 422
    assert client.post("/diagnose", json={"vehicle": "truck", "events": [{"code": "x" * 33, "time_ms": 1}]}).status_code == 422
    assert client.post("/diagnose", json={"vehicle": "truck", "vin": "I0QXXXXXXXXXXXXXX", "events": [ok]}).status_code == 422


def test_j1939_endpoint_decodes_dm1_frames(client):
    codes = [(168, 4), (639, 9), (94, 1), (157, 18), (110, 3)]
    frames = [{"time_ms": 3000 + 40 * i, "data": (bytes([0, 0xFF]) + encode_dtc(s, f)).hex()} for i, (s, f) in enumerate(codes)]
    frames.append({"time_ms": 9000, "data": "zz"})
    r = client.post("/diagnose/j1939", json={"vehicle": "truck_j1939", "frames": frames})
    assert r.status_code == 200
    body = r.json()
    assert len(body["codes_used"]) == 5 and len(body["skipped_frames"]) == 1


def test_feedback_updates_field_statistics(client):
    # three incidents with a known cause; the technician confirms two as correct and one as wrong
    truths = ["injectors", "coolant_sensor", "brakes"]
    ids = []
    for i, root in enumerate(truths):
        r = client.post("/diagnose", json={"vehicle": "truck", "events": events_for("truck", root, seed=i)}).json()
        ids.append((r["trace"]["id"], r["root_causes"][0]))
    assert client.get("/stats").json()["with_feedback"] == 0
    assert client.post(f"/diagnoses/{ids[0][0]}/feedback", json={"confirmed_root_cause": ids[0][1]}).status_code == 201
    assert client.post(f"/diagnoses/{ids[1][0]}/feedback", json={"confirmed_root_cause": ids[1][1], "technician": "A. Smith"}).status_code == 201
    wrong = "dashboard" if ids[2][1] != "dashboard" else "lighting"
    assert client.post(f"/diagnoses/{ids[2][0]}/feedback", json={"confirmed_root_cause": wrong, "notes": "loose connector"}).status_code == 201
    s = client.get("/stats").json()
    assert s["diagnoses"] == 3 and s["with_feedback"] == 3
    assert s["root_cause_correct"] == pytest.approx(2 / 3, abs=0.001)
    assert sum(v["n"] for v in s["by_verdict"].values()) == 3
    assert client.get("/stats", params={"vehicle": "car"}).json()["with_feedback"] == 0
    saved = client.get(f"/diagnoses/{ids[2][0]}").json()
    assert saved["feedback"][0]["confirmed_root_cause"] == wrong and saved["feedback"][0]["notes"] == "loose connector"


def test_a_correction_replaces_the_earlier_feedback_in_the_statistics(client):
    r = client.post("/diagnose", json={"vehicle": "truck", "events": events_for("truck", "injectors")}).json()
    did, guess = r["trace"]["id"], r["root_causes"][0]
    wrong = "dashboard" if guess != "dashboard" else "lighting"
    client.post(f"/diagnoses/{did}/feedback", json={"confirmed_root_cause": wrong})
    assert client.get("/stats").json()["root_cause_correct"] == 0
    client.post(f"/diagnoses/{did}/feedback", json={"confirmed_root_cause": guess})
    assert client.get("/stats").json()["root_cause_correct"] == 1


def test_feedback_validation(client):
    r = client.post("/diagnose", json={"vehicle": "truck", "events": events_for("truck", "injectors")}).json()
    did = r["trace"]["id"]
    assert client.post(f"/diagnoses/{did}/feedback", json={"confirmed_root_cause": "flux_capacitor"}).status_code == 422
    assert client.post("/diagnoses/nope/feedback", json={"confirmed_root_cause": "injectors"}).status_code == 404
    assert client.get("/diagnoses/nope").status_code == 404
    assert client.get("/diagnoses/nope/report").status_code == 404


def test_history_by_vin(client):
    for seed in (1, 2):
        client.post("/diagnose", json={"vehicle": "truck", "vin": VIN, "events": events_for("truck", "injectors", seed)})
    client.post("/diagnose", json={"vehicle": "truck", "vin": "2HGCM82633A004352", "events": events_for("truck", "brakes")})
    h = client.get(f"/history/{VIN}").json()
    assert len(h) == 2 and all(row["vehicle"] == "truck" for row in h)
    assert client.get("/history/short").status_code == 422


def test_api_key_protects_everything_except_health(tmp_path):
    c = TestClient(create_app(str(tmp_path / "k.db"), api_key="s3cret"))
    body = {"vehicle": "truck", "events": []}
    assert c.get("/health").status_code == 200
    assert c.get("/vehicles").status_code == 401
    assert c.post("/diagnose", json=body).status_code == 401
    assert c.post("/diagnose", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/diagnose", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/stats", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_deleting_a_vehicles_history_and_retention(client, tmp_path):
    client.post("/diagnose", json={"vehicle": "truck", "vin": VIN, "events": events_for("truck", "injectors", 1)})
    r = client.post("/diagnose", json={"vehicle": "truck", "vin": VIN, "events": events_for("truck", "brakes", 2)}).json()
    client.post(f"/diagnoses/{r['trace']['id']}/feedback", json={"confirmed_root_cause": "brakes"})
    other = client.post("/diagnose", json={"vehicle": "truck", "vin": "2HGCM82633A004352", "events": events_for("truck", "turbo")}).json()
    assert client.delete(f"/history/{VIN}").json() == {"deleted": 2}
    assert client.get(f"/diagnoses/{r['trace']['id']}").status_code == 404
    assert client.get(f"/diagnoses/{other['trace']['id']}").status_code == 200       # other vehicles are untouched
    assert client.get("/stats").json()["with_feedback"] == 0                         # feedback went with it
    assert client.delete("/history/short").status_code == 422


def test_retention_purge_by_age(tmp_path):
    import sqlite3

    from faulttrace.store import Store
    store = Store(str(tmp_path / "r.db"))
    old = store.save("truck", None, [], {"verdict": "no_data"}, "0.2.0", "x")
    new = store.save("truck", None, [], {"verdict": "no_data"}, "0.2.0", "x")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE diagnoses SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (old["id"],))
    assert store.purge_older_than(30) == 1
    assert store.get(old["id"]) is None and store.get(new["id"]) is not None
