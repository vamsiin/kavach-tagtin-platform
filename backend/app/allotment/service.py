"""Allotment chart lookups (BR-001): which chart row belongs to a station and to
each of its adjacent stations / block sections."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import domain, models
from .ranges import TAG_MAX, TIN_MAX, RangeError, id_key, name_key, parse_ranges


def current_rows(db: Session, workspace_id: int | None = None) -> list[models.AllotmentRowORM]:
    """Rows of the current charts in a workspace (charts are per zone)."""
    q = (db.query(models.AllotmentRowORM).join(models.AllotmentChartORM)
         .filter(models.AllotmentChartORM.is_current.is_(True)))
    if workspace_id is not None:
        q = q.filter(models.AllotmentChartORM.workspace_id == workspace_id)
    return q.order_by(models.AllotmentChartORM.id.desc(), models.AllotmentRowORM.id).all()


def find_row(rows, kavach_id, name) -> models.AllotmentRowORM | None:
    """Match by station ID (numerically: '00103' == '103'), else by exact name."""
    k = id_key(kavach_id)
    if k is not None:
        for r in rows:
            if id_key(r.station_id) == k or (not r.station_id and id_key(r.station_code) == k):
                return r
    n = name_key(name)
    if n:
        for r in rows:
            if name_key(r.name) == n:
                return r
    return None


def to_entry(r: models.AllotmentRowORM) -> domain.AllotmentEntry:
    def safe(text, hi):
        try:
            return frozenset(parse_ranges(text, hi))
        except RangeError:
            return frozenset()   # validated on save; never let a bad cell crash verification
    return domain.AllotmentEntry(name=r.name, station_id=r.station_id or "",
                                 tags=safe(r.tag_ranges, TAG_MAX), tins=safe(r.tin_ranges, TIN_MAX),
                                 tag_text=r.tag_ranges or "", tin_text=r.tin_ranges or "")


def chart_ref(c: models.AllotmentChartORM) -> str:
    """'Secunderabad Division (RDSO-SIG0MISC(GEN)/1/2021, 2024-08-16)'."""
    extra = ", ".join(x for x in (c.reference_no, c.issued_on) if x)
    return f"{c.title} ({extra})" if extra else c.title


def station_allotment(db: Session, st: models.StationORM) -> domain.StationAllotment | None:
    rows = current_rows(db, st.workspace_id)
    if not rows:
        return None
    own = find_row(rows, st.kavach_station_id, st.name)
    ref_chart = own.chart if own is not None else rows[0].chart
    out = domain.StationAllotment(chart_ref=chart_ref(ref_chart), own=to_entry(own) if own is not None else None)
    for a in st.adjacent_stations:
        r = find_row(rows, a.kavach_station_id, a.name)
        if r is None:
            out.unmatched_adjacent.append(a.name)
        else:
            out.adjacent.append((a.name, to_entry(r)))
    return out


NEARBY_M = 50_000.0   # the longest repeat limit (block-section TINs, H2.14)


def nearby_stations(db: Session, st: models.StationORM) -> list[domain.NearbyStation]:
    """Other layouts in the workspace that the H2.14 repeat limits apply to: stations
    within 50 km of this one's centre line by chainage, and linked to it through the
    adjacent-station records (directly or via other stations). The link keeps stations
    on an unrelated route, whose chainage merely happens to coincide, out of the check."""
    if st.centre_line_m is None or st.workspace_id is None:
        return []
    others = (db.query(models.StationORM)
              .filter(models.StationORM.workspace_id == st.workspace_id, models.StationORM.id != st.id,
                      models.StationORM.centre_line_m.isnot(None)).all())
    if not others:
        return []
    by_id = {id_key(o.kavach_station_id): o for o in others if id_key(o.kavach_station_id) is not None}
    by_name = {name_key(o.name): o for o in others}

    def neighbours(s):
        for a in s.adjacent_stations:
            o = by_id.get(id_key(a.kavach_station_id)) if id_key(a.kavach_station_id) is not None else None
            o = o or by_name.get(name_key(a.name))
            if o is not None:
                yield o
    # stations that name this one as a neighbour count too (links are often recorded on one side only)
    me_id, me_name = id_key(st.kavach_station_id), name_key(st.name)
    reach = {o.id for o in others if any((id_key(a.kavach_station_id) == me_id and me_id is not None)
                                         or name_key(a.name) == me_name for a in o.adjacent_stations)}
    reach |= {o.id for o in neighbours(st)}
    todo = list(reach)
    index = {o.id: o for o in others}
    while todo:
        cur = index[todo.pop()]
        for o in neighbours(cur):
            if o.id not in reach:
                reach.add(o.id)
                todo.append(o.id)
    out = []
    for o in others:
        if o.id in reach and abs(o.centre_line_m - st.centre_line_m) <= 2 * NEARBY_M:
            out.append(domain.NearbyStation(
                name=o.name, centre_m=o.centre_line_m,
                tags=[(t.tag_ref, t.tag_number, t.location_m) for t in o.tags if t.tag_number is not None],
                tins=[(n.tin_no, n.section_type or "", min(n.start_m, n.end_m), max(n.start_m, n.end_m))
                      for n in o.tins]))
    return out
