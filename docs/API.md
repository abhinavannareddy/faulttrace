# API reference

Start the service with `uvicorn faulttrace.api:create_app --factory`. Interactive documentation (generated
from the code) is served at `/docs`, and the OpenAPI schema at `/openapi.json`.

If `FAULTTRACE_API_KEY` is set, every endpoint except `/health` needs an `X-API-Key` header. A missing or
wrong key returns 401.

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness: status, version, number of vehicles. No key needed |
| `GET /vehicles` | Names of the available vehicles |
| `GET /vehicles/{name}` | Components (system, silent or not, repair data), codes and the config hash |
| `POST /diagnose` | Diagnose a list of `{code, time_ms}` events |
| `POST /diagnose/j1939` | Diagnose logged J1939 DM1 frames (`{time_ms, data}` with the payload as hex) |
| `GET /diagnoses/{id}` | A stored diagnosis with its input, report and feedback |
| `GET /diagnoses/{id}/report` | The same report as plain text, for a screen or a printout |
| `POST /diagnoses/{id}/feedback` | Record the component the technician found at fault |
| `GET /history/{vin}` | Earlier diagnoses of one vehicle, with confirmed causes |
| `GET /stats?vehicle=` | Field accuracy from feedback, overall and per verdict |

## Diagnose

```bash
curl -X POST localhost:8000/diagnose -H "content-type: application/json" -d '{
  "vehicle": "truck",
  "vin": "1HGCM82633A004352",
  "events": [{"code": "P0601", "time_ms": 3000}, {"code": "P0202", "time_ms": 3050},
             {"code": "X9999", "time_ms": 3100}, {"code": "B1001", "time_ms": 9000}]
}'
```

`vin` is optional (17 characters, no I, O or Q). Limits: at most 500 events per request, codes up to 32
characters, `time_ms` between 0 and 1e9. Anything else returns 422.

The response (shortened):

```json
{
  "verdict": "verified | ambiguous | unverified | no_data",
  "root_cause": "engine_ecu",
  "root_causes": ["engine_ecu"],
  "multiple_faults": false,
  "probability": 0.358,
  "text": "Human-readable summary",
  "ambiguity": {"ambiguous": true, "rivals": [{"components": ["injectors"], "probability": 0.31}], "note": "..."},
  "inspection_plan": [{"component": "injectors", "probability": 0.5, "est_minutes": 35,
                       "action": "Test supply pressure and inspect lines, filter and electrical connector", "part": null}],
  "codes_used": ["P0601", "P0202"],
  "codes_ignored": ["B1001"],
  "codes_unknown": ["X9999"],
  "alternatives": ["injectors", "fuel_rail"],
  "checks": [{"component": "engine_ecu", "jaccard": 0.5, "accepted": false,
              "missing_from_observation": ["P0101"], "unexplained_by_candidate": []}],
  "trace": {"id": "uuid", "created_at": "2026-01-01T12:00:00+00:00", "version": "0.2.0", "config_sha": "570a1b9fa1fc"}
}
```

- `codes_ignored` are known codes outside the main burst (a new burst starts after a gap above 500 ms).
  `codes_unknown` are not defined for this vehicle.
- `probability` is the model's weight for the leading hypothesis, a ranking aid and not a calibrated
  confidence. A component's `probability` in the inspection plan is its total weight across all
  hypotheses it appears in, so it can exceed the leader's.
- `trace.config_sha` identifies the exact vehicle file that produced the result.

## J1939

```bash
curl -X POST localhost:8000/diagnose/j1939 -H "content-type: application/json" -d '{
  "vehicle": "truck_j1939",
  "frames": [{"time_ms": 3000, "data": "00ff6e000305"}]
}'
```

Each frame is one reassembled DM1 payload as hex. The response is the same as above plus
`skipped_frames`, which lists every frame or fault that could not be used and why. At most 2,000 frames.
See [J1939.md](J1939.md).

## Closing the loop

```bash
curl -X POST localhost:8000/diagnoses/<id>/feedback -H "content-type: application/json" \
  -d '{"confirmed_root_cause": "injectors", "technician": "A. Smith", "notes": "connector corroded"}'
curl localhost:8000/stats
```

`confirmed_root_cause` must be a component of that diagnosis's vehicle (422 otherwise). A later feedback
entry replaces the earlier one in the statistics, so a technician can correct a mistake. `/stats` returns

```json
{"diagnoses": 120, "with_feedback": 80, "root_cause_correct": 0.74, "true_cause_in_inspection_plan": 0.91,
 "by_verdict": {"verified": {"n": 50, "correct": 0.9}, "ambiguous": {"n": 24, "correct": 0.5}}}
```

(illustrative values). Comparing `by_verdict` with the lab numbers in the README is how you find out
whether the model matches your fleet.

## Errors

| Code | Meaning |
|---|---|
| 401 | `FAULTTRACE_API_KEY` is set and the header is missing or wrong |
| 404 | Unknown vehicle or diagnosis. Vehicle names are never treated as file paths |
| 422 | Validation failed: limits, VIN format, unknown component in feedback |
