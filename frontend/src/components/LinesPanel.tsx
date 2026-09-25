import { useEffect, useState } from "react";
import type { AdjacentStation, Station, Track } from "../types";
import { LINE_CONFIGS, TRACK_TYPES } from "../types";
import { api } from "../api";
import { RegisterTable, type ColumnDef } from "./RegisterTable";

interface Props {
  station: Station;
  tracks: Track[];
  adjacent: AdjacentStation[];
  readOnly: boolean;
  lockReason?: string;
  onTracksChanged: () => Promise<void>;
  onAdjacentChanged: () => Promise<void>;
  onStationChanged: (s: Station) => void;
}

const km = (m: number | null | undefined) => (m == null ? "" : `km ${(m / 1000).toFixed(3)}`);
const num = (v: string) => (v.trim() === "" ? null : parseFloat(v));

/** Step 2 of the Annexure-H plan: the station's lines (tracks), its centre line
 *  (H2.28) and its neighbouring stations with their border lines (H2.16). */
export function LinesPanel({ station, tracks, adjacent, readOnly, lockReason, onTracksChanged,
  onAdjacentChanged, onStationChanged }: Props) {
  const [centre, setCentre] = useState(station.centre_line_m != null ? String(station.centre_line_m) : "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setCentre(station.centre_line_m != null ? String(station.centre_line_m) : ""); },
    [station.id, station.centre_line_m]);

  async function saveCentre() {
    setSaving(true); setError(null);
    try { onStationChanged(await api.setCentreLine(station.id, num(centre))); }
    catch (e) { setError(String(e)); } finally { setSaving(false); }
  }

  const dirty = (station.centre_line_m ?? null) !== num(centre);
  const reason = readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft.") : undefined;

  const trackCols: ColumnDef<Track>[] = [
    { key: "name", label: "Line" },
    { key: "track_type", label: "Type" },
    { key: "start_m", label: "From (m)" },
    { key: "end_m", label: "To (m)" },
    { key: "direction", label: "Dir", render: (t) => t.direction ?? "—" },
    { key: "is_kavach", label: "KAVACH", render: (t) => (t.is_kavach ? "Yes" : "No (white)") },
    { key: "remarks", label: "Remarks" },
  ];
  const adjCols: ColumnDef<AdjacentStation>[] = [
    { key: "name", label: "Station" },
    { key: "kavach_station_id", label: "KAVACH ID", render: (a) => a.kavach_station_id ?? "—" },
    { key: "side", label: "Side" },
    { key: "border_m", label: "Border line (m)",
      render: (a) => a.border_m == null ? <span className="badge fail">not recorded</span> : `${a.border_m} (${km(a.border_m)})` },
    { key: "distance_m", label: "Distance (m)", render: (a) => a.distance_m ?? "—" },
    { key: "line_config", label: "Section", render: (a) => a.line_config ?? "—" },
    { key: "remarks", label: "Remarks" },
  ];

  return (
    <>
      <div className="panel">
        <div className="panel-header"><h3>Station centre line</h3></div>
        <p className="muted small">
          Absolute location of the station centre line (the Station Master's panel centre, H2.4), shown on the
          layout per H2.28. Chainage in metres.
        </p>
        <div className="inline-form">
          <input type="number" step="0.001" placeholder="Centre line (m), e.g. 262750" value={centre}
            disabled={readOnly} onChange={(e) => setCentre(e.target.value)} style={{ width: 220 }} />
          <span className="muted small">{km(num(centre))}</span>
          {!readOnly && <button onClick={saveCentre} disabled={saving || !dirty}>{saving ? "Saving…" : "Save"}</button>}
          {station.centre_line_m == null && <span className="badge fail">not recorded</span>}
        </div>
        {reason && <div className="muted small">{reason}</div>}
        {error && <div className="error">{error}</div>}
      </div>

      <RegisterTable
        title="Lines"
        rows={tracks}
        columns={trackCols}
        readOnly={readOnly}
        readOnlyReason={reason}
        onAdd={async (p) => { await api.addTrack(station.id, p); await onTracksChanged(); }}
        onUpdate={async (id, p) => { await api.updateTrack(station.id, id, p); await onTracksChanged(); }}
        onDelete={async (id) => { await api.deleteTrack(station.id, id); await onTracksChanged(); }}
        renderForm={(submit, submitting) => <TrackForm onSubmit={submit} submitting={submitting} />}
        renderEditForm={(row, submit, cancel, submitting) => (
          <TrackForm initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
        )}
      />

      <RegisterTable
        title="Adjacent stations and border lines"
        rows={adjacent}
        columns={adjCols}
        readOnly={readOnly}
        readOnlyReason={reason}
        onAdd={async (p) => { await api.addAdjacent(station.id, p); await onAdjacentChanged(); }}
        onUpdate={async (id, p) => { await api.updateAdjacent(station.id, id, p); await onAdjacentChanged(); }}
        onDelete={async (id) => { await api.deleteAdjacent(station.id, id); await onAdjacentChanged(); }}
        renderForm={(submit, submitting) => <AdjacentForm onSubmit={submit} submitting={submitting} />}
        renderEditForm={(row, submit, cancel, submitting) => (
          <AdjacentForm initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
        )}
      />
    </>
  );
}

function TrackForm({ initial, onSubmit, onCancel, submitting }: {
  initial?: Track; onSubmit: (p: Partial<Track>) => void; onCancel?: () => void; submitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState(initial?.track_type ?? "Main");
  const [start, setStart] = useState(initial ? String(initial.start_m) : "");
  const [end, setEnd] = useState(initial ? String(initial.end_m) : "");
  const [dir, setDir] = useState(initial?.direction ?? "");
  const [kavach, setKavach] = useState(initial?.is_kavach ?? true);
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({ name, track_type: type, start_m: parseFloat(start), end_m: parseFloat(end),
        direction: dir || null, is_kavach: kavach, remarks: remarks || null });
    }}>
      <input placeholder="Name (e.g. DN MAIN)" value={name} onChange={(e) => setName(e.target.value)} required />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {TRACK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <input type="number" step="0.001" placeholder="From (m)" value={start} required style={{ width: 120 }}
        onChange={(e) => setStart(e.target.value)} title="Lower chainage of the line, in metres" />
      <input type="number" step="0.001" placeholder="To (m)" value={end} required style={{ width: 120 }}
        onChange={(e) => setEnd(e.target.value)} title="Higher chainage of the line, in metres" />
      <select value={dir} onChange={(e) => setDir(e.target.value)}>
        <option value="">Dir —</option>
        <option value="Nominal">Nominal</option>
        <option value="Reverse">Reverse</option>
        <option value="Both">Both</option>
      </select>
      <label className="checkbox-label">
        <input type="checkbox" checked={kavach} onChange={(e) => setKavach(e.target.checked)} /> KAVACH line
      </label>
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

function AdjacentForm({ initial, onSubmit, onCancel, submitting }: {
  initial?: AdjacentStation; onSubmit: (p: Partial<AdjacentStation>) => void; onCancel?: () => void; submitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kid, setKid] = useState(initial?.kavach_station_id ?? "");
  const [side, setSide] = useState(initial?.side ?? "Nominal");
  const [border, setBorder] = useState(initial?.border_m != null ? String(initial.border_m) : "");
  const [dist, setDist] = useState(initial?.distance_m != null ? String(initial.distance_m) : "");
  const [cfg, setCfg] = useState(initial?.line_config ?? "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({ name, kavach_station_id: kid || null, side, border_m: num(border), distance_m: num(dist),
        line_config: cfg || null, remarks: remarks || null });
    }}>
      <input placeholder="Station name" value={name} onChange={(e) => setName(e.target.value)} required />
      <input placeholder="KAVACH ID" value={kid} onChange={(e) => setKid(e.target.value)} style={{ width: 100 }} />
      <select value={side} onChange={(e) => setSide(e.target.value)} title="Direction towards the adjacent station">
        <option value="Nominal">Nominal side</option>
        <option value="Reverse">Reverse side</option>
      </select>
      <input type="number" step="0.001" placeholder="Border line (m)" value={border} style={{ width: 140 }}
        onChange={(e) => setBorder(e.target.value)} title="Absolute location of the station border line (H2.16)" />
      <input type="number" step="0.001" placeholder="Distance (m)" value={dist} style={{ width: 120 }}
        onChange={(e) => setDist(e.target.value)} title="Centre line to centre line, as written on the layout" />
      <select value={cfg} onChange={(e) => setCfg(e.target.value)} title="Section between the stations (H2.22)">
        <option value="">Section —</option>
        {LINE_CONFIGS.map((c) => <option key={c} value={c}>{c} line</option>)}
      </select>
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
