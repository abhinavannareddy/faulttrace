import json

import pytest

from faulttrace.__main__ import main, parse_codes
from faulttrace.j1939 import encode_dtc


def test_codes_without_a_time_stay_in_one_burst():
    ev = parse_codes(["P0601", "P0202@3100"])
    assert ev == [("P0601", 3000.0), ("P0202", 3100.0)]
    with pytest.raises(SystemExit):
        parse_codes(["P0601@soon"])


def test_vehicles_command(capsys):
    assert main(["vehicles"]) == 0
    assert "truck_j1939" in capsys.readouterr().out.split()


def test_diagnose_prints_a_readable_report(capsys):
    assert main(["diagnose", "truck", "P0601", "P0202"]) == 0
    out = capsys.readouterr().out
    assert "FaultTrace diagnosis - truck" in out and "Verdict:" in out and "Inspection plan" in out


def test_json_output(capsys):
    main(["diagnose", "truck", "P0601", "P0202", "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["verdict"] and rep["inspection_plan"] and rep["skipped_frames"] == []


def test_dm1_log_file(tmp_path, capsys):
    log = tmp_path / "log.csv"
    lines = ["# time_ms,payload"] + [f"{3000 + 40 * i},{(bytes([0, 0xFF]) + encode_dtc(s, f)).hex()}"
                                      for i, (s, f) in enumerate([(168, 4), (639, 9), (94, 1)])]
    log.write_text("\n".join(lines) + "\n")
    assert main(["diagnose", "truck_j1939", "--dm1-log", str(log)]) == 0
    assert "SPN168-FMI4" in capsys.readouterr().out


def test_bad_arguments_exit_with_a_message():
    with pytest.raises(SystemExit):
        main(["diagnose", "tractor", "P0601"])
    with pytest.raises(SystemExit):
        main(["diagnose", "truck"])


def test_purge_command(tmp_path, capsys):
    from faulttrace.store import Store
    db = str(tmp_path / "p.db")
    Store(db).save("truck", None, [], {"verdict": "no_data"}, "0.2.0", "x")
    assert main(["purge", "--db", db, "--older-than-days", "30"]) == 0
    assert "deleted 0" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["purge", "--db", db, "--older-than-days", "-1"])
