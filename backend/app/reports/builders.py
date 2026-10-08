"""
The eight BRD Section 11 reports, each built as a format-neutral `Report`
(see model.py). Data is always read fresh from the DB at generation time; reports
that must be frozen (verification evidence at a workflow step) are archived as files
by the router instead of being regenerated later.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from ..chainage import movement_text
from ..domain import guess_line_type
from ..documents import service as docsvc
from ..observations import rules as obsrules
from ..rules import store
from ..rules.engine import run_all_checks
from .model import (Banner, Bullets, Heading, KeyValues, PageBreak, Para, Report,
                    SignOff, Table)

STATUS_LABELS = {
    "draft": "Draft", "self_checked": "Self-checked", "submitted": "Submitted for check",
    "checked": "Checked", "approved": "Approved", "railway_submitted": "Submitted to Railway",
}
ACTION_LABELS = {
    "self_check": "Self-check", "revise": "Revise", "submit": "Submit for check",
    "request_changes": "Request changes (rework)", "check": "Mark checked", "reassign": "Reassign checker",
    "approve": "Approve", "railway_submit": "Railway submission", "reopen": "Reopen",
}

REPORT_TYPES: dict[str, dict] = {
    "layout": {"title": "Layout Report", "abbr": "LAY",
               "description": "Station particulars, design inputs and the full Element, Tag and TIN registers."},
    "verification": {"title": "Verification Report", "abbr": "VER",
                     "description": "Annexure-H automated check results item by item, manual-review clauses and sign-off."},
    "compliance": {"title": "Compliance Report", "abbr": "CMP",
                   "description": "Clause-by-clause compliance summary, including clauses that need manual review."},
    "observations": {"title": "Observation Report", "abbr": "OBS",
                     "description": "All review observations with status, resolution and full comment threads."},
    "approval": {"title": "Approval Status Report", "abbr": "APR",
                 "description": "Where the layout is in the lifecycle, who did each step, and what is blocking the next."},
    "audit": {"title": "Audit Trail Report", "abbr": "AUD",
              "description": "Every workflow transition, observation action and input upload in time order."},
    "traceability": {"title": "Traceability Matrix", "abbr": "TRC",
                     "description": "Input document revision -> register row -> workflow step, with gaps."},
    "revisions": {"title": "Revision History Report", "abbr": "REV",
                  "description": "Recorded drawing revisions, layout versions at each workflow step, input revisions and Railway submissions."},
}
WIDE_REPORTS = {"layout", "audit", "traceability", "observations"}


def _d(iso: str | None) -> str:
    return (iso or "")[:16].replace("T", " ") or "-"


def _fmt_m(v) -> str:
    if v is None:
        return "-"
    return f"{v:g}"


@dataclass
class Ctx:
    station: models.StationORM
    elements: list
    tags: list
    tins: list
    docs: list
    events: list
    observations: list
    railway: list
    revisions: list
    user: models.UserORM
    now: str
    rules: list          # FR-006 active checklist (RuleConfig)
    manual: list         # [{"rule": RuleConfig, "response": ChecklistResponseORM|None}]
    checklist_version: int
    changes: list        # StationChangeORM (versions, designer assignment)
    baselines: list      # BaselineORM

    @property
    def el_by_id(self):
        return {e.id: e for e in self.elements}

    @property
    def doc_by_id(self):
        return {d.id: d for d in self.docs}


def load_ctx(db: Session, station: models.StationORM, user: models.UserORM) -> Ctx:
    sid = station.id
    q = lambda mdl, order: db.query(mdl).filter_by(station_id=sid).order_by(order).all()  # noqa: E731
    return Ctx(
        station=station,
        elements=q(models.ElementORM, models.ElementORM.location_m),
        tags=q(models.TagORM, models.TagORM.location_m),
        tins=q(models.TINORM, models.TINORM.start_m),
        docs=q(models.InputDocumentORM, models.InputDocumentORM.id),
        events=q(models.WorkflowEventORM, models.WorkflowEventORM.id),
        observations=q(models.ObservationORM, models.ObservationORM.obs_no),
        railway=q(models.RailwaySubmissionORM, models.RailwaySubmissionORM.id),
        revisions=q(models.RevisionORM, models.RevisionORM.id),
        user=user, now=datetime.now(timezone.utc).isoformat(),
        rules=store.active_rules(db, station.workspace_id), manual=store.manual_items(db, sid),
        checklist_version=store.config_version(db),
        changes=q(models.StationChangeORM, models.StationChangeORM.id),
        baselines=q(models.BaselineORM, models.BaselineORM.id),
    )


def _new(ctx: Ctx, code: str) -> Report:
    meta = REPORT_TYPES[code]
    st = ctx.station
    stamp = ctx.now[:16].replace("-", "").replace(":", "").replace("T", "-")
    return Report(
        code=code, title=meta["title"], station_name=st.name, station_code=st.kavach_station_id,
        layout_version=st.layout_version, station_status=STATUS_LABELS.get(st.status, st.status),
        generated_by=f"{ctx.user.full_name} ({ctx.user.username})", generated_at=ctx.now,
        report_id=f"KVR-{st.kavach_station_id}-{meta['abbr']}-{stamp}",
    )


def _verify(ctx: Ctx):
    from ..deviations import apply as apply_deviations
    rep = run_all_checks(ctx.station.to_domain(), [e.to_domain() for e in ctx.elements],
                         [t.to_domain() for t in ctx.tags], [n.to_domain() for n in ctx.tins],
                         rules=ctx.rules)
    apply_deviations(rep, list(ctx.station.deviations))
    return rep


def _manual_rows(ctx: Ctx) -> list[list[str]]:
    rows = []
    for i in ctx.manual:
        r, resp = i["rule"], i["response"]
        rows.append([r.clause, r.description or r.title,
                     "Yes" if r.blocking else "No",
                     resp.status if resp else "PENDING",
                     f"{resp.responded_by} {_d(resp.responded_at)}" + (f"\n{resp.note}" if resp.note else "")
                     if resp else "-"])
    return rows


def _cycle_actor(ctx: Ctx, action: str) -> tuple[str, str]:
    """Latest actor/date for an action in the CURRENT cycle (after the last rework/reopen)."""
    actor, when = "", ""
    for e in ctx.events:
        if e.action in ("request_changes", "revise", "reopen"):
            actor, when = "", ""
        if e.action == action:
            actor, when = e.actor_username, _d(e.timestamp)[:10]
    return actor, when


def _station_kv(ctx: Ctx) -> KeyValues:
    st = ctx.station
    return KeyValues([
        ("Station name", st.name), ("KAVACH station ID", st.kavach_station_id),
        ("Workspace (zone)", f"{st.workspace.code} - {st.workspace.name} (SIP Down = {st.workspace.dn_direction})"
         if st.workspace is not None else "-"),
        ("SIP drawing no.", st.sip_drawing_number or "-"),
        ("Versions (KAVACH / SIP / Guideline)",
         f"{st.kavach_version or '-'} / {st.sip_version or '-'} / {st.guideline_version or '-'}"),
        ("Drawn to scale", "Yes" if st.drawn_to_scale else "No"),
        ("Created by", st.created_by or "-"),
    ])


def _inputs_table(ctx: Ctx, current_only=True) -> Table:
    current = {d.id for d in _current_docs(ctx).values()}
    rows = [[docsvc.DOC_TYPES.get(d.doc_type, {}).get("label", d.doc_type), str(d.revision),
             d.version_label or "-", d.original_filename, d.uploaded_by, _d(d.uploaded_at),
             d.sha256[:12], "Current" if d.id in current else "Superseded"]
            for d in ctx.docs if (d.id in current or not current_only)]
    return Table(["Input", "Rev", "Label", "File", "Uploaded by", "Uploaded", "SHA-256", "State"], rows,
                 widths=[2.2, 0.6, 1.5, 2.5, 1.2, 1.4, 1.2, 1], empty_text="No design inputs uploaded.")


def _current_docs(ctx: Ctx) -> dict:
    latest = {}
    for d in sorted(ctx.docs, key=lambda x: x.revision):
        latest[d.doc_type] = d
    return latest


def _src(ctx: Ctx, doc_id) -> str:
    d = ctx.doc_by_id.get(doc_id)
    return f"{d.doc_type} r{d.revision}" if d else "-"


# ---------------------------------------------------------------------------
def build_layout(ctx: Ctx) -> Report:
    r = _new(ctx, "layout")
    st = ctx.station
    lines = {t.id: t.name for t in st.tracks}
    line = lambda tid: lines.get(tid, "-") if tid is not None else "-"
    r.add(Heading("1. Station particulars"), _station_kv(ctx),
          Para("All locations are chainage in metres (e.g. 262910 = km 262.910).", "muted"),
          Heading("2. Design inputs"), _inputs_table(ctx))
    r.add(Heading("3. Lines and neighbouring stations"),
          KeyValues([("Station centre line (H2.28)",
                      _fmt_m(st.centre_line_m) if st.centre_line_m is not None else "Not recorded")]),
          Para("From / Start is always the lower chainage and To / End the higher one; the direction "
               "of movement is given separately (Nominal = lower to higher, Reverse = higher to lower).",
               "muted"),
          Table(["Line", "Line type", "Kind", "From / Start (m)", "To / End (m)", "Length (m)", "Direction",
                 "Movement (km)", "KAVACH"],
                [[t.name, t.line_type or guess_line_type(t.name), t.track_type, _fmt_m(t.start_m), _fmt_m(t.end_m), _fmt_m(t.end_m - t.start_m),
                  t.direction or "-", movement_text(t.start_m, t.end_m, t.direction),
                  "Yes" if t.is_kavach is not False else "No (white)"] for t in st.tracks],
                empty_text="No lines recorded."),
          Table(["Adjacent station", "KAVACH ID", "Side", "Line-wise border mapping (H2.16)", "Distance (m)",
                 "Section"],
                [[a.name, a.kavach_station_id or "-", a.side,
                  "; ".join(f"{b.line_label}" + (f" -> {b.neighbour_line}" if b.neighbour_line else "")
                            + f" at {_fmt_m(b.border_m)}" + (f" ({b.border_tag_ref})" if b.border_tag_ref else "")
                            for b in a.borders) if a.borders else
                  (_fmt_m(a.border_m) if a.border_m is not None else "Not recorded"),
                  _fmt_m(a.distance_m) if a.distance_m is not None else "-", a.line_config or "-"]
                 for a in st.adjacent_stations],
                empty_text="No adjacent stations recorded."))

    def el_detail(e):
        if e.to_track_id is not None:
            return f"to {line(e.to_track_id)}"
        if e.lc_class or e.lc_manning:
            return ", ".join(x for x in (f"Class {e.lc_class}" if e.lc_class else "", e.lc_manning or "") if x)
        return ""
    r.add(Heading(f"4. Element register ({len(ctx.elements)})"),
          Table(["Ref", "Type", "Chainage (m)", "Line", "Dir", "Details", "Source", "Remarks"],
                [[e.element_ref, e.element_type, _fmt_m(e.location_m), line(e.track_id), e.direction or "-",
                  el_detail(e) or "-", _src(ctx, e.source_document_id), e.remarks or ""] for e in ctx.elements],
                widths=[1, 2.6, 1.1, 1.1, 0.7, 1.3, 1.1, 2], empty_text="No elements."))
    els = ctx.el_by_id
    r.add(Heading(f"5. Tag register ({len(ctx.tags)})"),
          Table(["Ref", "No.", "Type", "Chainage (m)", "Line", "Dir", "Linked element", "TIN", "Pair grp",
                 "Dup", "Border", "Legend", "Source"],
                [[t.tag_ref, str(t.tag_number) if t.tag_number is not None else "-", t.tag_type,
                  _fmt_m(t.location_m), line(t.track_id), t.direction or "-",
                  els[t.linked_element_id].element_ref if t.linked_element_id in els else "-",
                  str(t.tin_no) if t.tin_no is not None else "-", t.pair_group_id or "-",
                  "Yes" if t.is_duplicate else "-", "Yes" if t.is_border_tag else "-",
                  t.legend_shape or "-", _src(ctx, t.source_document_id)] for t in ctx.tags],
                widths=[1, 0.6, 0.5, 1.1, 1, 0.8, 1.2, 0.5, 0.8, 0.5, 0.6, 0.9, 1.1], empty_text="No tags."))
    r.add(Heading(f"6. TIN register ({len(ctx.tins)})"),
          Table(["TIN", "Section", "Line", "Colour", "From / Start (m)", "To / End (m)", "Length (m)", "Direction",
                 "Non-KAVACH", "Source"],
                [[str(n.tin_no), n.section_type, line(n.track_id), n.color or "-", _fmt_m(n.start_m),
                  _fmt_m(n.end_m), _fmt_m(abs((n.end_m or 0) - (n.start_m or 0))), n.direction or "-",
                  "Yes" if n.is_non_kavach_territory else "No", _src(ctx, n.source_document_id)]
                 for n in ctx.tins], empty_text="No TINs."))
    counts = Counter(t.tag_type for t in ctx.tags)
    r.add(Heading("7. Summary"), KeyValues(
        [("Lines", str(len(st.tracks))), ("Adjacent stations", str(len(st.adjacent_stations))),
         ("Elements", str(len(ctx.elements))), ("Tags", str(len(ctx.tags))),
         ("Tags by type", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "-"),
         ("TINs", str(len(ctx.tins)))]))
    return r


def build_verification(ctx: Ctx) -> Report:
    r = _new(ctx, "verification")
    rep = _verify(ctx)
    s = rep.summary()
    ok = rep.fail_count == 0
    r.add(Banner(f"All {s['total_checks']} automated checks passed"
                 + (f" ({rep.warn_count} warning(s))" if rep.warn_count else "")
                 + (f"; {s['deviation_count']} accepted as station deviation(s)" if s.get("deviation_count") else "")
                 if ok else f"{rep.fail_count} of {s['total_checks']} automated checks FAILED "
                 f"- clauses {', '.join(s['clauses_failing'])}", "ok" if ok and not rep.warn_count
                 else "warn" if ok else "fail"))
    r.add(Heading("1. Basis"), KeyValues([
        ("Standard", "RDSO/SPN/196/2020 Annexure-H (Amdt-5) and BRD FR-004"),
        ("Checks run", str(s["total_checks"])),
        ("Failures / warnings", f"{rep.fail_count} / {rep.warn_count}"),
        ("Accepted station deviations", str(s.get("deviation_count", 0))),
        ("Clauses checked", ", ".join(s["clauses_checked"]) or "-"),
        ("Registers", f"{len(ctx.elements)} elements, {len(ctx.tags)} tags, {len(ctx.tins)} TINs"),
        ("Checklist configuration", f"version {ctx.checklist_version}"),
        ("Automated rules switched off", ", ".join(f"{r.clause} {r.title}" for r in ctx.rules
                                                 if not r.enabled and r.kind != "manual") or "None"),
    ]))
    r.add(Heading("2. Results"),
          Table(["Clause", "Check", "Result", "Subject", "Detail"],
                [[x.clause, x.title, x.status, x.subject_ref or "-", x.message]
                 for x in sorted(rep.results, key=lambda x: (x.status == "PASS", x.clause))],
                widths=[1.15, 2.2, 0.8, 1, 4], status_col=2, empty_text="No checks produced results."))
    r.add(Heading("3. Manual checklist (current review cycle)"),
          Para("Items that cannot be automated; confirmed by a reviewer on the drawing.", "muted"),
          Table(["Clause", "What must be checked by hand", "Blocking", "Result", "Confirmed by"],
                _manual_rows(ctx), widths=[1.1, 4.2, 0.8, 0.9, 1.8], status_col=3,
                empty_text="No manual checklist items are enabled."))
    open_obs = [o for o in ctx.observations if o.status in obsrules.UNRESOLVED + obsrules.UNVERIFIED]
    r.add(Heading("4. Open review observations"),
          Table(["No.", "Severity", "Status", "Observation"],
                [[f"OBS-{o.obs_no:03d}", o.severity, o.status.upper(), o.description] for o in open_obs],
                widths=[0.8, 0.8, 1, 6], status_col=2, empty_text="None."))
    sc, scd = _cycle_actor(ctx, "self_check")
    ck, ckd = _cycle_actor(ctx, "check")
    r.add(Heading("5. Sign-off"), SignOff([("Designer (self-check)", sc, scd),
                                           ("Checker", ck, ckd)]))
    return r


def build_compliance(ctx: Ctx) -> Report:
    r = _new(ctx, "compliance")
    rep = _verify(ctx)
    by = {}
    for x in rep.results:
        c = by.setdefault(x.clause, {"title": x.title, "PASS": 0, "FAIL": 0, "WARN": 0, "NA": 0})
        c[x.status] = c.get(x.status, 0) + 1
    rows = []
    for clause in sorted(by):
        c = by[clause]
        verdict = ("FAIL" if c["FAIL"] else "WARN" if c["WARN"] else
                   "DEVIATION" if c.get("DEVIATION") else "PASS")
        rows.append([clause, c["title"], verdict, str(c["PASS"]), str(c["FAIL"]), str(c["WARN"])])
    for i in ctx.manual:
        mr, resp = i["rule"], i["response"]
        text = mr.description or mr.title
        verdict = resp.status if resp and resp.status != "NA" else ("NA" if resp else "MANUAL")
        rows.append([mr.clause, text[:110] + ("..." if len(text) > 110 else ""), verdict,
                     "1" if resp and resp.status == "PASS" else "-",
                     "1" if resp and resp.status == "FAIL" else "-", "-"])
    compliant = sum(1 for x in rows if x[2] == "PASS")
    failing = [x[0] for x in rows if x[2] == "FAIL"]
    r.add(Banner(f"{len(failing)} clause(s) non-compliant: {', '.join(failing)}" if failing
                 else f"All {compliant} checked clauses compliant; "
                      f"{sum(1 for x in rows if x[2] == 'MANUAL')} manual item(s) awaiting confirmation",
                 "fail" if failing else "ok"))
    r.add(Para(f"Checklist configuration version {ctx.checklist_version}.", "muted"),
          Heading("1. Clause compliance matrix"),
          Table(["Clause", "Requirement", "Verdict", "Pass", "Fail", "Warn"], rows,
                widths=[1.1, 4.5, 0.9, 0.6, 0.6, 0.6], status_col=2))
    missing = [docsvc.DOC_TYPES[c]["label"] for c in docsvc.REQUIRED_DOC_TYPES if c not in _current_docs(ctx)]
    r.add(Heading("2. BRD input & process compliance"), Table(
        ["Requirement", "Status", "Detail"],
        [["FR-001 required inputs uploaded", "FAIL" if missing else "PASS",
          ("Missing: " + ", ".join(missing)) if missing else "SIP, Site Survey, Allocation Chart present"],
         ["FR-011 tags traced to an input", "PASS" if all(t.source_document_id for t in ctx.tags) and ctx.tags
          else "WARN", f"{sum(1 for t in ctx.tags if t.source_document_id)}/{len(ctx.tags)} tags traced"],
         ["FR-008 review observations closed",
          "PASS" if not any(o.status in obsrules.UNRESOLVED + obsrules.UNVERIFIED and o.severity != "info"
                            for o in ctx.observations) else "FAIL",
          f"{sum(1 for o in ctx.observations if o.status == 'closed')} closed, "
          f"{sum(1 for o in ctx.observations if o.status in obsrules.UNRESOLVED)} open, "
          f"{sum(1 for o in ctx.observations if o.status in obsrules.UNVERIFIED)} awaiting verification"],
         ["FR-010 layout version complete", "FAIL" if ctx.station.layout_version == "INCOMPLETE" else "PASS",
          ctx.station.layout_version]],
        widths=[2.5, 0.9, 4], status_col=1))
    return r


def build_observations(ctx: Ctx) -> Report:
    r = _new(ctx, "observations")
    c = Counter(o.status for o in ctx.observations)
    blocking = obsrules.blocking_counts([(o.status, o.severity) for o in ctx.observations])
    r.add(Banner(f"{blocking['unresolved']} open, {blocking['unverified']} awaiting verification "
                 f"(blocking); {c.get('closed', 0)} closed; {c.get('withdrawn', 0)} withdrawn",
                 "fail" if blocking["unresolved"] else "warn" if blocking["unverified"] else "ok"))
    r.add(Heading("1. Register of observations"),
          Table(["No.", "Severity", "Status", "Clause", "About", "Observation", "Raised", "Resolved", "Closed"],
                [[f"OBS-{o.obs_no:03d}", o.severity, o.status.upper(), o.clause or "-",
                  "Layout" if o.subject_kind == "station" else f"{o.subject_kind} {o.subject_ref}",
                  o.description, f"{o.raised_by}\n{_d(o.raised_at)}",
                  f"{o.resolved_by}\n{_d(o.resolved_at)}" if o.resolved_by else "-",
                  f"{o.closed_by}\n{_d(o.closed_at)}" if o.closed_by else "-"] for o in ctx.observations],
                widths=[0.8, 0.7, 0.9, 0.7, 1.1, 3.6, 1.2, 1.2, 1.2], status_col=2,
                empty_text="No observations have been raised."))
    if ctx.observations:
        r.add(Heading("2. Threads"))
        for o in ctx.observations:
            r.add(Heading(f"OBS-{o.obs_no:03d} - {o.status.upper()} - {o.severity}", 2),
                  Table(["When", "Who", "Action", "Text"],
                        [[_d(cm.created_at), f"{cm.author} ({cm.author_role})",
                          cm.action + (f" -> {cm.to_status}" if cm.to_status and cm.to_status != cm.from_status else ""),
                          cm.text or ""] for cm in o.comments], widths=[1.2, 1.5, 1.5, 5]))
    return r


def build_approval(ctx: Ctx) -> Report:
    r = _new(ctx, "approval")
    st = ctx.station
    order = ["draft", "self_checked", "submitted", "checked", "approved", "railway_submitted"]
    cur = order.index(st.status) if st.status in order else 0
    rows = []
    for i, s in enumerate(order):
        state = "DONE" if i < cur else "CURRENT" if i == cur else "PENDING"
        rows.append([STATUS_LABELS[s], state])
    r.add(Banner(f"Current status: {STATUS_LABELS.get(st.status, st.status)}",
                 "ok" if st.status in ("approved", "railway_submitted") else "info"))
    from ..routers.workflow import _load_workflow_state
    from sqlalchemy.orm import object_session
    state = _load_workflow_state(st, object_session(st))
    r.add(Heading("1. Lifecycle position"), Table(["Stage", "State"], rows, widths=[3, 1.2]),
          KeyValues([("Assigned designer", st.assigned_designer or "Any designer (not assigned)"),
                     ("Assigned checker", state.assigned_checker or "-")]))
    steps = [("Self-check (Designer)", "self_check"), ("Submitted for check", "submit"),
             ("Checked (Checker)", "check"), ("Approved (Approver)", "approve"),
             ("Railway submission", "railway_submit")]
    r.add(Heading("2. Sign-offs in the current cycle"),
          Table(["Step", "By", "Date"], [[lbl, *(x or "-" for x in _cycle_actor(ctx, a))] for lbl, a in steps],
                widths=[3, 2, 1.5]))
    rep = _verify(ctx)
    blocking = obsrules.blocking_counts([(o.status, o.severity) for o in ctx.observations])
    missing = [docsvc.DOC_TYPES[c]["label"] for c in docsvc.REQUIRED_DOC_TYPES if c not in _current_docs(ctx)]
    gates = [
        ["Automated verification", "PASS" if rep.fail_count == 0 else "FAIL",
         f"{rep.fail_count} failing check(s)"],
        ["Open observations", "PASS" if not blocking["unresolved"] else "FAIL", str(blocking["unresolved"])],
        ["Observations awaiting verification", "PASS" if not blocking["unverified"] else "WARN",
         str(blocking["unverified"])],
        ["Layout version complete", "PASS" if st.layout_version != "INCOMPLETE" else "FAIL", st.layout_version],
        ["Required inputs uploaded", "PASS" if not missing else "WARN", ", ".join(missing) or "All present"],
    ]
    r.add(Heading("3. Gates for the next step"), Table(["Gate", "Status", "Detail"], gates,
                                                       widths=[2.5, 0.9, 3], status_col=1))
    r.add(Heading("4. Railway submissions"),
          Table(["Reference", "Date sent", "Addressed to", "Layout", "Recorded by"],
                [[x.reference_no, x.submitted_on, x.addressed_to or "-", x.layout_version,
                  f"{x.recorded_by} {_d(x.recorded_at)}"] for x in ctx.railway],
                empty_text="Not yet submitted to the Railway."))
    return r


def build_audit(ctx: Ctx) -> Report:
    r = _new(ctx, "audit")
    rows = []
    for e in ctx.events:
        parts = []
        if e.verification_fail_count is not None:
            parts.append(f"verification fails: {e.verification_fail_count}")
        if e.target_username:
            parts.append(f"assigned to {e.target_username}")
        if e.comment:
            parts.append(e.comment)
        detail = "; ".join(parts)
        rows.append((e.timestamp, "Workflow", f"{e.actor_username} ({e.actor_role})",
                     f"{ACTION_LABELS.get(e.action, e.action)}: {STATUS_LABELS.get(e.from_status, e.from_status)}"
                     f" -> {STATUS_LABELS.get(e.to_status, e.to_status)}", detail))
    for o in ctx.observations:
        for cm in o.comments:
            rows.append((cm.created_at, "Observation", f"{cm.author} ({cm.author_role})",
                         f"OBS-{o.obs_no:03d} {cm.action}" + (f" -> {cm.to_status}" if cm.to_status and cm.to_status != cm.from_status else ""),
                         cm.text or ""))
    for d in ctx.docs:
        rows.append((d.uploaded_at, "Input", d.uploaded_by,
                     f"Uploaded {d.doc_type} rev {d.revision}", f"{d.original_filename} (sha256 {d.sha256[:12]})"))
    for x in ctx.railway:
        rows.append((x.recorded_at, "Railway", x.recorded_by, f"Submission {x.reference_no}",
                     f"sent {x.submitted_on} to {x.addressed_to or '-'}"))
    for c in ctx.changes:
        rows.append((c.changed_at, "Configuration", f"{c.changed_by} ({c.changed_by_role})",
                     f"{c.field}: {c.before or '-'} -> {c.after or '-'}", c.reason or ""))
    for b in ctx.baselines:
        rows.append((b.created_at, "Baseline", b.created_by, f"Baseline '{b.label}' of layout {b.layout_version}",
                     b.notes or ""))
    rows.sort(key=lambda x: x[0] or "")
    r.add(Para(f"{len(rows)} recorded event(s). Times are UTC.", "muted"),
          Table(["When (UTC)", "Area", "Who", "What", "Detail"],
                [[_d(a), b, c, d, e] for a, b, c, d, e in rows],
                widths=[1.3, 1, 1.6, 3, 3.5], empty_text="No events recorded."))
    return r


def build_traceability(ctx: Ctx, trace) -> Report:
    r = _new(ctx, "traceability")
    s = trace.summary
    r.add(Banner("No traceability gaps" if not trace.gaps else f"{len(trace.gaps)} traceability gap(s)",
                 "ok" if not trace.gaps else "warn"))
    if trace.gaps:
        r.add(Bullets(trace.gaps))
    r.add(KeyValues([("Tags traced", f"{s['tags_traced']}/{s['tags']}"),
                     ("Elements traced", f"{s['elements_traced']}/{s['elements']}"),
                     ("Rows on superseded inputs", str(s["rows_on_superseded_inputs"]))]))
    r.add(Heading("1. Design inputs (all revisions)"), _inputs_table(ctx, current_only=False))
    r.add(Heading("2. Register -> source input"),
          Table(["Kind", "Ref", "Type", "Chainage (m)", "Linked element", "Source input", "State"],
                [[x.kind, x.ref, x.type or "-", _fmt_m(x.location_m), x.linked_element_ref or "-",
                  (f"{x.source.doc_type} rev {x.source.revision} - {x.source.original_filename}"
                   if x.source else "none"),
                  "MISSING" if not x.source else "SUPERSEDED" if x.source_outdated else "PASS"]
                 for x in trace.rows], widths=[0.8, 1, 1.8, 1.2, 1.2, 3.4, 1.1], status_col=6))
    r.add(Heading("3. Workflow step -> input package in force"),
          Table(["When", "Action", "By", "Layout", "Inputs in force"],
                [[_d(e.timestamp), ACTION_LABELS.get(e.action, e.action), e.actor_username,
                  e.layout_version or "-",
                  "not recorded" if e.input_snapshot is None else
                  ", ".join(f"{i['doc_type']} r{i['revision']}" for i in e.input_snapshot) or "none uploaded"]
                 for e in trace.workflow], widths=[1.3, 1.6, 1.2, 0.9, 4.5], empty_text="No workflow events."))
    return r


def build_revisions(ctx: Ctx) -> Report:
    r = _new(ctx, "revisions")
    r.add(Heading("1. Drawing revision table"),
          Table(["Rev", "Date", "Description", "Layout", "Recorded by"],
                [[x.rev_no, x.date or "-", x.description, x.layout_version or "-",
                  f"{x.created_by or '-'} {_d(x.created_at)}"] for x in ctx.revisions],
                widths=[0.7, 1.1, 4.5, 0.9, 1.8], empty_text="No revision entries recorded yet."))
    milestones = [[_d(e.timestamp), ACTION_LABELS.get(e.action, e.action), e.layout_version or "-",
                   e.actor_username, e.comment or ""]
                  for e in ctx.events if e.action in ("approve", "railway_submit", "reopen", "request_changes", "reassign")]
    r.add(Heading("2. Layout versions at key workflow steps"),
          Para("Layout version = KAVACH.SIP.Guideline (FR-010). Steps before Phase 4 did not record it.", "muted"),
          Table(["When", "Step", "Layout", "By", "Comment"], milestones,
                widths=[1.3, 1.8, 0.9, 1.2, 3.8], empty_text="No approvals, reworks or submissions yet."))
    vch = [c for c in ctx.changes if c.field in ("kavach_version", "sip_version", "guideline_version",
                                                 "sip_drawing_number")]
    r.add(Heading("3. Version number changes (Configuration Manager)"),
          Table(["When", "Field", "From", "To", "By", "Reason"],
                [[_d(c.changed_at), c.field, c.before or "-", c.after or "-", c.changed_by, c.reason or ""]
                 for c in vch], widths=[1.3, 1.5, 0.8, 0.8, 1.1, 3.5], empty_text="No version changes recorded."))
    r.add(Heading("4. Baselines"),
          Table(["Label", "Layout", "Status", "Checklist", "Created", "Notes"],
                [[b.label, b.layout_version, STATUS_LABELS.get(b.station_status, b.station_status),
                  f"v{b.checklist_version}", f"{b.created_by} {_d(b.created_at)}", b.notes or ""]
                 for b in ctx.baselines], widths=[1.4, 0.8, 1.3, 0.8, 1.8, 3], empty_text="No baselines."))
    r.add(Heading("5. Design input revisions"), _inputs_table(ctx, current_only=False))
    r.add(Heading("6. Railway submissions"),
          Table(["Reference", "Date sent", "Layout", "Package"],
                [[x.reference_no, x.submitted_on, x.layout_version, _package(x)] for x in ctx.railway],
                widths=[2, 1.2, 0.9, 4], empty_text="None."))
    return r


def _package(x) -> str:
    try:
        snap = json.loads(x.layout_snapshot)
        return (f"{len(snap.get('elements', []))} elements, {len(snap.get('tags', []))} tags, "
                f"{len(snap.get('tins', []))} TINs")
    except (ValueError, TypeError):
        return "-"


BUILDERS = {
    "layout": build_layout, "verification": build_verification, "compliance": build_compliance,
    "observations": build_observations, "approval": build_approval, "audit": build_audit,
    "revisions": build_revisions,
    # "traceability" needs the traceability payload -- built in the router
}
