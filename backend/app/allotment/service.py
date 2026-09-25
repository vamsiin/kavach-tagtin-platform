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
