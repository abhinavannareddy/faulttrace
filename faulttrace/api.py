"""HTTP service.

Start it with:  uvicorn faulttrace.api:create_app --factory

Configuration through environment variables:
    FAULTTRACE_DB        path of the SQLite file that stores diagnoses and feedback (default faulttrace.db)
    FAULTTRACE_API_KEY   when set, every endpoint except /health requires this value in an X-API-Key header
"""
import hmac
import os
import re
from functools import cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .agents import diagnose
from .j1939 import events_from_frames
from .model import CONFIG_DIR, load_vehicle
from .report import format_text
from .store import Store

VIN = r"^[A-HJ-NPR-Z0-9]{17}$"          # 17 characters, never I, O or Q
MAX_EVENTS = 500
MAX_FRAMES = 2000


class Event(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    time_ms: float = Field(ge=0, le=1e9)


class DiagnoseRequest(BaseModel):
    vehicle: str = Field(max_length=64)
    vin: str | None = Field(default=None, pattern=VIN)
    events: list[Event] = Field(max_length=MAX_EVENTS)


class Frame(BaseModel):
    time_ms: float = Field(ge=0, le=1e9)
    data: str = Field(min_length=1, max_length=1800, description="DM1 payload as hex")


class J1939Request(BaseModel):
    vehicle: str = Field(max_length=64)
    vin: str | None = Field(default=None, pattern=VIN)
    frames: list[Frame] = Field(max_length=MAX_FRAMES)


class Feedback(BaseModel):
    confirmed_root_cause: str = Field(max_length=64, description="the component the technician found to be at fault")
    technician: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)


def available_vehicles() -> list:
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))


@cache
def _vehicle(name: str):
    """Loaded once per process so the simulation cache on the Vehicle survives between requests.
    Restart the service after editing a config."""
    return load_vehicle(name)


def get_vehicle(name: str):
    # Only the shipped configs are served; never treat client input as a file path.
    if name not in available_vehicles():
        raise HTTPException(404, "unknown vehicle")
    return _vehicle(name)


def create_app(db_path: str | None = None, api_key: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("FAULTTRACE_DB", "faulttrace.db")
    api_key = api_key if api_key is not None else os.environ.get("FAULTTRACE_API_KEY")
    store = Store(db_path)
    app = FastAPI(title="FaultTrace", version=__version__,
                  description="Root-cause diagnosis from diagnostic trouble codes, with an inspection plan.")

    def require_key(x_api_key: str | None = Header(default=None)):
        if api_key and not (x_api_key and hmac.compare_digest(x_api_key.encode(), api_key.encode())):
            raise HTTPException(401, "missing or invalid X-API-Key")

    auth = [Depends(require_key)]

    def run(v, vin, events, extra=None):
        report = diagnose(v, events)
        trace = store.save(v.name, vin, events, report, __version__, v.source_sha)
        return {**report, "trace": trace, **(extra or {})}

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "vehicles": len(available_vehicles())}

    @app.get("/vehicles", dependencies=auth)
    def vehicles():
        return available_vehicles()

    @app.get("/vehicles/{name}", dependencies=auth)
    def vehicle_detail(name: str):
        v = get_vehicle(name)
        return {"vehicle": v.name, "config_sha": v.source_sha,
                "components": [{"id": c, "system": v.graph.nodes[c]["system"], "silent": c not in v.component_dtcs,
                                "service": v.service(c)} for c in v.components],
                "codes": [{"code": code, "component": comp} for code, comp in v.dtc_component.items()]}

    @app.post("/diagnose", dependencies=auth)
    def diagnose_route(req: DiagnoseRequest):
        v = get_vehicle(req.vehicle)
        return run(v, req.vin, [(e.code, e.time_ms) for e in req.events])

    @app.post("/diagnose/j1939", dependencies=auth)
    def diagnose_j1939(req: J1939Request):
        v = get_vehicle(req.vehicle)
        events, skipped = events_from_frames([f.model_dump() for f in req.frames])
        return run(v, req.vin, events, {"skipped_frames": skipped})

    @app.get("/diagnoses/{diagnosis_id}", dependencies=auth)
    def get_diagnosis(diagnosis_id: str):
        found = store.get(diagnosis_id)
        if not found:
            raise HTTPException(404, "unknown diagnosis")
        return found

    @app.get("/diagnoses/{diagnosis_id}/report", dependencies=auth, response_class=PlainTextResponse)
    def get_report(diagnosis_id: str):
        found = store.get(diagnosis_id)
        if not found:
            raise HTTPException(404, "unknown diagnosis")
        trace = {k: found[k] for k in ("id", "created_at", "version")} | {"config_sha": found["config_sha"]}
        return format_text(found["report"], found["vehicle"], trace)

    @app.post("/diagnoses/{diagnosis_id}/feedback", dependencies=auth, status_code=201)
    def add_feedback(diagnosis_id: str, fb: Feedback):
        found = store.get(diagnosis_id)
        if not found:
            raise HTTPException(404, "unknown diagnosis")
        if fb.confirmed_root_cause not in get_vehicle(found["vehicle"]).components:
            raise HTTPException(422, f"'{fb.confirmed_root_cause}' is not a component of {found['vehicle']}")
        store.add_feedback(diagnosis_id, fb.confirmed_root_cause, fb.technician, fb.notes)
        return {"status": "recorded"}

    @app.get("/history/{vin}", dependencies=auth)
    def history(vin: str):
        if not re.fullmatch(VIN, vin):
            raise HTTPException(422, "not a valid VIN")
        return [{"id": d["id"], "created_at": d["created_at"], "vehicle": d["vehicle"],
                 "verdict": d["report"]["verdict"], "root_causes": d["report"].get("root_causes", []),
                 "confirmed": [f["confirmed_root_cause"] for f in d["feedback"]]} for d in store.history(vin)]

    @app.delete("/history/{vin}", dependencies=auth)
    def delete_history(vin: str):
        if not re.fullmatch(VIN, vin):
            raise HTTPException(422, "not a valid VIN")
        return {"deleted": store.delete_vin(vin)}

    @app.get("/stats", dependencies=auth)
    def stats(vehicle: str | None = None):
        return store.stats(vehicle)

    return app

