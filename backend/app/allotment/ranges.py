"""Number ranges as written on an RDSO RFID Tag / TIN allotment chart.

Pure functions, no DB. A cell is a comma-separated list of single numbers and
inclusive ranges, e.g. "977-1023, 1-70" (wraps past 1023), "220, 219, 218, 217",
"169-192". Tag numbers run 1-1023 and TIN numbers 1-255 (Annexure-H H2.23).
"""
from __future__ import annotations

import re

TAG_MAX = 1023
TIN_MAX = 255

_DASHES = re.compile(r"[‐-―−~]")


class RangeError(ValueError):
    pass


def parse_ranges(text: str | None, hi: int, lo: int = 1) -> list[int]:
    """Numbers in the cell, sorted and unique. Raises RangeError on anything that
    isn't a number or a low-high pair within [lo, hi]."""
    if text is None:
        return []
    s = _DASHES.sub("-", str(text)).replace(";", ",").replace("&", ",")
    out: set[int] = set()
    for part in (p.strip() for p in s.split(",")):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                raise RangeError(f"'{part}': range runs backwards")
        elif re.fullmatch(r"\d+", part):
            a = b = int(part)
        else:
            raise RangeError(f"'{part}' is not a number or a range like 12-34")
        if a < lo or b > hi:
            raise RangeError(f"'{part}' is outside {lo}-{hi}")
        out.update(range(a, b + 1))
    return sorted(out)


def compact(nums) -> str:
    """[1,2,3,7,9,10] -> '1-3, 7, 9-10'."""
    nums = sorted(set(nums))
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ", ".join(parts)


def id_key(value) -> int | None:
    """Station ID / KAVACH ID as a number, so '00103', '103' and 103 all match."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def name_key(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()
