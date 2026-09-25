import { useEffect, useState } from "react";
import type { Baseline, BaselineDiff, Station, StationChange } from "../types";
import { STATUS_LABELS, ROLE_LABELS } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";
import { useWorkspace } from "../workspace/WorkspaceContext";

interface Props {
  station: Station;
  onStationChanged: (s: Station) => void;
}

function when(iso: string) {
  return iso.slice(0, 16).replace("T", " ");
}

/** Configuration Manager: version numbers (FR-010), baselines of approved layouts,
 *  and comparison of the current layout against a baseline. Visible to everyone. */
export function ConfigurationPanel({ station, onStationChanged }: Props) {
  const can = useCan();
  const canVersions = can("station.versions") && station.status === "draft";
  const canBaseline = can("baseline.create") && ["approved", "railway_submitted"].includes(station.status);

  const [v, setV] = useState({ kavach_version: "", sip_version: "", guideline_version: "", sip_drawing_number: "" });
  const [reason, setReason] = useState("");
  const [changes, setChanges] = useState<StationChange[]>([]);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [diff, setDiff] = useState<BaselineDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { workspaces, byId, reload: reloadWorkspaces } = useWorkspace();
  const canMove = can("workspace.manage");
  const [moveTo, setMoveTo] = useState("");
  const [moveReason, setMoveReason] = useState("");

  async function reload() {
    setChanges(await api.stationChanges(station.id));
    setBaselines(await api.listBaselines(station.id));
  }
  useEffect(() => {
    setV({ kavach_version: station.kavach_version ?? "", sip_version: station.sip_version ?? "",
           guideline_version: station.guideline_version ?? "", sip_drawing_number: station.sip_drawing_number ?? "" });
    setDiff(null);
    reload().catch((e) => setError(String(e)));
  }, [station.id, station.status, station.layout_version]);

  async function saveVersions() {
    setError(null);
    try {
      onStationChanged(await api.updateVersions(station.id, { ...v, reason }));
      setReason("");
      await reload();
    } catch (e) { setError(String(e)); }
  }

  async function makeBaseline() {
    setError(null);
    try { await api.createBaseline(station.id, label, notes); setLabel(""); setNotes(""); await reload(); }
    catch (e) { setError(String(e)); }
  }

  async function move() {
    setError(null);
    try {
      onStationChanged(await api.moveStation(station.id, Number(moveTo), moveReason));
      setMoveTo(""); setMoveReason("");
      await reload(); await reloadWorkspaces();
    } catch (e) { setError(String(e)); }
  }

  const ws = byId(station.workspace_id);
  const preview = `${v.kavach_version || "?"}.${v.sip_version || "?"}.${v.guideline_version || "?"}`;

  return (
    <>
      <div className="panel">
        <h3>Workspace <span className="muted small">railway zone</span></h3>
        <p>
          <strong>{ws ? `${ws.code} — ${ws.name}` : station.workspace_code ?? "—"}</strong>
          {ws && <span className="muted small"> · SIP Down = {ws.dn_direction}, SIP Up = {ws.dn_direction === "Nominal" ? "Reverse" : "Nominal"}</span>}
        </p>
        {canMove && workspaces.length > 1 && (
          <div className="inline-form">
            <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)}>
              <option value="">Move to workspace…</option>
              {workspaces.filter((w) => w.id !== station.workspace_id).map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
            </select>
            <input style={{ flex: 1, minWidth: 240 }} placeholder="Reason (required, recorded)" value={moveReason}
              onChange={(e) => setMoveReason(e.target.value)} />
            <button disabled={!moveTo || !moveReason.trim()} onClick={move}>Move</button>
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Version numbers <span className="muted small">layout {station.layout_version}</span></h3>
        <p className="muted small">
          Layout version X.Y.Z = KAVACH version . SIP version . Guideline version (FR-010). The Configuration Manager
          changes these, only while the station is in Draft; every change is recorded.
        </p>
        <div className="form-grid">
          <label>KAVACH version (X)<input disabled={!canVersions} value={v.kavach_version} onChange={(e) => setV({ ...v, kavach_version: e.target.value })} /></label>
          <label>SIP version (Y)<input disabled={!canVersions} value={v.sip_version} onChange={(e) => setV({ ...v, sip_version: e.target.value })} /></label>
          <label>Guideline version (Z)<input disabled={!canVersions} value={v.guideline_version} onChange={(e) => setV({ ...v, guideline_version: e.target.value })} /></label>
          <label>SIP drawing no.<input disabled={!canVersions} value={v.sip_drawing_number} onChange={(e) => setV({ ...v, sip_drawing_number: e.target.value })} /></label>
        </div>
        {canVersions && (
          <div className="inline-form">
            <input style={{ flex: 1, minWidth: 280 }} placeholder="Reason (required, recorded)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button disabled={!reason.trim()} onClick={saveVersions}>Save → {preview}</button>
          </div>
        )}
        {!canVersions && (
          <p className="muted small">
            {can("station.versions") ? `Locked: station is ${STATUS_LABELS[station.status] ?? station.status}. Reopen it to start a new revision.`
              : "Only a Configuration Manager or admin can change version numbers."}
          </p>
        )}
        {error && <div className="error">{error}</div>}
        <table className="register-table">
          <thead><tr><th>When</th><th>Field</th><th>From</th><th>To</th><th>By</th><th>Reason</th></tr></thead>
          <tbody>
            {changes.map((c) => (
              <tr key={c.id}>
                <td className="small">{when(c.changed_at)}</td><td>{c.field}</td><td>{c.before ?? "—"}</td><td>{c.after ?? "—"}</td>
                <td className="small">{c.changed_by} <span className="muted">({ROLE_LABELS[c.changed_by_role] ?? c.changed_by_role})</span></td>
                <td>{c.reason ?? ""}</td>
              </tr>
            ))}
            {changes.length === 0 && <tr><td colSpan={6} className="muted">No version or assignment changes recorded.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3>Baselines</h3>
        <p className="muted small">
          A baseline freezes an approved layout (registers, input revisions, checklist version, verification result)
          so later revisions can be compared against it.
        </p>
        {canBaseline && (
          <div className="inline-form wrap">
            <input placeholder="Label, e.g. B1 – Rev-0 approved" value={label} onChange={(e) => setLabel(e.target.value)} style={{ minWidth: 240 }} />
            <input placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
            <button disabled={!label.trim()} onClick={makeBaseline}>Create baseline</button>
          </div>
        )}
        <table className="register-table">
          <thead><tr><th>Label</th><th>Layout</th><th>Status</th><th>Contents</th><th>Checks</th><th>Checklist</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {baselines.map((b) => (
              <tr key={b.id}>
                <td><strong>{b.label}</strong>{b.notes && <div className="muted small">{b.notes}</div>}</td>
                <td>{b.layout_version}</td>
                <td className="small">{STATUS_LABELS[b.station_status] ?? b.station_status}</td>
                <td className="small">{b.counts.elements ?? 0} el · {b.counts.tags ?? 0} tags · {b.counts.tins ?? 0} TINs</td>
                <td className="small">{b.verification_summary ? `${b.verification_summary.fail_count} fail / ${b.verification_summary.total_checks}` : "—"}</td>
                <td>v{b.checklist_version ?? "—"}</td>
                <td className="small">{b.created_by} · {when(b.created_at)}</td>
                <td><button className="link-btn" onClick={() => api.baselineDiff(station.id, b.id).then(setDiff).catch((e) => setError(String(e)))}>Compare with current</button></td>
              </tr>
            ))}
            {baselines.length === 0 && <tr><td colSpan={8} className="muted">No baselines yet{canBaseline ? "" : " (created by a Configuration Manager once the layout is approved)"}.</td></tr>}
          </tbody>
        </table>

        {diff && (
          <div className="comment-modal">
            <div className="panel-header">
              <strong>{diff.baseline.label} (layout {diff.baseline.layout_version}) → current (layout {diff.current_layout_version}, {STATUS_LABELS[diff.current_status] ?? diff.current_status})</strong>
              <button className="secondary" onClick={() => setDiff(null)}>Close</button>
            </div>
            {diff.identical ? <div className="status-banner ok">Identical to the baseline.</div> : (
              <>
                {diff.inputs_changed.length > 0 && <div className="status-banner warn">New input revisions since baseline: {diff.inputs_changed.join(", ")}</div>}
                <table className="register-table">
                  <thead><tr><th>Item</th><th>Change</th><th>Details</th></tr></thead>
                  <tbody>
                    {diff.rows.map((r) => (
                      <tr key={r.item} className={r.change === "removed" ? "row-fail" : r.change === "added" ? "row-pass" : ""}>
                        <td>{r.item}</td><td>{r.change}</td><td className="small">{r.details.join("; ")}</td>
                      </tr>
                    ))}
                    {diff.rows.length === 0 && <tr><td colSpan={3} className="muted">Registers unchanged.</td></tr>}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}
