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
from ..domain import ELEMENT_TYPES, LC_CLASSES, LC_GATE, LC_MANNING, POINTS, TAG_TYPES

KINDS = ("elements", "tags", "tins")

# canonical field -> accepted header spellings (normalised: lower case, letters/digits only)
_ALIASES = {
    "elements": {
        "element_ref": ["elementref", "ref", "element", "name", "signal", "id"],
        "element_type": ["elementtype", "type"],
        "location_m": ["locationm", "location", "chainagem", "chainage", "absolutelocation"],
        "km": ["km", "locationkm", "chainagekm"],
        "line": ["line", "track", "trackname", "linename"],
        "to_line": ["toline", "divergingline", "leadsto", "totrack"],
        "direction": ["direction", "dir"],
        "lc_class": ["lcclass", "class"],
        "lc_manning": ["lcmanning", "manning"],
        "remarks": ["remarks", "remark", "notes"],
    },
    "tags": {
        "tag_ref": ["tagref", "tagid", "ref", "tag", "id"],
        "tag_number": ["tagnumber", "number", "no", "tagno"],
        "tag_type": ["tagtype", "type"],
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
        "remarks": ["remarks", "remark", "notes"],
    },
    "tins": {
        "tin_no": ["tinno", "tin", "tinnumber", "no", "number"],
        "section_type": ["sectiontype", "section", "type"],
        "line": ["line", "track", "trackname", "linename"],
        "color": ["color", "colour"],
        "start_m": ["startm", "start", "fromm", "from", "fromstartm", "endpointa", "endpointam", "a"],
        "end_m": ["endm", "end", "tom", "to", "toendm", "endpointb", "endpointbm", "b"],
        "start_km": ["startkm", "fromkm"],
        "end_km": ["endkm", "tokm"],
        "direction": ["direction", "dir"],
        "is_non_kavach_territory": ["isnonkavachterritory", "nonkavach", "nonkavachterritory"],
        "remarks": ["remarks", "remark", "notes"],
    },
}

TEMPLATES = {
    "elements": ("element_ref,element_type,location_m,line,to_line,direction,lc_class,lc_manning,remarks\n"
                 "S1,Main Home without Junction Route Indicator,261789,DN MAIN,,,,,DN home\n"
                 "P19,Points / Turnout,263009,DN MAIN,COMMON LOOP,,,,\n"
                 "LC-38,LC Gate,264174,DN MAIN,,,Special,Manned interlocked,\n"),
    "tags": ("tag_ref,tag_number,tag_type,location_m,line,direction,placed_for,paired_with,role,legend_shape,"
             "exit_set,is_border_tag,remarks\n"
             "R-783,783,S,261789,DN MAIN,Nominal,S1,,,,,no,signal foot tag of S1\n"
             "R-836,836,T,262966,DN MAIN,Reverse,P19,,,,,no,on the DN/CL crossover\n"
             "R-883,883,G,263574,DN MAIN,Nominal,LC-38,,,,,no,600 m before LC-38\n"),
    "tins": ("tin_no,section_type,line,color,start_m,end_m,direction,non_kavach,remarks\n"
             "169,Station,DN MAIN,Yellow,261978,262221,Nominal,no,\n"
             "222,Block,DN MAIN,Orange,259740,261978,Nominal,no,\n"),
}


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
        if r and str(r[0]).startswith("#"):
            continue
        out.append({head[i]: (r[i] if i < len(r) else "") for i in range(len(head))})
    return out


def map_headers(kind: str, headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """{canonical field: header in file}, and the headers that were not recognised."""
    aliases = _ALIASES[kind]
    found, unknown = {}, []
    for h in headers:
        n = _norm(h)
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


def _choice(v: str, options, what: str, errs: list[str]):
    v = (v or "").strip()
    if not v:
        return None
    for o in options:
        if _norm(o) == _norm(v):
            return o
    if len(options) > 8:
        import difflib
        near = difflib.get_close_matches(v, list(options), n=3, cutoff=0.4)
        errs.append(f"{what} '{v}' is not a known value" + (f" -- did you mean {' / '.join(near)}?" if near
                                                               else " (see the list in the Add form or the template)"))
    else:
        errs.append(f"{what} '{v}' is not one of: {', '.join(options)}")
    return None


def _location(rec: dict, errs: list[str], m_key="location_m", km_key="km", what="Chainage"):
    m = _num(rec.get(m_key, ""), f"{what} (m)", errs)
    if m is None and rec.get(km_key, "").strip():
        k = _num(rec.get(km_key, ""), f"{what} (km)", errs)
        m = round(k * 1000, 3) if k is not None else None
    if m is not None and m < 0:
        errs.append(f"{what} cannot be negative")
    return m


def _direction(v: str, errs: list[str], allow_both=False):
    v = (v or "").strip()
    if not v:
        return None
    n = _norm(v)
    if n in ("nominal", "nom", "n"):
        return "Nominal"
    if n in ("reverse", "rev", "r"):
        return "Reverse"
    if allow_both and n in ("both", "bidirectional"):
        return "Both"
    errs.append(f"Direction '{v}' must be Nominal or Reverse" + (" or Both" if allow_both else ""))
    return None


def preview(db, station: models.StationORM, kind: str, rows: list[dict[str, str]], update_existing: bool) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown register")
    if not rows:
        raise HTTPException(422, "No data rows in the file")
    cols, unknown = map_headers(kind, list(rows[0].keys()))
    rec_rows = [{f: r.get(h, "") for f, h in cols.items()} for r in rows]
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
    if kind == "elements":
        missing = [f for f in ("element_ref", "element_type") if f not in cols] + \
                  ([] if ("location_m" in cols or "km" in cols) else ["location_m (or km)"])
        if missing:
            raise HTTPException(422, f"Missing column(s): {', '.join(missing)}")
        existing = {(e.element_ref.strip().upper(), e.track_id): e for e in station.elements}
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
            key = (ref.upper(), tid)
            if key in seen:
                errs.append(f"{ref} appears twice in the file on the same line")
            seen.add(key)
            r = RowResult(i, f"{ref}" + (f" ({rec.get('line')})" if rec.get("line") else ""), errors=errs, warnings=warns,
                          data=dict(element_ref=ref, element_type=etype, location_m=loc, track_id=tid,
                                    to_track_id=to, direction=(rec.get("direction") or "").strip() or None,
                                    lc_class=lc_class, lc_manning=lc_man,
                                    remarks=(rec.get("remarks") or "").strip() or None))
            old = existing.get(key)
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
            ttype = _choice(rec.get("tag_type", ""), TAG_TYPES, "Tag type", errs)
            if not rec.get("tag_type", "").strip():
                errs.append("Tag type is empty")
            num = _num(rec.get("tag_number", ""), "Tag number", errs, integer=True)
            if num is None and re.fullmatch(r"R-?\d+", ref, re.I):
                num = int(re.sub(r"\D", "", ref))           # R-775 -> 775
            if num is not None and not 1 <= num <= 1023:
                errs.append(f"Tag number {num} outside 1-1023")
            loc = _location(rec, errs)
            if loc is None and not any("Chainage" in e for e in errs):
                errs.append("Chainage is empty")
            tid = line(rec.get("line"), errs)
            direction = _direction(rec.get("direction"), errs)
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
                is_border_tag=_yes(rec.get("is_border_tag", "")), remarks=(rec.get("remarks") or "").strip() or None,
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
        existing = {(n.tin_no, n.track_id): n for n in station.tins}
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
            if key in seen:
                errs.append(f"TIN {no} appears twice in the file on the same line")
            seen.add(key)
            r = RowResult(i, f"TIN {no}" + (f" ({rec.get('line')})" if rec.get("line") else ""), errors=errs,
                          warnings=warns, data=dict(
                              tin_no=no, section_type=section, color=(rec.get("color") or "").strip() or None,
                              start_m=lo, end_m=hi, direction=direction, track_id=tid,
                              is_non_kavach_territory=_yes(rec.get("is_non_kavach_territory", "")),
                              remarks=(rec.get("remarks") or "").strip() or None))
            old = existing.get(key)
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
                if kind == "tags" and k == "pair_group_id" and v is None:
                    continue                       # pairing handled below
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
