"""LangGraph workflow: triage -> investigator -> verifier (loops over hypotheses) -> reporter."""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .diagnose import ambiguity, inspection_plan, rank_hypotheses, triage, verify
from .model import Vehicle

MAX_CANDIDATES = 3


class State(TypedDict, total=False):
    vehicle: Vehicle
    events: list
    burst: list
    ignored_codes: list
    unknown_codes: list
    hypotheses: list
    tried: list
    verification: dict
    accepted: str
    report: dict


def triage_agent(s: State) -> State:
    t = triage(s["vehicle"], s["events"])
    return {"burst": t["burst"], "ignored_codes": t["ignored_codes"],
            "unknown_codes": t["unknown_codes"], "tried": []}


def investigator(s: State) -> State:
    return {"hypotheses": rank_hypotheses(s["vehicle"], {c for c, _ in s["burst"]})}


def verifier(s: State) -> State:
    tried = list(s["tried"])
    cand = s["hypotheses"][len(tried)]
    res = verify(s["vehicle"], cand["components"], {c for c, _ in s["burst"]})
    out = {"tried": tried + [res], "verification": res}
    if res["accepted"]:
        out["accepted"] = cand
    return out


def route_after_triage(s: State) -> str:
    return "investigator" if s["burst"] else "reporter"


def route_after_verify(s: State) -> str:
    if s.get("accepted") or len(s["tried"]) >= MAX_CANDIDATES:
        return "reporter"
    return "verifier"


def _label(h: dict) -> str:
    return " + ".join(h["components"])


def _alternatives(hyps: list, lead) -> list:
    lead = lead or (hyps[0] if hyps else None)
    return [_label(h) for h in hyps if h is not lead][:3]


def reporter(s: State) -> State:
    hyps, tried, v = s.get("hypotheses", []), s["tried"], s["vehicle"]
    if not s["burst"]:
        report = {"verdict": "no_data", "text": "No known diagnostic codes were found in the log."}
    else:
        chosen = s.get("accepted")
        lead = chosen or hyps[0]
        amb = ambiguity(v, hyps)
        if chosen and not amb["ambiguous"]:
            verdict = "verified"
            text = (f"Most likely root cause: {_label(lead)} (model probability {lead['probability']}). "
                    f"Re-simulating the fault reproduces the observed codes (overlap {s['verification']['jaccard']}).")
        elif chosen:
            verdict = "ambiguous"
            rival = " or ".join(_label(r) for r in amb["rivals"][:2])
            text = (f"Leading hypothesis: {_label(lead)} (probability {lead['probability']}), but {rival} "
                    f"cannot be ruled out from the codes. Follow the inspection plan.")
        else:
            verdict = "unverified"
            text = (f"No hypothesis passed the simulation check. Best guess: {_label(lead)} "
                    f"(probability {lead['probability']}). A technician should confirm.")
        if len(lead["components"]) > 1:
            text += " The pattern fits two simultaneous faults."
        report = {"verdict": verdict, "root_cause": lead["components"][0], "root_causes": lead["components"],
                  "probability": lead["probability"], "multiple_faults": len(lead["components"]) > 1,
                  "text": text, "ambiguity": amb, "inspection_plan": inspection_plan(v, hyps)}
    report.update({"codes_used": [c for c, _ in s["burst"]], "codes_ignored": s["ignored_codes"],
                   "codes_unknown": s["unknown_codes"],
                   "alternatives": _alternatives(hyps, s.get("accepted")), "checks": tried})
    return {"report": report}


def build_graph():
    g = StateGraph(State)
    g.add_node("triage", triage_agent)
    g.add_node("investigator", investigator)
    g.add_node("verifier", verifier)
    g.add_node("reporter", reporter)
    g.set_entry_point("triage")
    g.add_conditional_edges("triage", route_after_triage, {"investigator": "investigator", "reporter": "reporter"})
    g.add_edge("investigator", "verifier")
    g.add_conditional_edges("verifier", route_after_verify, {"reporter": "reporter", "verifier": "verifier"})
    g.add_edge("reporter", END)
    return g.compile()


_GRAPH = None


def diagnose(vehicle: Vehicle, events: list) -> dict:
    global _GRAPH
    _GRAPH = _GRAPH or build_graph()
    return _GRAPH.invoke({"vehicle": vehicle, "events": events})["report"]
