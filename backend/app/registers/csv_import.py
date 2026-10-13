"""Bulk entry of the Elements, Tags and TINs registers from a CSV (or .xlsx) file.

A file is first PREVIEWED: every row is parsed and checked with the same rules as the
entry forms, and gets an action (add / update / skip) or the errors that stop it.
Nothing is written unless the whole file is free of errors; then APPLY writes all of
it in one transaction. Rows are matched to existing entries by their identity --
element ref + line, tag ID, TIN number + line -- and with "update existing" off a
matching row is reported as an error instead of being changed.

Column headers are matched loosely (case, spaces, underscores; common aliases such as
"Chainage (m)", "km", "Line"), so a sheet exported from the registers or typed by hand
both work. Locations can be given in metres (location_m / chainage) or in km.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from fastapi import HTTPException

from .. import models
from ..domain import (ELEMENT_TYPES, LC_CLASSES, LC_GATE, LC_MANNING, POINTS, TAG_TYPES, is_signal_type,
                      normalise_aspects)

KINDS = ("elements", "tags", "tins")

# canonical field -> accepted header spellings (normalised: lower case, letters/digits only)
_ALIASES = {
    "elements": {
        "element_ref": ["elementref", "ref", "element", "name", "signal", "id", "nameofthesignal", "signalname",
                        "nameoftheelement", "elementname"],
        "element_type": ["elementtype", "type", "typeofsignal", "signaltype", "typeofelement"],
        "location_m": ["locationm", "location", "chainagem", "chainage", "absolutelocation"],
        "km": ["km", "locationkm", "chainagekm"],
        "line": ["line", "track", "trackname", "linename"],
        "to_line": ["toline", "divergingline", "leadsto", "totrack"],
        "direction": ["direction", "dir"],
        "lc_class": ["lcclass", "class"],
        "lc_manning": ["lcmanning", "manning"],
        "aspects": ["aspects", "aspect", "signalaspects", "aspectsofsignal", "lamps"],
        "remarks": ["remarks", "remark", "notes"],
    },
    "tags": {
        "tag_ref": ["tagref", "tagid", "ref", "tag", "id"],
        "tag_number": ["tagnumber", "number", "no", "tagno"],
        "tag_type": ["tagtype", "type", "typeoftag"],
        "location_m": ["locationm", "location", "chainagem", "chainage", "absolutelocation"],
        "km": ["km", "locationkm", "chainagekm"],
        "line": ["line", "track", "trackname", "linename"],
        "direction": ["direction", "dir"],
        "placed_for": ["placedfor", "linkedelement", "linkedelementref", "element", "for"],
        "paired_with": ["pairedwith", "partner", "pairtag", "duplicateof"],
        "role": ["role", "pairrole", "mainorduplicate"],
        "pair_group_id": ["pairgroupid", "pairgroup", "group"],
        "legend_shape": ["legendshape", "legend"],
        "exit_set": ["exitset"],
        "is_border_tag": ["isbordertag", "bordertag", "border"],
        "abs2_m": ["abs2m", "abs2", "correctedlocation", "correctedlocationm"],
        "remarks": ["remarks", "remark", "notes"],
    },
    "tins": {
        "tin_no": ["tinno", "tin", "tinnumber", "no", "number"],
        "section_type": ["sectiontype", "section", "type", "tinplacement", "placement"],
        "line": ["line", "track", "trackname", "linename"],
        "color": ["color", "colour"],
        "start_m": ["startm", "start", "fromm", "from", "fromstartm", "endpointa", "endpointam", "a"],
        "end_m": ["endm", "end", "tom", "to", "toendm", "endpointb", "endpointbm", "b"],
        "start_km": ["startkm", "fromkm"],
        "end_km": ["endkm", "tokm"],
        "direction": ["direction", "dir"],
        "is_non_kavach_territory": ["isnonkavachterritory", "nonkavach", "nonkavachterritory", "nokavachterritory",
                                    "nokavach"],
        "remarks": ["remarks", "remark", "notes"],
    },
}

# Templates use the column headings of the QFTL working sheets (ALER_*_test.csv).
TEMPLATES = {
    "elements": ("#,Name of the  Signal,Type of Signal,Location(m),Line,Dir,Remarks\n"
                 "1,S1D,Distant Signal,259740,DN MAIN,Down,-\n"
                 "2,S1/S1A,Main Home with Junction Route Indicator,261789,DN MAIN,Down,-\n"
                 "3,BSLB,BSLB Board,261978,DN MAIN,Down,-\n"
                 "4,SH23,Shunt Signal,262221,DN MAIN,Down,-\n"
                 "5,S30D,Gate Distant Signal,266417,UP MAIN,Up,-\n"),
    "tags": ("#,Tag Number,Type of Tag,Chainage(m),Line,Dir,Linked element,Pair group ID,Legend,Border tag\n"
             "1,R-775,S - Signal Foot Tag,259740,DN MAIN,Nominal (DN),S1D,-,Triangle,Yes\n"
             "2,R-777,N - Normal / Inline section Tag,260559,DN MAIN,Nominal (DN),-,-,Triangle,No\n"
             "3,R-862,A - Adjustment / Junction Tag,261083 / 261144,UP MAIN,Reverse (UP),-,-,Triangle,No\n"),
    "tins": ("#,TIN Number,TIN Placement,Line,Color,Start (m),End (m),No KAVACH territory\n"
             "1,222,Block,DN MAIN,Orange,252711,261978,No\n"
             "2,169,Station,DN MAIN,Yellow,261978,262221,No\n"
             "3,218,Block,UP MAIN,Orange,270968,263145,No\n"),
}

# serial-number columns are skipped without a warning
_SERIAL = {"", "sno", "slno", "srno", "serialno", "no"}



def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read_table(filename: str, data: bytes) -> list[dict[str, str]]:
    """Rows of a .csv or .xlsx file as {header: text}."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        rows = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
    elif name.endswith((".csv", ".txt")) or not name:
        text = data.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    else:
        raise HTTPException(422, "Upload a .csv file (or .xlsx)")
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        raise HTTPException(422, "The file is empty")
    head = rows[0]
    out = []
    for r in rows[1:]:
        if r and str(r[0]).startswith("#") and len(str(r[0])) > 1:
            continue                       # "# comment" line
        out.append({head[i]: (r[i] if i < len(r) else "") for i in range(len(head))})
    return out


def map_headers(kind: str, headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """{canonical field: header in file}, and the headers that were not recognised."""
    aliases = _ALIASES[kind]
    found, unknown = {}, []
    for h in headers:
        n = _norm(h)
        if h.strip() in ("#", "") or n in ("sno", "slno", "srno", "serialno"):
            continue                       # serial-number column
        hit = next((f for f, al in aliases.items() if n == _norm(f) or n in al), None)
        if hit and hit not in found:
            found[hit] = h
        elif not hit:
            unknown.append(h)
    return found, unknown


@dataclass
class RowResult:
    row: int                       # 1-based data row (header = row 0)
    key: str
    action: str = "add"            # add | update | error
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    existing_id: int | None = None


def _clean(v) -> str:
    """Cell text with line breaks and repeated spaces collapsed; '-' / 'NA' mean empty."""
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    t = re.sub(r"\s*-\s+", "-", t) if re.search(r"\w-\s+\w", t) else t   # "Distant-Cum-\n Distant" -> joined
    return "" if t in ("-", "--", "NA", "N/A", "n/a", "na") else t


def _yes(v: str) -> bool:
    return _norm(v) in ("yes", "y", "true", "1", "x")


def _num(v: str, what: str, errs: list[str], integer=False):
    v = (v or "").strip().replace(",", "")
    if v == "":
        return None
    try:
        f = float(v)
    except ValueError:
        errs.append(f"{what} '{v}' is not a number")
        return None
    if integer:
        if f != int(f):
            errs.append(f"{what} '{v}' must be a whole number")
            return None
        return int(f)
    return f


# names used on QFTL sheets for element types that RDSO's list spells differently
_TYPE_ALIASES = {
    "gatestopcuminnerdistantsignal": "Gate-cum-Inner Distant Signal",
    "gatehomecuminnerdistantsignal": "Gate-cum-Inner Distant Signal",
    "gatehomesignal": "Gate Stop Signal",
    "stopboard": "Stop Board/Buffer Stop",
    "bufferstop": "Stop Board/Buffer Stop",
    "callingonsignal": "Calling-on Signal",
    "advancestartersignal": "Advanced Starter Signal",
    "advancestarter": "Advanced Starter Signal",
    "advancedstarter": "Advanced Starter Signal",
    "shunt": "Shunt Signal",
    "bslb": "BSLB Board",
    "points": "Points / Turnout",
    "turnout": "Points / Turnout",
    "lcgate": "LC Gate",
}


def _choice(v: str, options, what: str, errs: list[str]):
    v = _clean(v)
    if not v:
        return None
    for o in options:
        if _norm(o) == _norm(v):
            return o
    alias = _TYPE_ALIASES.get(_norm(v))
    if alias in options:
        return alias
    if len(options) > 8:
        import difflib
        near = difflib.get_close_matches(v, list(options), n=3, cutoff=0.4)
        errs.append(f"{what} '{v}' is not a known value" + (f" -- did you mean {' / '.join(near)}?" if near
                                                               else " (see the list in the Add form or the template)"))
    else:
        errs.append(f"{what} '{v}' is not one of: {', '.join(options)}")
    return None


def _location(rec: dict, errs: list[str], m_key="location_m", km_key="km", what="Chainage", warns=None):
    raw = _clean(rec.get(m_key, ""))
    if "/" in raw:                      # adjustment tag "261083 / 261144": ABS-1 / ABS-2
        first, second = [x.strip() for x in raw.split("/", 1)]
        if warns is not None:
            warns.append(f"Two chainages given ({raw}): ABS-1 {first} = location, ABS-2 {second} = corrected location")
        rec["_abs2"] = second
        raw = first
    m = _num(raw, f"{what} (m)", errs)
    if m is None and rec.get(km_key, "").strip():
        k = _num(rec.get(km_key, ""), f"{what} (km)", errs)
        m = round(k * 1000, 3) if k is not None else None
    if m is not None and m < 0:
        errs.append(f"{what} cannot be negative")
    return m


def _abs2(rec: dict, ttype: str | None, errs: list[str], warns: list[str]) -> float | None:
    """ABS-2 of an adjustment tag, from "ABS-1 / ABS-2" in the chainage cell or an abs2 column."""
    raw = rec.get("_abs2") or rec.get("abs2_m") or ""
    if not raw:
        return None
    v = _num(raw, "ABS-2", errs)
    if v is not None and ttype != "A":
        warns.append("ABS-2 is only used for adjustment (A) tags -- ignored")
        return None
    return v


def _direction(v: str, errs: list[str], allow_both=False, dn_direction: str = "Nominal"):
    v = _clean(v)
    if not v:
        return None
    n = _norm(v)
    if n in ("nominal", "nom", "n") or n.startswith("nominal"):
        return "Nominal"
    if n in ("reverse", "rev", "r") or n.startswith("reverse"):
        return "Reverse"
    up = "Reverse" if dn_direction == "Nominal" else "Nominal"
    if n in ("down", "dn", "d"):
        return dn_direction
    if n in ("up", "u"):
        return up
    if allow_both and n in ("both", "bidirectional"):
        return "Both"
    errs.append(f"Direction '{v}' must be Nominal or Reverse" + (" or Both" if allow_both else ""))
    return None


def _match(same: list, exact, claimed: set):
    """The existing row a file row updates: the one at the same place if there is one,
    otherwise the only one with that name -- each existing row is matched at most once,
    so two rows of the file never overwrite the same entry."""
    hit = next((x for x in same if exact(x) and x.id not in claimed), None)
    if hit is None:
        free = [x for x in same if x.id not in claimed]
        hit = free[0] if len(free) == 1 and len(same) == 1 else None
    if hit is not None:
        claimed.add(hit.id)
    return hit


def preview(db, station: models.StationORM, kind: str, rows: list[dict[str, str]], update_existing: bool) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown register")
    if not rows:
        raise HTTPException(422, "No data rows in the file")
    cols, unknown = map_headers(kind, list(rows[0].keys()))
    # QFTL sheets put the tag ID (R-775) in the "Tag Number" column
    if kind == "tags" and "tag_ref" not in cols and "tag_number" in cols and any(
            re.match(r"^[A-Za-z]+-?\d+$", _clean(r.get(cols["tag_number"], ""))) for r in rows):
        cols["tag_ref"] = cols.pop("tag_number")
    rec_rows = [{f: _clean(r.get(h, "")) for f, h in cols.items()} for r in rows]
    dn_direction = station.workspace.dn_direction if station.workspace is not None else "Nominal"
    tracks = {t.name.strip().upper(): t for t in station.tracks}
    for t in station.tracks:      # also by line type (e.g. "DN MAIN" when the line is called "DN.MAIN")
        tracks.setdefault((t.line_type or "").upper(), t)

    def line(v, errs, what="Line"):
        v = (v or "").strip()
        if not v:
            return None
        t = tracks.get(v.upper()) or tracks.get(re.sub(r"[\s._-]+", " ", v.upper()).strip())
        if t is None:
            errs.append(f"{what} '{v}' is not a line of this station ({', '.join(x.name for x in station.tracks) or 'no lines yet'})")
            return None
        return t.id

    results: list[RowResult] = []
    claimed: set[int] = set()     # existing rows already matched by an earlier line of the file
    if kind == "elements":
        missing = [f for f in ("element_ref", "element_type") if f not in cols] + \
                  ([] if ("location_m" in cols or "km" in cols) else ["location_m (or km)"])
        if missing:
            raise HTTPException(422, f"Missing column(s): {', '.join(missing)}")
        existing: dict = {}
        for e in station.elements:
            existing.setdefault((e.element_ref.strip().upper(), e.track_id), []).append(e)
        seen = set()
        for i, rec in enumerate(rec_rows, 1):
            errs, warns = [], []
            ref = rec.get("element_ref", "").strip()
            if not ref:
                errs.append("Element ref is empty")
            etype = _choice(rec.get("element_type", ""), ELEMENT_TYPES, "Element type", errs)
            if not etype and rec.get("element_type", "").strip() == "":
                errs.append("Element type is empty")
            loc = _location(rec, errs)
            if loc is None and not any("Chainage" in e for e in errs):
                errs.append("Chainage is empty")
            tid = line(rec.get("line"), errs)
            to = line(rec.get("to_line"), errs, "Diverging line") if etype == POINTS else None
            if etype == POINTS and to is not None and to == tid:
                errs.append("Points must lead to a different line from the one they are on")
            if etype == POINTS and to is None and not rec.get("to_line", "").strip():
                warns.append("Points: the line they lead to is not given")
            lc_class = _choice(rec.get("lc_class", ""), LC_CLASSES, "LC class", errs) if etype == LC_GATE else None
            lc_man = _choice(rec.get("lc_manning", ""), LC_MANNING, "LC manning", errs) if etype == LC_GATE else None
            aspects = None
            if (rec.get("aspects") or "").strip() and etype:
                if is_signal_type(etype):
                    try:
                        aspects = normalise_aspects(rec.get("aspects"))
                    except ValueError as ex:
                        errs.append(str(ex))
                else:
                    warns.append(f"Aspects ignored: {etype} is not a signal")
            key = (ref.upper(), tid)
            if (key, loc) in seen:
                errs.append(f"{ref} appears twice in the file on the same line at the same chainage")
            seen.add((key, loc))
            r = RowResult(i, f"{ref}" + (f" ({rec.get('line')})" if rec.get("line") else ""), errors=errs, warnings=warns,
                          data=dict(element_ref=ref, element_type=etype, location_m=loc, track_id=tid,
                                    to_track_id=to, direction=(rec.get("direction") or "").strip() or None,
                                    lc_class=lc_class, lc_manning=lc_man, aspects=aspects,
                                    remarks=(rec.get("remarks") or "").strip() or None))
            old = _match(existing.get(key, []), lambda e: e.location_m == loc, claimed)
            if old is not None:
                r.existing_id = old.id
                if update_existing:
                    r.action = "update"
                else:
                    errs.append(f"{ref} already exists on this line -- tick 'update existing' to change it")
            results.append(r)

    elif kind == "tags":
        missing = [f for f in ("tag_ref", "tag_type") if f not in cols] + \
                  ([] if ("location_m" in cols or "km" in cols) else ["location_m (or km)"])
        if missing:
            raise HTTPException(422, f"Missing column(s): {', '.join(missing)}")
        existing = {t.tag_ref.strip().upper(): t for t in station.tags}
        els_by_ref: dict[str, list] = {}
        for e in station.elements:
            els_by_ref.setdefault(e.element_ref.strip().upper(), []).append(e)
        file_refs = {rec.get("tag_ref", "").strip().upper() for rec in rec_rows}
        seen = set()
        from ..domain import suitable_link
        for i, rec in enumerate(rec_rows, 1):
            errs, warns = [], []
            ref = rec.get("tag_ref", "").strip()
            if not ref:
                errs.append("Tag ID is empty")
            tt = rec.get("tag_type", "")
            m = re.match(r"^([A-Za-z])\s*(-|–|:|\s)\s*", tt)
            ttype = _choice(m.group(1).upper() if m else tt, TAG_TYPES, "Tag type", errs)
            if not rec.get("tag_type", "").strip():
                errs.append("Tag type is empty")
            num = _num(rec.get("tag_number", ""), "Tag number", errs, integer=True)
            if num is None and re.fullmatch(r"[A-Za-z]+-?\d+", ref):
                num = int(re.sub(r"\D", "", ref))           # R-775 -> 775
            if num is not None and not 1 <= num <= 1023:
                errs.append(f"Tag number {num} outside 1-1023")
            loc = _location(rec, errs, warns=warns)
            if loc is None and not any("Chainage" in e for e in errs):
                errs.append("Chainage is empty")
            tid = line(rec.get("line"), errs)
            direction = _direction(rec.get("direction"), errs, dn_direction=dn_direction)
            link = None
            pf = (rec.get("placed_for") or "").strip()
            if pf:
                cands = els_by_ref.get(pf.upper(), [])
                if len(cands) > 1 and tid is not None:
                    cands = [e for e in cands if e.track_id == tid] or cands
                if not cands:
                    errs.append(f"Placed for '{pf}' is not an element of this station (import the elements first)")
                else:
                    link = cands[0].id
                    if len(cands) > 1:
                        warns.append(f"'{pf}' exists on several lines; linked to the one on {cands[0].track_id and next((t.name for t in station.tracks if t.id == cands[0].track_id), '?')}")
                    if ttype and not suitable_link(ttype, cands[0].element_type):
                        warns.append(f"A {ttype} tag is not usually placed for a {cands[0].element_type}")
            elif ttype == "T":
                warns.append("Turnout tag without the points it is for")
            partner = (rec.get("paired_with") or "").strip()
            if partner and partner.upper() not in existing and partner.upper() not in file_refs:
                errs.append(f"Paired with '{partner}' is not a tag in the register or in this file")
            role = _norm(rec.get("role", ""))
            legend = _choice(rec.get("legend_shape", ""), ["Rectangle", "Triangle"], "Legend shape", errs)
            exit_set = _choice(rec.get("exit_set", ""), ["1st", "2nd"], "Exit set", errs)
            if ref.upper() in seen:
                errs.append(f"{ref} appears twice in the file")
            seen.add(ref.upper())
            r = RowResult(i, ref, errors=errs, warnings=warns, data=dict(
                tag_ref=ref, tag_number=num, tag_type=ttype, location_m=loc, track_id=tid, direction=direction,
                linked_element_id=link, legend_shape=legend, exit_set=exit_set,
                is_border_tag=_yes(rec.get("is_border_tag", "")),
                remarks=(rec.get("remarks") or "").strip() or None,
                abs2_m=_abs2(rec, ttype, errs, warns),
                pair_group_id=(rec.get("pair_group_id") or "").strip() or None,
                _partner=partner or None, is_duplicate=role.startswith("dup")))
            old = existing.get(ref.upper())
            if old is not None:
                r.existing_id = old.id
                if update_existing:
                    r.action = "update"
                else:
                    errs.append(f"{ref} already exists -- tick 'update existing' to change it")
            results.append(r)

    else:  # tins
        missing = [f for f in ("tin_no",) if f not in cols]
        if not (("start_m" in cols or "start_km" in cols) and ("end_m" in cols or "end_km" in cols)):
            missing.append("start_m and end_m (or endpoint A / B)")
        if missing:
            raise HTTPException(422, f"Missing column(s): {', '.join(missing)}")
        existing: dict = {}
        for n in station.tins:
            existing.setdefault((n.tin_no, n.track_id), []).append(n)
        seen = set()
        from ..chainage import normalise_section
        for i, rec in enumerate(rec_rows, 1):
            errs, warns = [], []
            no = _num(rec.get("tin_no", ""), "TIN number", errs, integer=True)
            if no is None and not any("TIN number" in e for e in errs):
                errs.append("TIN number is empty")
            if no is not None and not 1 <= no <= 255:
                errs.append(f"TIN number {no} outside 1-255")
            section = _choice(rec.get("section_type", "") or "Station", ["Station", "Block"], "Section", errs)
            a = _location(rec, errs, "start_m", "start_km", "From / Start")
            b = _location(rec, errs, "end_m", "end_km", "To / End")
            direction = _direction(rec.get("direction"), errs, allow_both=True)
            lo = hi = None
            if a is not None and b is not None:
                try:
                    lo, hi, swapped = normalise_section(a, b, direction, f"TIN {no}")
                    if swapped:
                        warns.append(f"Endpoints given high-to-low; saved as {lo:g} -> {hi:g}")
                except HTTPException as ex:
                    errs.append(str(ex.detail))
            elif not errs:
                errs.append("Both endpoints are needed")
            tid = line(rec.get("line"), errs)
            key = (no, tid)
            if (key, lo, hi) in seen:
                errs.append(f"TIN {no} appears twice in the file on the same line with the same extent")
            seen.add((key, lo, hi))
            r = RowResult(i, f"TIN {no}" + (f" ({rec.get('line')})" if rec.get("line") else ""), errors=errs,
                          warnings=warns, data=dict(
                              tin_no=no, section_type=section, color=(rec.get("color") or "").strip() or None,
                              start_m=lo, end_m=hi, direction=direction, track_id=tid,
                              is_non_kavach_territory=_yes(rec.get("is_non_kavach_territory", "")),
                              remarks=(rec.get("remarks") or "").strip() or None))
            old = _match(existing.get(key, []), lambda n: (n.start_m, n.end_m) == (lo, hi), claimed)
            if old is not None:
                r.existing_id = old.id
                if update_existing:
                    r.action = "update"
                else:
                    errs.append(f"TIN {no} already exists on this line -- tick 'update existing' to change it")
            results.append(r)

    for r in results:
        if r.errors:
            r.action = "error"
    counts = {a: sum(1 for r in results if r.action == a) for a in ("add", "update", "error")}
    return {
        "kind": kind, "columns": cols, "ignored_columns": unknown, "counts": counts,
        "can_apply": counts["error"] == 0 and (counts["add"] + counts["update"]) > 0,
        "rows": [{"row": r.row, "key": r.key, "action": r.action, "errors": r.errors, "warnings": r.warnings,
                  "data": {k: v for k, v in r.data.items() if not k.startswith("_")}} for r in results],
        "_results": results,
    }


def apply(db, station: models.StationORM, kind: str, result: dict) -> dict:
    results: list[RowResult] = result["_results"]
    model = {"elements": models.ElementORM, "tags": models.TagORM, "tins": models.TINORM}[kind]
    written = {}
    for r in results:
        data = {k: v for k, v in r.data.items() if not k.startswith("_")}
        if r.action == "update":
            obj = db.get(model, r.existing_id)
            for k, v in data.items():
                if v is None:
                    continue    # a blank / "-" cell keeps what is already recorded (e.g. a tag's linked element)
                setattr(obj, k, v)
        else:
            obj = model(station_id=station.id, **data)
            db.add(obj)
        written[r.key.upper() if kind != "tags" else data["tag_ref"].upper()] = obj
    db.flush()
    if kind == "tags":
        by_ref = {t.tag_ref.strip().upper(): t for t in db.query(models.TagORM).filter_by(station_id=station.id)}
        for r in results:
            partner = r.data.get("_partner")
            if not partner:
                continue
            me, other = by_ref[r.data["tag_ref"].upper()], by_ref[partner.upper()]
            gid = (r.data.get("pair_group_id") or other.pair_group_id or me.pair_group_id
                   or f"PAIR-{'/'.join(sorted([me.tag_ref, other.tag_ref]))}")
            me.pair_group_id = other.pair_group_id = gid
            other.is_duplicate = not me.is_duplicate
            if me.legend_shape is None:
                me.legend_shape = "Rectangle" if me.location_m == other.location_m else "Triangle"
            if other.legend_shape is None:
                other.legend_shape = me.legend_shape
    return result["counts"]
