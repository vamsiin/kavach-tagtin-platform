"""Station-specific deviations from automated checks -- see models.CheckDeviationORM."""
from __future__ import annotations

from ..rules.engine import VerificationReport


def _key(clause: str, subject_ref: str | None) -> tuple[str, str]:
    return (clause.strip().upper(), (subject_ref or "").strip().upper())


def apply(report: VerificationReport, deviations) -> list:
    """Turn every FAIL that has a recorded deviation into DEVIATION (message carries the
    reason). Returns the deviations that matched no failing result -- the layout has
    changed and they are no longer needed."""
    by = {_key(d.clause, d.subject_ref): d for d in deviations}
    used = set()
    for r in report.results:
        if r.status != "FAIL":
            continue
        d = by.get(_key(r.clause, r.subject_ref))
        if d is None:
            continue
        used.add(d.id)
        r.status = "DEVIATION"
        ref = f" [{d.reference}]" if d.reference else ""
        r.message = (f"{r.message} -- accepted as a station deviation: {d.reason}{ref} "
                     f"({d.created_by}, {d.created_at[:10]})")
    return [d for d in deviations if d.id not in used]


def station_report(db, st, report: VerificationReport) -> VerificationReport:
    apply(report, list(st.deviations))
    return report
