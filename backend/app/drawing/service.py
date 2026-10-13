"""Station (ORM) -> DrawingData for the layout sheet."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from ..allotment.ranges import TAG_MAX, TIN_MAX, RangeError, parse_ranges
from ..allotment.service import chart_ref, current_rows, find_row
from .layout import (DAllotRow, DBorder, DElement, DrawingData, DTag, DTin, DTrack)

SIGN_ACTIONS = {"Prepared": "self_check", "Checked": "check", "Approved": "approve"}


def _nums(text, hi):
    try:
        return set(parse_ranges(text, hi))
    except RangeError:
        return set()


def build_data(db: Session, st: models.StationORM, user: models.UserORM) -> DrawingData:
    ws = st.workspace
    d = DrawingData(
        station_name=st.name, kavach_station_id=st.kavach_station_id,
        sip_drawing_number=st.sip_drawing_number or "", layout_version=st.layout_version,
        zone=f"{ws.code} - {ws.name}" if ws is not None else "", dn_direction=ws.dn_direction if ws else "Nominal",
        drawn_to_scale=False,   # the generated sheet's chainage axis is always compressed (H2.26)
        centre_line_m=st.centre_line_m,
        generated_at=datetime.now(timezone.utc).isoformat(), generated_by=user.full_name or user.username)
    from ..domain import guess_line_type
    d.tracks = [DTrack(t.id, t.name, t.start_m, t.end_m, t.is_kavach is not False,
                       t.line_type or guess_line_type(t.name), t.sort_order or 0) for t in st.tracks]
    d.tins = [DTin(n.tin_no, n.start_m, n.end_m, n.track_id, n.color, n.section_type,
                   bool(n.is_non_kavach_territory)) for n in st.tins]
    d.tags = [DTag(t.tag_ref, t.tag_type, t.location_m, t.track_id, t.tag_number, t.direction, t.legend_shape,
                   t.pair_group_id, bool(t.is_border_tag), t.abs2_m) for t in st.tags]
    d.elements = [DElement(e.element_ref, e.element_type, e.location_m, e.track_id, e.to_track_id)
                  for e in st.elements]
    for a in st.adjacent_stations:
        d.neighbours.append((a.name, a.side))
        for b in a.borders:
            d.borders.append(DBorder(a.name, a.side, b.line_label, b.border_m, b.border_tag_ref or "", b.track_id))
        if not a.borders and a.border_m is not None:
            d.borders.append(DBorder(a.name, a.side, "All lines", a.border_m))
    d.revisions = [(r.rev_no, r.date, r.description) for r in
                   db.query(models.RevisionORM).filter_by(station_id=st.id).order_by(models.RevisionORM.id)]

    # signature block: latest self-check / check / approval in the workflow history
    events = (db.query(models.WorkflowEventORM).filter_by(station_id=st.id)
              .order_by(models.WorkflowEventORM.id.desc()).all())
    names = {u.username: u.full_name for u in db.query(models.UserORM).all()}
    for role, action in SIGN_ACTIONS.items():
        ev = next((e for e in events if e.action == action), None)
        if ev is not None:
            d.signatures[role] = (names.get(ev.actor_username) or ev.actor_username, (ev.timestamp or "")[:10])

    # allotment block (H2.23): own row and the adjacent sections' rows, with used / spare
    rows = current_rows(db, st.workspace_id)
    used_tags = {t.tag_number for t in st.tags if t.tag_number is not None}
    used_tins = {n.tin_no for n in st.tins}
    own = find_row(rows, st.kavach_station_id, st.name) if rows else None
    if own is not None:
        d.allotment_ref = chart_ref(own.chart)
        seen_rows = set()
        for label, r in [(st.name, own)] + [(a.name, find_row(rows, a.kavach_station_id, a.name))
                                            for a in st.adjacent_stations]:
            if r is not None:
                if r.id in seen_rows:
                    continue                  # two neighbours matched to the same chart row
                seen_rows.add(r.id)
            if r is None:
                d.allotment.append(DAllotRow(f"{label} (not on chart)", "", None, None, "", None, None))
                continue
            tg, tn = _nums(r.tag_ranges, TAG_MAX), _nums(r.tin_ranges, TIN_MAX)
            d.allotment.append(DAllotRow(r.name, r.tag_ranges or "", len(tg & used_tags), len(tg - used_tags),
                                         r.tin_ranges or "", len(tn & used_tins), len(tn - used_tins)))
    return d
