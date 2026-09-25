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


def seed_rules(db: Session) -> int:
    """Insert any default rule whose key isn't in the table yet. Never overwrites an
    existing row -- admin edits survive upgrades. Returns rows inserted."""
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


def active_rules(db: Session) -> list[RuleConfig]:
    rows = (db.query(models.ChecklistRuleORM).filter(models.ChecklistRuleORM.deleted.isnot(True))
            .order_by(models.ChecklistRuleORM.sort_order, models.ChecklistRuleORM.id).all())
    return [to_config(r) for r in rows]


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
    rules = [r for r in active_rules(db) if r.kind == "manual" and r.enabled]
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
