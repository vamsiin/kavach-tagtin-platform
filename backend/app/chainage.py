"""Chainage ordering for line (track) and TIN sections -- REQ-TAGTIN-DIR-001..007
(test-team observation, Oct 2026).

A section is stored with its LOWER chainage in start_m ("From / Start") and its HIGHER
chainage in end_m ("To / End"), whatever the direction of movement. Direction is a
separate attribute:

    Nominal  movement from the lower to the higher chainage   (start_m -> end_m)
    Reverse  movement from the higher to the lower chainage   (end_m -> start_m)
    Both     bi-directional line (e.g. a common loop)

Entering the endpoints the "other way round" (e.g. an UP line as 266.417 -> 258.024)
is accepted and normalised; it never changes the direction, and changing the
direction never swaps the endpoints.
"""
from __future__ import annotations

import math
import os

from fastapi import HTTPException

DIRECTIONS = ("Nominal", "Reverse", "Both")
DIRECTION_LABELS = {
    "Nominal": "Nominal (lower to higher chainage)",
    "Reverse": "Reverse (higher to lower chainage)",
    "Both": "Both directions",
}


def negative_allowed() -> bool:
    """Railway chainage is not negative; a deployment whose chainage system uses
    negative values can allow them with ALLOW_NEGATIVE_CHAINAGE=true."""
    return os.environ.get("ALLOW_NEGATIVE_CHAINAGE", "false").lower() in ("1", "true", "yes")


def normalise_section(a, b, direction: str | None, what: str = "Section") -> tuple[float, float, bool]:
    """Validate two endpoint chainages and return (lower, higher, swapped).
    Raises 422 for missing, non-numeric, non-finite, negative or equal endpoints and
    for an unknown direction."""
    vals = []
    for label, v in (("From / Start", a), ("To / End", b)):
        if v is None or isinstance(v, bool):
            raise HTTPException(422, f"{what}: {label} chainage is required")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{what}: {label} chainage must be a number")
        if not math.isfinite(f):
            raise HTTPException(422, f"{what}: {label} chainage must be a finite number")
        if f < 0 and not negative_allowed():
            raise HTTPException(422, f"{what}: {label} chainage cannot be negative ({f:g} m)")
        vals.append(f)
    lo, hi = vals
    if lo == hi:
        raise HTTPException(422, f"{what}: the two endpoints are equal ({lo:g} m) -- a section needs two "
                                 f"different chainages")
    if direction is not None and direction not in DIRECTIONS:
        raise HTTPException(422, f"{what}: direction must be one of {', '.join(DIRECTIONS)} (or left blank)")
    swapped = lo > hi
    return (hi, lo, True) if swapped else (lo, hi, False)


def movement(start_m: float, end_m: float, direction: str | None) -> tuple[float | None, float | None]:
    """(origin, destination) of movement along a normalised section."""
    lo, hi = min(start_m, end_m), max(start_m, end_m)
    if direction == "Nominal":
        return lo, hi
    if direction == "Reverse":
        return hi, lo
    return None, None


def movement_text(start_m: float, end_m: float, direction: str | None) -> str:
    o, d = movement(start_m, end_m, direction)
    if o is None:
        return "Both directions" if direction == "Both" else "-"
    return f"{o / 1000:.3f} -> {d / 1000:.3f}"


def normalise_existing(db) -> int:
    """One-off on start-up: rows saved before REQ-TAGTIN-DIR-001 with the higher
    chainage first are swapped into lower/higher order (direction is untouched).
    Returns how many rows changed."""
    from . import models
    n = 0
    for model in (models.TrackORM, models.TINORM):
        for row in db.query(model).filter(model.start_m > model.end_m).all():
            row.start_m, row.end_m = row.end_m, row.start_m
            n += 1
    if n:
        db.commit()
    return n
