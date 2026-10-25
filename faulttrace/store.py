"""SQLite store for diagnoses and technician feedback.

Every diagnosis is saved with its input, its full report and the software and config versions that
produced it, so a result can be reproduced and audited later. Feedback (what the technician found to be
the real cause) is what turns the tool's accuracy from a lab number into a measured field number.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnoses (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, vehicle TEXT NOT NULL, vin TEXT,
    events TEXT NOT NULL, report TEXT NOT NULL, version TEXT NOT NULL, config_sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, diagnosis_id TEXT NOT NULL REFERENCES diagnoses(id),
    confirmed_root_cause TEXT NOT NULL, technician TEXT, notes TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_by_diagnosis ON feedback(diagnosis_id);
CREATE INDEX IF NOT EXISTS diagnoses_by_vin ON diagnoses(vin);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        """A short-lived connection per operation: simple, and safe across the API's worker threads.
        Commits on success, rolls back on error, always closes."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def save(self, vehicle: str, vin, events: list, report: dict, version: str, config_sha: str) -> dict:
        trace = {"id": str(uuid.uuid4()), "created_at": _now(), "version": version, "config_sha": config_sha}
        with self._db() as db:
            db.execute("INSERT INTO diagnoses VALUES (?,?,?,?,?,?,?,?)",
                       (trace["id"], trace["created_at"], vehicle, vin, json.dumps(events), json.dumps(report),
                        version, config_sha))
        return trace

    def get(self, diagnosis_id: str):
        with self._db() as db:
            row = db.execute("SELECT * FROM diagnoses WHERE id = ?", (diagnosis_id,)).fetchone()
            if row is None:
                return None
            fb = db.execute("SELECT confirmed_root_cause, technician, notes, created_at FROM feedback "
                            "WHERE diagnosis_id = ? ORDER BY id", (diagnosis_id,)).fetchall()
        return {"id": row["id"], "created_at": row["created_at"], "vehicle": row["vehicle"], "vin": row["vin"],
                "events": json.loads(row["events"]), "report": json.loads(row["report"]),
                "version": row["version"], "config_sha": row["config_sha"], "feedback": [dict(f) for f in fb]}

    def add_feedback(self, diagnosis_id: str, confirmed_root_cause: str, technician, notes) -> None:
        with self._db() as db:
            db.execute("INSERT INTO feedback (diagnosis_id, confirmed_root_cause, technician, notes, created_at) "
                       "VALUES (?,?,?,?,?)", (diagnosis_id, confirmed_root_cause, technician, notes, _now()))

    def history(self, vin: str, limit: int = 20) -> list:
        """Earlier diagnoses for one vehicle, newest first (a repeat of the same fault is itself a finding)."""
        with self._db() as db:
            ids = [r["id"] for r in db.execute(
                "SELECT id FROM diagnoses WHERE vin = ? ORDER BY created_at DESC, rowid DESC LIMIT ?", (vin, limit))]
        return [self.get(i) for i in ids]

    def stats(self, vehicle=None) -> dict:
        """Field accuracy from technician feedback. Only the latest feedback on each diagnosis counts."""
        with self._db() as db:
            total = db.execute("SELECT COUNT(*) FROM diagnoses WHERE (? IS NULL OR vehicle = ?)",
                               (vehicle, vehicle)).fetchone()[0]
            rows = db.execute(
                "SELECT d.report, f.confirmed_root_cause FROM diagnoses d JOIN feedback f ON f.diagnosis_id = d.id "
                "WHERE (? IS NULL OR d.vehicle = ?) AND f.id = (SELECT MAX(id) FROM feedback WHERE diagnosis_id = d.id)",
                (vehicle, vehicle)).fetchall()
        by_verdict, correct, in_plan = {}, 0, 0
        for r in rows:
            rep, truth = json.loads(r["report"]), r["confirmed_root_cause"]
            ok = truth in rep.get("root_causes", [])
            correct += ok
            in_plan += truth in [p["component"] for p in rep.get("inspection_plan", [])]
            n, good = by_verdict.get(rep["verdict"], (0, 0))
            by_verdict[rep["verdict"]] = (n + 1, good + ok)
        n = len(rows)
        return {"diagnoses": total, "with_feedback": n,
                "root_cause_correct": round(correct / n, 3) if n else None,
                "true_cause_in_inspection_plan": round(in_plan / n, 3) if n else None,
                "by_verdict": {k: {"n": c, "correct": round(g / c, 3)} for k, (c, g) in by_verdict.items()}}

    def delete_vin(self, vin: str) -> int:
        """Remove every diagnosis (and its feedback) for one vehicle, for example on a deletion request."""
        with self._db() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM diagnoses WHERE vin = ?", (vin,))]
            db.executemany("DELETE FROM feedback WHERE diagnosis_id = ?", [(i,) for i in ids])
            db.executemany("DELETE FROM diagnoses WHERE id = ?", [(i,) for i in ids])
        return len(ids)

    def purge_older_than(self, days: int) -> int:
        """Retention: remove diagnoses (and their feedback) created more than `days` days ago."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._db() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM diagnoses WHERE created_at < ?", (cutoff,))]
            db.executemany("DELETE FROM feedback WHERE diagnosis_id = ?", [(i,) for i in ids])
            db.executemany("DELETE FROM diagnoses WHERE id = ?", [(i,) for i in ids])
        return len(ids)
