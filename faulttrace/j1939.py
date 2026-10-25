"""Decoder for J1939 DM1 messages (active diagnostic trouble codes), so heavy-duty logs can be diagnosed.

A DM1 payload is two lamp bytes followed by four bytes per active fault (SAE J1939-73):

    byte 1   SPN, bits 7..0
    byte 2   SPN, bits 15..8
    byte 3   bits 7..5 = SPN bits 18..16, bits 4..0 = FMI
    byte 4   bit 7 = conversion method (CM), bits 6..0 = occurrence count

SPN says which signal, FMI says how it failed. Only the current layout (CM = 0) is decoded; frames from
the legacy layouts are reported back as skipped because the bytes alone do not say which legacy layout
was used. The lamp bytes are ignored: they do not affect which component failed.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Dtc:
    spn: int
    fmi: int
    occurrences: int
    legacy_cm: bool

    @property
    def code(self) -> str:
        """The string used for this fault in vehicle configs, for example SPN110-FMI3."""
        return f"SPN{self.spn}-FMI{self.fmi}"


def decode_dtc(b: bytes) -> Dtc:
    if len(b) != 4:
        raise ValueError(f"a J1939 DTC is 4 bytes, got {len(b)}")
    return Dtc(spn=b[0] | b[1] << 8 | (b[2] >> 5) << 16, fmi=b[2] & 0x1F,
               occurrences=b[3] & 0x7F, legacy_cm=bool(b[3] & 0x80))


def encode_dtc(spn: int, fmi: int, occurrences: int = 1) -> bytes:
    if not 0 <= spn < 1 << 19:
        raise ValueError(f"SPN {spn} does not fit in 19 bits")
    if not 0 <= fmi < 32:
        raise ValueError(f"FMI {fmi} does not fit in 5 bits")
    if not 0 <= occurrences < 128:
        raise ValueError(f"occurrence count {occurrences} does not fit in 7 bits")
    return bytes([spn & 0xFF, (spn >> 8) & 0xFF, (spn >> 16) << 5 | fmi, occurrences])


def parse_dm1(payload: bytes) -> list:
    """All active faults in one reassembled DM1 payload. The 'no active faults' message (SPN 0, FMI 0)
    and 0xFF padding yield an empty list."""
    if len(payload) < 2 or (len(payload) - 2) % 4:
        raise ValueError(f"a DM1 payload is 2 lamp bytes plus 4 bytes per fault, got {len(payload)} bytes")
    out = []
    for i in range(2, len(payload), 4):
        raw = payload[i:i + 4]
        if raw == b"\xff\xff\xff\xff":                     # padding added to fill a transport frame
            continue
        dtc = decode_dtc(raw)
        if dtc.spn == 0 and dtc.fmi == 0:                  # "no active faults" marker
            continue
        out.append(dtc)
    return out


def events_from_frames(frames: list) -> tuple:
    """Turn logged DM1 frames into (code, time_ms) events.

    `frames` is a list of {"time_ms": float, "data": hex string}. A DM1 is repeated about once a second
    while a fault stays active, so only the first appearance of each code is kept: that is when it
    appeared, which is what the burst analysis needs. Returns (events, skipped) where `skipped` explains
    every frame or fault that could not be used."""
    seen, events, skipped = set(), [], []
    for i, f in enumerate(sorted(frames, key=lambda f: f["time_ms"])):
        try:
            faults = parse_dm1(bytes.fromhex(f["data"]))
        except ValueError as exc:
            skipped.append(f"frame {i} at {f['time_ms']} ms: {exc}")
            continue
        for d in faults:
            if d.legacy_cm:
                skipped.append(f"SPN {d.spn} FMI {d.fmi} at {f['time_ms']} ms uses a legacy conversion method")
            elif d.code not in seen:
                seen.add(d.code)
                events.append((d.code, f["time_ms"]))
    return events, skipped
