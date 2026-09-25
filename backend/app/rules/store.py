"""DB adapter for the configurable checklist (FR-006): seeding, loading, versioning,
manual responses per review cycle."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from .checklist import RuleConfig, default_rules

CYCLE_RESET_ACTIONS = ("request_changes", "revise", "reopen")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rule_snapshot(r: models.ChecklistRuleORM) -> dict:
    return {"key": r.key, "kind": r.kind, "builtin": r.builtin, "clause": r.clause, "title": r.title,
            "description": r.description, "params": json.loads(r.params or "{}"),
            "severity": r.severity, "enabled": bool(r.enabled), "blocking": bool(r.blocking),
            "sort_order": r.sort_order, "deleted": bool(r.deleted)}


# Clause numbers corrected against Annexure H Amdt-5 (Sep 2026). Existing rule rows
# are renamed in place so admin edits, manual responses and history stay attached.
#   builtin.h2_13 (numbering ranges)  -> builtin.h2_23 / H2.23
#   builtin.h2_14 (legend shape)      -> builtin.h2_15 / H2.15
#   builtin.h2_12 (dup + tag-set)     -> split: h2_12 duplicate spacing, new h2_13 tag-set spacing
#   manual "H2.15/H2.16"              -> manual.h2_16 / H2.16
#   manual "H2.14 (25km radius)"      -> manual.h2_14 / H2.14
_RENAMES = [
    # (old key, new key, new builtin or None, old clause, new clause, old title, new title)
    ("builtin.h2_13", "builtin.h2_23", "h2_23", "H2.13", "H2.23", None, None),
    ("builtin.h2_14", "builtin.h2_15", "h2_15", "H2.14", "H2.15", None, None),
    ("manual.h2_15_h2_16", "manual.h2_16", None, "H2.15/H2.16", "H2.16", None, None),
    ("manual.h2_14__25km_radius", "manual.h2_14", None, "H2.14 (25km radius)", "H2.14", None, None),
]


def _log(db, row, action, before, reason):
    db.add(models.ChecklistChangeORM(rule_id=row.id, rule_key=row.key, action=action,
                                     before=json.dumps(before) if before else None,
                                     after=json.dumps(rule_snapshot(row)), reason=reason,
                                     changed_by="system", changed_at=now()))


def _is_pristine_seed(db: Session, row: models.ChecklistRuleORM) -> bool:
    """True if a row was only ever installed by the system: never edited, never answered."""
    if row.updated_by != "system":
        return False
    if db.query(models.ChecklistResponseORM).filter_by(rule_id=row.id).count():
        return False
    actions = {a for (a,) in db.query(models.ChecklistChangeORM.action)
               .filter(models.ChecklistChangeORM.rule_id == row.id).all()}
    return actions <= {"seed"}


def _recover_tagset(db: Session, dup: models.ChecklistRuleORM) -> float:
    """Tag-set threshold from H2.12's params, or from the snapshot logged when an
    earlier (interrupted) upgrade removed it; default 10 m."""
    params = json.loads(dup.params or "{}")
    if "tagset_min_m" in params:
        return params["tagset_min_m"]
    for c in (db.query(models.ChecklistChangeORM)
              .filter(models.ChecklistChangeORM.rule_id == dup.id)
              .order_by(models.ChecklistChangeORM.id.desc()).all()):
        before = json.loads(c.before or "{}").get("params", {})
        if "tagset_min_m" in before:
            return before["tagset_min_m"]
    return 10


def migrate_rules(db: Session) -> int:
    """Bring rule rows seeded by earlier versions up to the current clause numbering.
    Idempotent; returns the number of rows changed, added or removed. Also repairs a
    table where the new-numbered defaults were seeded before this ran: an untouched
    seeded duplicate is removed so the original row (with its edits and history) is
    renamed onto its key."""
    rows = {r.key: r for r in db.query(models.ChecklistRuleORM).all()}
    changed = 0
    reason = "Clause number corrected to Annexure H (Amdt-5)"

    for old, new, builtin, old_clause, new_clause, _, _ in _RENAMES:
        r = rows.get(old)
        if r is None:
            continue
        # builtin.h2_13 is only the old numbering rule if it still carries its params
        if old == "builtin.h2_13" and "tag_min" not in json.loads(r.params or "{}"):
            continue
        if new in rows:
            dupe = rows[new]
            if not _is_pristine_seed(db, dupe):
                continue   # both edited by people: leave for an admin to resolve
            _log(db, dupe, "migrate", rule_snapshot(dupe), f"Removed duplicate of {old} seeded during upgrade")
            db.delete(dupe)
            db.flush()
            rows.pop(new)
            changed += 1
        before = rule_snapshot(r)
        r.key = new
        if builtin:
            r.builtin = builtin
        if r.clause == old_clause:
            r.clause = new_clause
        r.updated_by, r.updated_at = "system", now()
        db.flush()
        _log(db, r, "migrate", before, reason)
        rows.pop(old)
        rows[new] = r
        changed += 1

    dup = rows.get("builtin.h2_12")
    if dup is not None:
        params = json.loads(dup.params or "{}")
        tagset = _recover_tagset(db, dup)
        if "tagset_min_m" in params:
            before = rule_snapshot(dup)
            params.pop("tagset_min_m")
            dup.params = json.dumps(params)
            if dup.title == "Duplicate and tag-set spacing":
                dup.title = "Duplicate tag pair spacing"
                dup.description = "Main and duplicate tag spacing. T and A tag pairs must be co-located."
            dup.updated_by, dup.updated_at = "system", now()
            db.flush()
            _log(db, dup, "migrate", before, "Tag-set spacing moved to its own rule, H2.13")
            changed += 1
        if "builtin.h2_13" not in rows and "builtin.h2_23" in rows:
            row = models.ChecklistRuleORM(
                key="builtin.h2_13", kind="builtin", builtin="h2_13", clause="H2.13",
                title="Tag-set to tag-set spacing",
                description="Minimum distance from one tag set to the next.",
                params=json.dumps({"tagset_min_m": tagset}), severity=dup.severity,
                enabled=dup.enabled, blocking=False, sort_order=(dup.sort_order or 0) + 5,
                updated_by="system", updated_at=now())
            db.add(row)
            db.flush()
            _log(db, row, "migrate", None, "Split from H2.12: tag-set spacing is clause H2.13")
            rows[row.key] = row
            changed += 1
    if changed:
        db.commit()
    return changed


def seed_rules(db: Session) -> int:
    """Insert any default rule whose key isn't in the table yet. Never overwrites an
    existing row -- admin edits survive upgrades. Runs migrate_rules first, so old
    rows are renamed before defaults under the new keys can be added beside them.
    Returns rows inserted."""
    migrate_rules(db)
    existing = {k for (k,) in db.query(models.ChecklistRuleORM.key).all()}
    added = 0
    for r in default_rules():
        if r.key in existing:
            continue
        row = models.ChecklistRuleORM(
            key=r.key, kind=r.kind, builtin=r.builtin, clause=r.clause, title=r.title,
            description=r.description, params=json.dumps(r.params), severity=r.severity,
            enabled=r.enabled, blocking=r.blocking, sort_order=r.sort_order,
            updated_by="system", updated_at=now())
        db.add(row)
        db.flush()
        db.add(models.ChecklistChangeORM(rule_id=row.id, rule_key=row.key, action="seed",
                                         after=json.dumps(rule_snapshot(row)),
                                         reason="Default rule installed", changed_by="system",
                                         changed_at=now()))
        added += 1
    if added:
        db.commit()
    return added


def to_config(r: models.ChecklistRuleORM) -> RuleConfig:
    return RuleConfig(key=r.key, kind=r.kind, clause=r.clause, title=r.title,
                      description=r.description or "", params=json.loads(r.params or "{}"),
                      severity=r.severity, enabled=bool(r.enabled), sort_order=r.sort_order,
                      blocking=bool(r.blocking), builtin=r.builtin, id=r.id)


def overrides_for(db: Session, workspace_id: int | None) -> dict[int, models.WorkspaceRuleOverrideORM]:
    if workspace_id is None:
        return {}
    return {o.rule_id: o for o in db.query(models.WorkspaceRuleOverrideORM).filter_by(workspace_id=workspace_id)}


def apply_override(cfg: RuleConfig, o: models.WorkspaceRuleOverrideORM | None) -> RuleConfig:
    if o is None:
        return cfg
    if o.params is not None:
        cfg.params = json.loads(o.params)
    if o.severity is not None:
        cfg.severity = o.severity
    if o.enabled is not None:
        cfg.enabled = bool(o.enabled)
    return cfg


def active_rules(db: Session, workspace_id: int | None = None) -> list[RuleConfig]:
    """The checklist as it applies in a workspace: the standard rules with that
    workspace's overrides applied (none when workspace_id is None)."""
    rows = (db.query(models.ChecklistRuleORM).filter(models.ChecklistRuleORM.deleted.isnot(True))
            .order_by(models.ChecklistRuleORM.sort_order, models.ChecklistRuleORM.id).all())
    ov = overrides_for(db, workspace_id)
    return [apply_override(to_config(r), ov.get(r.id)) for r in rows]


def rules_for_station(db: Session, station: models.StationORM) -> list[RuleConfig]:
    return active_rules(db, station.workspace_id)


def config_version(db: Session) -> int:
    return db.query(models.ChecklistChangeORM).count()


def current_cycle_event_id(db: Session, station_id: int) -> int:
    ev = (db.query(models.WorkflowEventORM)
          .filter(models.WorkflowEventORM.station_id == station_id,
                  models.WorkflowEventORM.action.in_(CYCLE_RESET_ACTIONS))
          .order_by(models.WorkflowEventORM.id.desc()).first())
    return ev.id if ev else 0


def manual_items(db: Session, station_id: int) -> list[dict]:
    """Enabled manual rules with this station's CURRENT-cycle response (if any)."""
    cycle = current_cycle_event_id(db, station_id)
    st = db.get(models.StationORM, station_id)
    rules = [r for r in active_rules(db, st.workspace_id if st else None) if r.kind == "manual" and r.enabled]
    latest: dict[int, models.ChecklistResponseORM] = {}
    for resp in (db.query(models.ChecklistResponseORM)
                 .filter_by(station_id=station_id, cycle_event_id=cycle)
                 .order_by(models.ChecklistResponseORM.id).all()):
        latest[resp.rule_id] = resp
    out = []
    for r in rules:
        resp = latest.get(r.id)
        out.append({"rule": r, "response": resp})
    return out


def manual_summary(db: Session, station_id: int) -> dict:
    items = manual_items(db, station_id)
    pending_blocking = [i["rule"].clause for i in items
                        if i["rule"].blocking and i["response"] is None]
    failed = [i["rule"].clause for i in items if i["response"] is not None and i["response"].status == "FAIL"]
    return {"total": len(items),
            "answered": sum(1 for i in items if i["response"] is not None),
            "pending_blocking": pending_blocking,
            "failed": failed}
