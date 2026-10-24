"""LangGraph workflow: triage -> investigator -> verifier (loops over candidates) -> reporter."""
from typing import TypedDict

from langgraph.graph import StateGraph, END

from .diagnose import rank_causes, triage, verify
from .model import Vehicle

MAX_CANDIDATES = 3


class State(TypedDict, total=False):
    vehicle: Vehicle
    events: list
    burst: list
    ignored_codes: list
    unknown_codes: list
    ranking: list
    tried: list
    verification: dict
    accepted: str
    report: dict


def triage_agent(s: State) -> State:
    t = triage(s["vehicle"], s["events"])
    return {"burst": t["burst"], "ignored_codes": t["ignored_codes"],
            "unknown_codes": t["unknown_codes"], "tried": []}


def investigator(s: State) -> State:
    if "ranking" in s and s["ranking"]:
        return {}
    return {"ranking": rank_causes(s["vehicle"], {c for c, _ in s["burst"]})}


def verifier(s: State) -> State:
    tried = list(s["tried"])
    cand = s["ranking"][len(tried)]["component"]
    res = verify(s["vehicle"], cand, {c for c, _ in s["burst"]})
    out = {"tried": tried + [res], "verification": res}
    if res["accepted"]:
        out["accepted"] = cand
    return out


def route_after_verify(s: State) -> str:
    if s.get("accepted") or len(s["tried"]) >= MAX_CANDIDATES:
        return "reporter"
    return "investigator"


def reporter(s: State) -> State:
    ranking, tried = s["ranking"], s["tried"]
    chosen = s.get("accepted")
    best = ranking[0]
    if not s["burst"]:
        report = {"verdict": "no_data", "text": "No known diagnostic codes were found in the log."}
    elif chosen:
        entry = next(r for r in ranking if r["component"] == chosen)
        report = {"verdict": "verified", "root_cause": chosen, "probability": entry["probability"],
                  "text": (f"Most likely root cause: {chosen} (model probability {entry['probability']}). "
                           f"Re-simulating the fault reproduces the observed codes "
                           f"(overlap {s['verification']['jaccard']}).")}
    else:
        report = {"verdict": "unverified", "root_cause": best["component"], "probability": best["probability"],
                  "text": (f"No candidate passed simulation check. Best guess: {best['component']} "
                           f"(probability {best['probability']}). A technician should confirm.")}
    report.update({"codes_used": [c for c, _ in s["burst"]], "codes_ignored": s["ignored_codes"],
                   "codes_unknown": s["unknown_codes"], "alternatives": [r["component"] for r in ranking[1:4]],
                   "checks": tried})
    return {"report": report}


def build_graph():
    g = StateGraph(State)
    g.add_node("triage", triage_agent)
    g.add_node("investigator", investigator)
    g.add_node("verifier", verifier)
    g.add_node("reporter", reporter)
    g.set_entry_point("triage")
    g.add_edge("triage", "investigator")
    g.add_edge("investigator", "verifier")
    g.add_conditional_edges("verifier", route_after_verify, {"reporter": "reporter", "investigator": "verifier"})
    g.add_edge("reporter", END)
    return g.compile()


_GRAPH = None


def diagnose(vehicle: Vehicle, events: list) -> dict:
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    return _GRAPH.invoke({"vehicle": vehicle, "events": events})["report"]
