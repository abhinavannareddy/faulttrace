from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agents import diagnose
from .model import CONFIG_DIR, load_vehicle

app = FastAPI(title="FaultTrace")


class Event(BaseModel):
    code: str
    time_ms: float


class Request(BaseModel):
    vehicle: str
    events: list[Event]


def available_vehicles():
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))


@app.get("/vehicles")
def vehicles():
    return available_vehicles()


@app.post("/diagnose")
def diagnose_route(req: Request):
    # Only the shipped configs are served; never treat client input as a file path.
    if req.vehicle not in available_vehicles():
        raise HTTPException(404, "unknown vehicle")
    v = load_vehicle(req.vehicle)
    return diagnose(v, [(e.code, e.time_ms) for e in req.events])
