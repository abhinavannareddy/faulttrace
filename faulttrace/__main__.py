"""Command line:  python -m faulttrace <command>

    vehicles                                  list the available vehicles
    diagnose VEHICLE CODE [CODE ...]          diagnose a set of codes
    diagnose VEHICLE --dm1-log FILE           diagnose a J1939 log (CSV lines: time_ms,hex payload)
    purge --older-than-days N                 delete stored diagnoses older than N days

A code can be written CODE or CODE@time_ms. Codes without a time are spaced 20 ms apart so that they
count as one burst. Add --json for machine-readable output.
"""
import argparse
import json
import os
import sys

from . import __version__
from .agents import diagnose
from .j1939 import events_from_frames
from .model import CONFIG_DIR, load_vehicle
from .report import format_text
from .store import Store

CODE_SPACING_MS = 20


def parse_codes(items: list) -> list:
    events = []
    for i, item in enumerate(items):
        code, sep, t = item.partition("@")
        try:
            events.append((code, float(t) if sep else 3000.0 + CODE_SPACING_MS * i))
        except ValueError:
            raise SystemExit(f"error: '{item}' is not CODE or CODE@time_ms")
    return events


def read_dm1_log(path: str) -> list:
    frames = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t, _, data = line.partition(",")
            try:
                frames.append({"time_ms": float(t), "data": data.strip()})
            except ValueError:
                raise SystemExit(f"error: {path} line {n}: expected 'time_ms,hex payload'")
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="faulttrace", description="Root-cause diagnosis from diagnostic trouble codes.")
    ap.add_argument("--version", action="version", version=f"faulttrace {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("vehicles", help="list the available vehicles")
    pg = sub.add_parser("purge", help="delete stored diagnoses older than N days (data retention)")
    pg.add_argument("--db", default=os.environ.get("FAULTTRACE_DB", "faulttrace.db"), help="database file")
    pg.add_argument("--older-than-days", type=int, required=True)
    d = sub.add_parser("diagnose", help="diagnose a set of codes or a J1939 log")
    d.add_argument("vehicle", help="vehicle name (see 'vehicles') or path to a vehicle YAML file")
    d.add_argument("codes", nargs="*", help="CODE or CODE@time_ms")
    d.add_argument("--dm1-log", metavar="FILE", help="CSV file with lines 'time_ms,hex payload' of DM1 messages")
    d.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    if args.command == "vehicles":
        print("\n".join(sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))))
        return 0

    if args.command == "purge":
        if args.older_than_days < 0:
            raise SystemExit("error: --older-than-days must not be negative")
        print(f"deleted {Store(args.db).purge_older_than(args.older_than_days)} diagnoses")
        return 0

    if bool(args.codes) == bool(args.dm1_log):
        ap.error("give either codes or --dm1-log")
    try:
        v = load_vehicle(args.vehicle)
    except FileNotFoundError:
        raise SystemExit(f"error: unknown vehicle '{args.vehicle}' (try: python -m faulttrace vehicles)")
    skipped = []
    if args.dm1_log:
        events, skipped = events_from_frames(read_dm1_log(args.dm1_log))
    else:
        events = parse_codes(args.codes)
    report = diagnose(v, events)
    if args.json:
        print(json.dumps({**report, "skipped_frames": skipped}, indent=2))
    else:
        print(format_text(report, v.name, {"id": None, "version": __version__,
                                           "config_sha": v.source_sha}), end="")
        for s in skipped:
            print(f"skipped: {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
