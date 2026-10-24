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


@app.get("/vehicles")
def vehicles():
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))


@app.post("/diagnose")
def diagnose_route(req: Request):
    try:
        v = load_vehicle(req.vehicle)
    except FileNotFoundError:
        raise HTTPException(404, "unknown vehicle")
    return diagnose(v, [(e.code, e.time_ms) for e in req.events])
