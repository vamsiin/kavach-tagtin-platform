import { Fragment, useEffect, useState } from "react";
import type { Checklist, ChecklistChange, ChecklistRule } from "../types";
import { api } from "../api";
import { ParamEditor, paramSummary } from "./ParamEditor";

const KIND_LABELS: Record<string, string> = {
  builtin: "Built-in check",
  tag_element_distance: "Tag ↔ element distance",
  tag_spacing: "Tag spacing",
  required_field: "Required field",
  manual: "Manual checklist item",
};

function errText(e: unknown) {
  const raw = String(e).replace(/^Error:\s*/, "");
  const i = raw.indexOf("{");
  if (i >= 0) {
    try {
      const d = JSON.parse(raw.slice(i)).detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg).join("; ");
    } catch { /* ignore */ }
  }
  return raw;
}

/** BRD FR-006: configurable checklist. Everyone can view; admins edit. Every change
 *  needs a reason and is recorded in the change log; the version number goes onto
 *  verification results and reports. */
export function ChecklistPanel() {
  const [data, setData] = useState<Checklist | null>(null);
  const [changes, setChanges] = useState<ChecklistChange[]>([]);
  const [reason, setReason] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<ChecklistRule> | null>(null);
  const [adding, setAdding] = useState<Record<string, unknown> | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    setData(await api.getChecklist());
    setChanges(await api.checklistChanges());
  }
  useEffect(() => { reload().catch((e) => setError(errText(e))); }, []);

  if (!data) return <div className="panel"><p className="muted">Loading checklist…</p>{error && <div className="error">{error}</div>}</div>;
  const edit = data.can_edit;
  const noReason = !reason.trim();

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {
      await fn();
      // Clear the reason after every successful change so the next, unrelated change
      // can't silently be logged under this one's justification.
      setReason("");
      await reload();
      return true;
    } catch (e) { setError(errText(e)); return false; } finally { setBusy(false); }
  }

  const quick = (r: ChecklistRule, patch: Record<string, unknown>) => run(() => api.updateRule(r.id, { ...patch, reason }));

  function move(idx: number, dir: -1 | 1) {
    const ids = data!.rules.map((r) => r.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    run(() => api.reorderRules(ids, reason));
  }

  async function saveEdit(r: ChecklistRule) {
    if (!draft) return;
    const ok = await run(() => api.updateRule(r.id, {
      clause: draft.clause, title: draft.title, description: draft.description ?? "",
      params: draft.params, reason,
    }));
    if (ok) { setEditing(null); setDraft(null); }
  }

  async function saveNew() {
    if (!adding) return;
    const ok = await run(() => api.createRule({ ...adding, reason }));
    if (ok) setAdding(null);
  }

  const addKind = (adding?.kind as string) ?? "manual";

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <h3>Verification Checklist <span className="muted small">configuration v{data.config_version}</span></h3>
          {edit && !adding && <button onClick={() => setAdding({ kind: "manual", clause: "", title: "", description: "", severity: "FAIL", params: {}, blocking: false })}>Add rule</button>}
        </div>
        <p className="muted small">
          Applies to every station. Automated rules run on every verification, self-check and check.
          Manual items are confirmed by a reviewer during review. WARN-severity rules are reported
          but never block. {edit ? "" : "Only an admin can change this configuration."}
        </p>
        {edit && (
          <div className="inline-form">
            <input style={{ flex: 1, minWidth: 320 }} placeholder="Reason for this change (required; recorded in the change log, cleared after each change)"
              value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
        {error && <div className="error">{error}</div>}

        {adding && (
          <div className="comment-modal">
            <div className="form-grid">
              <label>Type
                <select value={addKind} onChange={(e) => setAdding({ ...adding, kind: e.target.value, params: {} })}>
                  {Object.keys(data.kinds).map((k) => <option key={k} value={k}>{KIND_LABELS[k] ?? k}</option>)}
                </select>
              </label>
              <label>Clause / code *<input value={String(adding.clause ?? "")} placeholder="e.g. QFTL-01" onChange={(e) => setAdding({ ...adding, clause: e.target.value })} /></label>
              <label>Title *<input value={String(adding.title ?? "")} onChange={(e) => setAdding({ ...adding, title: e.target.value })} /></label>
              <label>Severity
                <select value={String(adding.severity)} onChange={(e) => setAdding({ ...adding, severity: e.target.value })}>
                  <option value="FAIL">FAIL (blocks)</option><option value="WARN">WARN (report only)</option>
                </select>
              </label>
              {addKind === "manual" && (
                <label className="checkbox-label"><input type="checkbox" checked={!!adding.blocking}
                  onChange={(e) => setAdding({ ...adding, blocking: e.target.checked })} /> Must be confirmed before “Mark checked”</label>
              )}
            </div>
            <textarea rows={2} placeholder="Description (what the reviewer / rule checks)" value={String(adding.description ?? "")}
              onChange={(e) => setAdding({ ...adding, description: e.target.value })} />
            <ParamEditor schema={data.kinds[addKind] ?? []} value={(adding.params as Record<string, unknown>) ?? {}}
              onChange={(p) => setAdding({ ...adding, params: p })} />
            <div className="comment-modal-actions">
              <button disabled={busy || noReason || !String(adding.clause ?? "").trim() || !String(adding.title ?? "").trim()} onClick={saveNew}>Create rule</button>
              <button className="secondary" onClick={() => setAdding(null)}>Cancel</button>
              {noReason && <span className="muted small">Enter a reason above first.</span>}
            </div>
          </div>
        )}

        <table className="register-table checklist-table">
          <thead>
            <tr><th></th><th>On</th><th>Clause</th><th>Rule</th><th>Type</th><th>Severity</th><th>Parameters</th><th></th></tr>
          </thead>
          <tbody>
            {data.rules.map((r, i) => (
              <Fragment key={r.id}>
                <tr className={r.enabled ? "" : "row-superseded"}>
                  <td className="order-cell">
                    {edit && <>
                      <button className="icon-btn" title="Move up" disabled={busy || noReason || i === 0} onClick={() => move(i, -1)}>↑</button>
                      <button className="icon-btn" title="Move down" disabled={busy || noReason || i === data.rules.length - 1} onClick={() => move(i, 1)}>↓</button>
                    </>}
                  </td>
                  <td><input type="checkbox" checked={r.enabled} disabled={!edit || busy || noReason}
                    title={noReason ? "Enter a reason first" : ""} onChange={(e) => quick(r, { enabled: e.target.checked })} /></td>
                  <td><strong>{r.clause}</strong></td>
                  <td>{r.title}{r.description && !r.description.startsWith(r.title) && <div className="muted small">{r.description}</div>}</td>
                  <td className="small">{KIND_LABELS[r.kind] ?? r.kind}{r.kind === "manual" && r.blocking && <div><span className="badge warn">blocks check</span></div>}</td>
                  <td>
                    <select value={r.severity} disabled={!edit || busy || noReason} onChange={(e) => quick(r, { severity: e.target.value })}>
                      <option value="FAIL">FAIL</option><option value="WARN">WARN</option>
                    </select>
                  </td>
                  <td className="small">{paramSummary(r.param_schema, r.params) || "—"}</td>
                  <td className="row-actions">
                    {edit && <button className="link-btn" onClick={() => { setEditing(editing === r.id ? null : r.id); setDraft({ ...r, params: { ...r.params } }); }}>{editing === r.id ? "Close" : "Edit"}</button>}
                    {edit && r.is_builtin && <button className="link-btn" disabled={busy || noReason} onClick={() => run(() => api.resetRule(r.id, reason))}>Reset</button>}
                    {edit && !r.is_builtin && <button className="link-btn danger" disabled={busy || noReason} onClick={() => run(() => api.deleteRule(r.id, reason))}>Delete</button>}
                  </td>
                </tr>
                {editing === r.id && draft && (
                  <tr className="row-editing"><td colSpan={8}>
                    <div className="form-grid">
                      <label>Clause<input value={draft.clause ?? ""} onChange={(e) => setDraft({ ...draft, clause: e.target.value })} /></label>
                      <label>Title<input value={draft.title ?? ""} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
                      {r.kind === "manual" && (
                        <label className="checkbox-label"><input type="checkbox" checked={r.blocking} disabled={busy || noReason}
                          onChange={(e) => quick(r, { blocking: e.target.checked })} /> Must be confirmed before “Mark checked”</label>
                      )}
                    </div>
                    <textarea rows={2} value={draft.description ?? ""} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                    <ParamEditor schema={r.param_schema} value={(draft.params as Record<string, unknown>) ?? {}}
                      onChange={(p) => setDraft({ ...draft, params: p })} />
                    <div className="comment-modal-actions">
                      <button disabled={busy || noReason} onClick={() => saveEdit(r)}>Save changes</button>
                      <button className="secondary" onClick={() => { setEditing(null); setDraft(null); }}>Cancel</button>
                      {noReason && <span className="muted small">Enter a reason above first.</span>}
                      {r.updated_by && <span className="muted small">Last changed by {r.updated_by} {r.updated_at?.slice(0, 16).replace("T", " ")}</span>}
                    </div>
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <button className="link-btn" onClick={() => setShowLog(!showLog)}>{showLog ? "Hide" : "Show"} change log ({changes.filter((c) => c.action !== "seed").length} changes)</button>
        {showLog && (
          <table className="register-table">
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Rule</th><th>Reason</th><th>Change</th></tr></thead>
            <tbody>
              {changes.filter((c) => c.action !== "seed").map((c) => (
                <tr key={c.id}>
                  <td className="small">{c.changed_at.slice(0, 16).replace("T", " ")}</td>
                  <td>{c.changed_by}</td>
                  <td>{c.action}</td>
                  <td className="small">{c.rule_key ?? "—"}</td>
                  <td>{c.reason}</td>
                  <td className="small"><code>{diffText(c.before, c.after)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function diffText(before: unknown, after: unknown): string {
  if (Array.isArray(before) || Array.isArray(after)) return "order changed";
  const b = (before ?? {}) as Record<string, unknown>;
  const a = (after ?? {}) as Record<string, unknown>;
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((k) => JSON.stringify(b[k]) !== JSON.stringify(a[k]));
  return keys.map((k) => `${k}: ${JSON.stringify(b[k] ?? null)} → ${JSON.stringify(a[k] ?? null)}`).join("; ") || "—";
}
