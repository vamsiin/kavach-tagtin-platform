import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { AdjacentStation, RssiSummary, Tower, Track } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";
import { LineSelect, lineName } from "./ElementsPanel";
import { RegisterImport } from "./RegisterImport";

/** Input 5: Stationary KAVACH tower locations, and the tower RSSI survey that shows
 *  whether every border tag gets -70 dBm or better from both stations (BRD BR-005). */
export function TowersPanel({ stationId, stationName, tracks, adjacent, readOnly, lockReason }: {
  stationId: number; stationName: string; tracks: Track[]; adjacent: AdjacentStation[];
  readOnly?: boolean; lockReason?: string;
}) {
  const [towers, setTowers] = useState<Tower[]>([]);
  const [summary, setSummary] = useState<RssiSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      const [t, s] = await Promise.all([api.listTowers(stationId), api.rssiSummary(stationId)]);
      setTowers(t); setSummary(s); setError(null);
    } catch (e) { setError(String(e).replace(/^Error: /, "")); }
  }
  useEffect(() => { reload(); }, [stationId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const columns: ColumnDef<Tower>[] = [
    { key: "tower_ref", label: "Tower" },
    { key: "location_m", label: "Location (m)" },
    { key: "owner", label: "Station", render: (t) => t.owner || `${stationName} (this station)` },
    { key: "track_id", label: "Beside line", render: (t) => lineName(tracks, t.track_id) },
    { key: "side", label: "Side", render: (t) => t.side || "—" },
    { key: "height_m", label: "Height (m)", render: (t) => t.height_m ?? "—" },
    { key: "remarks", label: "Remarks" },
  ];
  const lockMsg = readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft.") : undefined;

  return (
    <>
      <RegisterTable
        title="Towers (Stationary KAVACH)"
        rows={towers}
        columns={columns}
        readOnly={readOnly}
        readOnlyReason={lockMsg}
        headerExtra={<RegisterImport stationId={stationId} kind="towers" onDone={reload} />}
        onAdd={async (p) => { await api.addTower(stationId, p); await reload(); }}
        onUpdate={async (id, p) => { await api.updateTower(stationId, id, p); await reload(); }}
        onDelete={async (id) => { await api.deleteTower(stationId, id); await reload(); }}
        renderForm={(submit, submitting) => (
          <TowerForm tracks={tracks} adjacent={adjacent} stationName={stationName} onSubmit={submit} submitting={submitting} />)}
        renderEditForm={(row, submit, cancel, submitting) => (
          <TowerForm tracks={tracks} adjacent={adjacent} stationName={stationName} initial={row}
            onSubmit={submit} onCancel={cancel} submitting={submitting} />)}
      />
      <RssiSection stationId={stationId} summary={summary} readOnly={readOnly} onChanged={reload} error={error} />
    </>
  );
}

function RssiSection({ stationId, summary, readOnly, onChanged, error }: {
  stationId: number; summary: RssiSummary | null; readOnly?: boolean; onChanged: () => Promise<void>; error: string | null;
}) {
  const [confirm, setConfirm] = useState(false);
  const badge = (s: string): ReactNode => (
    <span className={`badge ${s === "PASS" ? "pass" : s === "FAIL" ? "fail" : "warn"}`}>{s}</span>);
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Tower RSSI survey</h3>
        {!readOnly && (
          <div className="inline-form">
            <RegisterImport stationId={stationId} kind="rssi" onDone={onChanged} />
            {summary && summary.total_readings > 0 && (confirm ? (
              <>
                <span>Delete all {summary.total_readings} readings?</span>
                <button className="danger" onClick={async () => { await api.clearRssi(stationId); setConfirm(false); await onChanged(); }}>Delete</button>
                <button className="secondary" onClick={() => setConfirm(false)}>Cancel</button>
              </>
            ) : <button className="secondary" onClick={() => setConfirm(true)}>Clear readings</button>)}
          </div>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      <p className="muted small">
        Readings of each tower's signal along the line, from the RSSI report. Every border tag needs this
        station's tower and the adjacent station's tower at -70 dBm or better within 50 m (BRD BR-005;
        threshold and distance are in the checklist settings).
      </p>
      {!summary || summary.total_readings === 0 ? <p className="muted small">No RSSI readings loaded.</p> : (
        <table className="register-table">
          <thead><tr><th>Tower</th><th>Station</th><th>Readings</th><th>From (m)</th><th>To (m)</th><th>Strongest</th><th>Weakest</th></tr></thead>
          <tbody>
            {summary.towers.map((t) => (
              <tr key={t.tower_ref}>
                <td>{t.tower_ref} {!t.in_register && <span className="badge warn" title="Add this tower to the towers register">not in register</span>}</td>
                <td>{t.owner ?? "—"}</td><td>{t.readings}</td><td>{t.from_m}</td><td>{t.to_m}</td>
                <td>{t.best_dbm} dBm</td><td>{t.worst_dbm} dBm</td>
              </tr>))}
          </tbody>
        </table>
      )}
      {summary && summary.border_coverage.length > 0 && (
        <>
          <h4>Border tags</h4>
          <table className="register-table">
            <tbody>
              {summary.border_coverage.map((c, i) => (
                <tr key={i}><td>{badge(c.status)}</td><td>{c.message}</td></tr>))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function TowerForm({ tracks, adjacent, stationName, initial, onSubmit, onCancel, submitting }: {
  tracks: Track[]; adjacent: AdjacentStation[]; stationName: string; initial?: Tower;
  onSubmit: (p: Partial<Tower>) => void; onCancel?: () => void; submitting: boolean;
}) {
  const [ref, setRef] = useState(initial?.tower_ref ?? "");
  const [loc, setLoc] = useState(initial ? String(initial.location_m) : "");
  const [owner, setOwner] = useState(initial?.owner ?? "");
  const [track, setTrack] = useState(initial?.track_id != null ? String(initial.track_id) : "");
  const [side, setSide] = useState(initial?.side ?? "");
  const [height, setHeight] = useState(initial?.height_m != null ? String(initial.height_m) : "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        tower_ref: ref.trim(), location_m: parseFloat(loc), owner: owner || null,
        track_id: track ? parseInt(track) : null, side: side || null,
        height_m: height ? parseFloat(height) : null, remarks: remarks || null,
      });
    }}>
      <input placeholder="Tower (e.g. ALR-T1)" value={ref} onChange={(e) => setRef(e.target.value)} required />
      <input type="number" step="0.001" placeholder="Location (m)" value={loc} onChange={(e) => setLoc(e.target.value)}
             required style={{ width: 130 }} />
      <select value={owner} onChange={(e) => setOwner(e.target.value)} title="Station the tower belongs to">
        <option value="">{stationName} (this station)</option>
        {adjacent.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}
      </select>
      <LineSelect tracks={tracks} value={track} onChange={setTrack} placeholder="Beside line —" />
      <input placeholder="Side (e.g. UP side)" value={side} onChange={(e) => setSide(e.target.value)} style={{ width: 120 }} />
      <input type="number" step="0.1" placeholder="Height (m)" value={height} onChange={(e) => setHeight(e.target.value)} style={{ width: 100 }} />
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
