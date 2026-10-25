import pytest

from faulttrace.agents import diagnose
from faulttrace.j1939 import decode_dtc, encode_dtc, events_from_frames, parse_dm1
from faulttrace.model import load_vehicle


def test_known_byte_layout():
    # SPN 3216 = 0x0C90, FMI 2, occurrence count 5
    assert encode_dtc(3216, 2, 5) == bytes([0x90, 0x0C, 0x02, 0x05])
    d = decode_dtc(bytes([0x90, 0x0C, 0x02, 0x05]))
    assert (d.spn, d.fmi, d.occurrences, d.legacy_cm) == (3216, 2, 5, False)
    assert d.code == "SPN3216-FMI2"


@pytest.mark.parametrize("spn", [0, 1, 110, 3216, 65535, 65536, 0x7FFFF])
@pytest.mark.parametrize("fmi", [0, 4, 18, 31])
def test_round_trip_including_the_three_high_spn_bits(spn, fmi):
    d = decode_dtc(encode_dtc(spn, fmi, 7))
    assert (d.spn, d.fmi, d.occurrences) == (spn, fmi, 7)


def test_conversion_method_bit_is_detected():
    assert decode_dtc(bytes([0x6E, 0x00, 0x03, 0x81])).legacy_cm


def test_encoder_rejects_values_that_do_not_fit():
    for args in [(1 << 19, 0), (0, 32), (0, 0, 128), (-1, 0)]:
        with pytest.raises(ValueError):
            encode_dtc(*args)


def test_dm1_with_several_faults_and_the_no_fault_marker():
    payload = bytes([0xFF, 0xFF]) + encode_dtc(110, 3) + encode_dtc(168, 4) + b"\xff\xff\xff\xff"
    assert [d.code for d in parse_dm1(payload)] == ["SPN110-FMI3", "SPN168-FMI4"]
    assert parse_dm1(bytes([0x00, 0xFF, 0, 0, 0, 0])) == []
    with pytest.raises(ValueError):
        parse_dm1(bytes(5))


def test_repeated_dm1_messages_keep_the_first_appearance_only():
    one = (bytes([0, 0xFF]) + encode_dtc(110, 3)).hex()
    frames = [{"time_ms": 3000, "data": one}, {"time_ms": 4000, "data": one}, {"time_ms": 5000, "data": one}]
    events, skipped = events_from_frames(frames)
    assert events == [("SPN110-FMI3", 3000)] and skipped == []


def test_bad_and_legacy_frames_are_reported_not_fatal():
    legacy = bytes([0, 0xFF, 0x6E, 0x00, 0x03, 0x81]).hex()
    frames = [{"time_ms": 1, "data": "zz"}, {"time_ms": 2, "data": "00"}, {"time_ms": 3, "data": legacy}]
    events, skipped = events_from_frames(frames)
    assert events == [] and len(skipped) == 3


def test_a_j1939_log_is_diagnosed_end_to_end():
    v = load_vehicle("truck_j1939")
    codes = [(168, 4), (639, 9), (94, 1), (157, 18), (110, 3), (521, 13)]
    frames = [{"time_ms": 3000 + 40 * i, "data": (bytes([0, 0xFF]) + encode_dtc(s, f)).hex()} for i, (s, f) in enumerate(codes)]
    events, skipped = events_from_frames(frames)
    rep = diagnose(v, events)
    assert not skipped and len(rep["codes_used"]) == len(codes) and rep["inspection_plan"]
