"""Plain-text version of a diagnosis report, for a technician's screen or a printout."""


def format_text(report: dict, vehicle: str = "", trace: dict | None = None) -> str:
    title = "FaultTrace diagnosis" + (f" - {vehicle}" if vehicle else "")
    lines = [title, "=" * len(title)]
    if trace and trace.get("id"):
        lines.append(f"Case {trace['id']}  |  {trace['created_at']}  |  "
                     f"FaultTrace {trace['version']}, config {trace['config_sha']}")
    elif trace:
        lines.append(f"FaultTrace {trace['version']}, config {trace['config_sha']}")
    lines += ["", f"Verdict: {report['verdict'].upper()}", report["text"], ""]

    if report.get("codes_used"):
        lines.append(f"Codes analysed ({len(report['codes_used'])}): {', '.join(report['codes_used'])}")
    if report.get("codes_ignored"):
        lines.append(f"Set aside as unrelated (outside the main burst): {', '.join(report['codes_ignored'])}")
    if report.get("codes_unknown"):
        lines.append(f"Not defined for this vehicle: {', '.join(report['codes_unknown'])}")

    amb = report.get("ambiguity") or {}
    if amb.get("ambiguous") and amb.get("note"):
        lines += ["", "Why this is not certain:", f"  {amb['note']}"]

    plan = report.get("inspection_plan") or []
    if plan:
        lines += ["", "Inspection plan (best value per minute first):"]
        for i, step in enumerate(plan, 1):
            part = f"  [part: {step['part']}]" if step.get("part") else ""
            lines.append(f"  {i}. {step['component']}  (probability {step['probability']}, "
                         f"about {step['est_minutes']} min){part}")
            lines.append(f"     {step['action']}")

    if report.get("alternatives"):
        lines += ["", "Other hypotheses: " + "; ".join(report["alternatives"])]
    checks = report.get("checks") or []
    if checks:
        lines += ["", "Simulation checks:"]
        for c in checks:
            extra = []
            if c["missing_from_observation"]:
                extra.append("would also have raised " + ", ".join(c["missing_from_observation"]))
            if c["unexplained_by_candidate"]:
                extra.append("does not explain " + ", ".join(c["unexplained_by_candidate"]))
            verdict = "accepted" if c["accepted"] else "rejected"
            lines.append(f"  {c['component']}: overlap {c['jaccard']} -> {verdict}"
                         + (f" ({'; '.join(extra)})" if extra else ""))
    return "\n".join(lines) + "\n"
