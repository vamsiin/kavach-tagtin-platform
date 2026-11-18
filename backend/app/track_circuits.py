"""Provisional track circuits (QFTL, 18 Nov 2026). The SIP does not give the chainages of individual track circuits and the
team does not survey them, so the layouts mark them from a fixed method, "provisional / indicative, not surveyed":

* Home signal circuit (1AT, 29AT ...): starts about 190-200 m behind the Home signal and ends 3-5 m beyond it.
* Berthing circuit (DMT, UMT, ULT, CLT): the one circuit between the two opposite starter signals is divided into three
  parts of average length (DMAT, DMBT, DMCT).
"""
from __future__ import annotations

import re

from .domain import Element, Station, expected_line_direction

PROVISIONAL_NOTE = "Provisional / indicative (SIP method, not surveyed)"
HOME_BEFORE_M = 195.0       # 190-200 m behind the Home signal
HOME_BEYOND_M = 4.0         # 3-5 m beyond it
BERTHING_PREFIX = {"DN MAIN": "DM", "UP MAIN": "UM", "UP LOOP": "UL", "COMMON LOOP": "CL", "DN LOOP": "DL"}


def _sign(e: Element, station: Station, line_type: str | None) -> int:
    """+1 when the signal faces higher chainage (Nominal), -1 for Reverse."""
    d = (e.direction or "").strip().capitalize()
    dn = getattr(station, "dn_direction", "Nominal")
    if d in ("Down", "Up"):
        d = dn if d == "Down" else ("Reverse" if dn == "Nominal" else "Nominal")
    if d not in ("Nominal", "Reverse"):
        d = expected_line_direction(line_type, dn) or "Nominal"
        if d == "Both":
            d = "Nominal"
    return 1 if d == "Nominal" else -1


def home_signal_circuits(station: Station, elements: list[Element], before_m: float = HOME_BEFORE_M,
                         beyond_m: float = HOME_BEYOND_M) -> list[dict]:
    """One provisional circuit per Home signal on a line: S1 -> '1AT', S29 -> '29AT'."""
    lines = {t.id: t for t in station.tracks}
    out = []
    for e in elements:
        lo = (e.element_type or "").lower()
        if "home" not in lo or "distant" in lo or e.track_id not in lines:
            continue
        m = re.search(r"(\d+)", e.element_ref or "")
        if not m:
            continue
        sg = _sign(e, station, lines[e.track_id].line_type)
        a, b = e.location_m - sg * before_m, e.location_m + sg * beyond_m
        out.append(dict(label=f"{m.group(1)}AT", track_id=e.track_id, start_m=min(a, b), end_m=max(a, b),
                        remarks=f"{PROVISIONAL_NOTE}: {before_m:g} m behind {e.element_ref}, {beyond_m:g} m beyond it"))
    return out


def split_berthing_circuit(prefix: str, track_id: int, start_m: float, end_m: float) -> list[dict]:
    """One berthing circuit (e.g. DMT) between two starters, divided into three equal parts: DMAT, DMBT, DMCT."""
    lo, hi = sorted((start_m, end_m))
    step = (hi - lo) / 3
    names = ("AT", "BT", "CT")
    return [dict(label=f"{prefix}{n}", track_id=track_id, start_m=round(lo + i * step), end_m=round(lo + (i + 1) * step),
                 remarks=f"{PROVISIONAL_NOTE}: {prefix}T divided in three")
            for i, n in enumerate(names)]
