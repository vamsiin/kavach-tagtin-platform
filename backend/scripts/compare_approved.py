"""Compare a station's tag / TIN registers with the approved layout's data.

    python scripts/compare_approved.py --station-id 1 \
        --import-json ../frontend/import/aler_dwg_import.json --key aler \
        --toc ../sample_data/ALER_ToC.csv

Three independent comparisons (only the ones whose input is given are run):
  1. registers vs the approved-drawing import JSON: tags (number, type, chainage, direction,
     line) and TINs (number, line, extent, colour) present on one side only or different;
  2. registers vs the Table of Control: every tag the ToC chains name exists, and drawn
     distances along each route match the ToC's cumulative distances (toc/cross_validate.py);
  3. TIN numbers named in the ToC (free-TIN lists, adjacent-line info) vs the TIN register.

Read-only. Point DATABASE_URL at a copy to keep a live database untouched (the first
connection adds any missing columns to the file it opens).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def compare_json(st, path: str, key: str) -> list[str]:
    ref = json.load(open(path, encoding="utf-8"))[key]
    lines = {t.id: t.name for t in st.tracks}
    out = []
    mine = {t.tag_ref: t for t in st.tags}
    theirs = {t["tag_ref"]: t for t in ref.get("tags", [])}
    out += [f"tag {r}: in the register, not in the approved data" for r in sorted(set(mine) - set(theirs))]
    out += [f"tag {r}: in the approved data, not in the register" for r in sorted(set(theirs) - set(mine))]
    for r in sorted(set(mine) & set(theirs)):
        a, b, d = mine[r], theirs[r], []
        if a.tag_type != b["tag_type"]:
            d.append(f"type {a.tag_type} vs {b['tag_type']}")
        if a.tag_number != b.get("tag_number"):
            d.append(f"number {a.tag_number} vs {b.get('tag_number')}")
        if abs(a.location_m - b["location_m"]) > 0.5:
            d.append(f"chainage {a.location_m:g} vs {b['location_m']:g}")
        if (a.direction or None) != (b.get("direction") or None):
            d.append(f"direction {a.direction} vs {b.get('direction')}")
        if lines.get(a.track_id) != b.get("line"):
            d.append(f"line {lines.get(a.track_id)} vs {b.get('line')}")
        if d:
            out.append(f"tag {r}: " + "; ".join(d))
    reg = {(n.tin_no, lines.get(n.track_id), n.start_m, n.end_m): n for n in st.tins}
    app = {(t["tin_no"], t.get("line"), t["start_m"], t["end_m"]): t for t in ref.get("tins", [])}
    out += [f"TIN {k[0]} on {k[1]} {k[2]:g}-{k[3]:g}: in the register, not in the approved data"
            for k in sorted(set(reg) - set(app), key=str)]
    out += [f"TIN {k[0]} on {k[1]} {k[2]:g}-{k[3]:g}: in the approved data, not in the register"
            for k in sorted(set(app) - set(reg), key=str)]
    for k in sorted(set(reg) & set(app), key=str):
        if (reg[k].color or "").lower() != (app[k].get("color") or "").lower():
            out.append(f"TIN {k[0]} on {k[1]}: colour {reg[k].color} vs {app[k].get('color')}")
    return out


def compare_toc(st, path: str) -> tuple[list[str], list[str]]:
    from app.toc.cross_validate import cross_validate_route
    from app.toc.parser import parse_toc_file
    routes = parse_toc_file(path, os.path.basename(path))
    tags = {t.tag_ref: t.to_domain() for t in st.tags}
    res = [x for r in routes for x in cross_validate_route(r, tags)]
    c = collections.Counter(x.status for x in res)
    tag_lines = [f"{len(routes)} routes; chain checks {dict(c)}"]
    tag_lines += [f"route {x.route_s_no} {x.entry_signal}->{x.exit_signal or '-'}: {x.message}"
                  for x in res if x.status != "PASS"]
    in_toc = {e.tag_id for r in routes for e in r.tag_chain} | {r.entry_signal_foot_tag for r in routes
                                                                  if r.entry_signal_foot_tag}
    tag_lines.append(f"ToC tags missing from the register: {sorted(in_toc - set(tags)) or 'none'}")
    tag_lines.append(f"register tags in no ToC chain (loop / turnout tags often are): "
                     f"{sorted(set(tags) - in_toc) or 'none'}")
    reg = {n.tin_no for n in st.tins}
    toc = set()
    for r in routes:
        for txt in (r.tins_required_free, r.tins_required_free_overlap):
            toc |= {int(x) for x in re.findall(r"N-(\d+)", txt or "")}        # "N-169#N-170", "N-171(W19R)"
        parts = re.findall(r"\d+", r.adjacent_line_info or "")               # "(1#222#221#0#0#0#0)"
        toc |= {int(x) for x in parts[1:3] if int(x)}
    tin_lines = [f"TINs named in the ToC but not in the register: {sorted(toc - reg) or 'none'}",
                 f"register TINs the ToC never names: {sorted(reg - toc) or 'none'}"]
    return tag_lines, tin_lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station-id", type=int, required=True)
    ap.add_argument("--import-json")
    ap.add_argument("--key", default="aler", help="top-level key of the import JSON")
    ap.add_argument("--toc")
    a = ap.parse_args()
    from app import models
    from app.database import SessionLocal, ensure_schema_up_to_date
    ensure_schema_up_to_date()
    db = SessionLocal()
    st = db.get(models.StationORM, a.station_id)
    if st is None:
        sys.exit(f"No station with id {a.station_id}")
    print(f"Station {st.name} ({st.kavach_station_id}): {len(st.tags)} tags, {len(st.tins)} TIN rows")
    if a.import_json:
        diffs = compare_json(st, a.import_json, a.key)
        print("\n== Register vs approved drawing data ==")
        print("\n".join(diffs) if diffs else "identical")
    if a.toc:
        tag_lines, tin_lines = compare_toc(st, a.toc)
        print("\n== Register vs Table of Control: tags ==")
        print("\n".join(tag_lines))
        print("\n== Register vs Table of Control: TINs ==")
        print("\n".join(tin_lines))


if __name__ == "__main__":
    main()
