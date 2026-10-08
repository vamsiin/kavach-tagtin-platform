import { useEffect, useState } from "react";
import type { AdjacentStation, Station, StationBorder, Track } from "../types";
import { LINE_CONFIGS, TRACK_TYPES } from "../types";
import { api } from "../api";
import { RegisterTable, type ColumnDef } from "./RegisterTable";
import { SectionEndpoints, directionText, movementText, normaliseEndpoints } from "./SectionEndpoints";

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
    { key: "start_m", label: "From / Start (m)" },
    { key: "end_m", label: "To / End (m)" },
    { key: "direction", label: "Direction", render: (t) => directionText(t.direction) },
    { key: "_movement", label: "Movement (km)", render: (t) => movementText(t.start_m, t.end_m, t.direction) },
    { key: "is_kavach", label: "KAVACH", render: (t) => (t.is_kavach ? "Yes" : "No (white)") },
    { key: "remarks", label: "Remarks" },
  ];
  const adjCols: ColumnDef<AdjacentStation>[] = [
    { key: "name", label: "Station" },
    { key: "kavach_station_id", label: "KAVACH ID", render: (a) => a.kavach_station_id ?? "—" },
    { key: "side", label: "Side" },
    { key: "border_m", label: "Border line (m)",
      render: (a) => a.borders?.length
        ? <>{a.borders.map((b, i) => (
            <div key={i}><strong>{b.line_label}</strong>: {b.border_m} ({km(b.border_m)}){b.border_tag_ref ? ` · ${b.border_tag_ref}` : ""}</div>
          ))}</>
        : a.border_m == null ? <span className="badge fail">not recorded</span> : `${a.border_m} (${km(a.border_m)})` },
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
        renderForm={(submit, submitting) => <AdjacentForm tracks={tracks} onSubmit={submit} submitting={submitting} />}
        renderEditForm={(row, submit, cancel, submitting) => (
          <AdjacentForm tracks={tracks} initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
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
  const ends = normaliseEndpoints(start, end);
  const [kavach, setKavach] = useState(initial?.is_kavach ?? true);
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      if (ends.error) return;
      onSubmit({ name, track_type: type, start_m: ends.lo, end_m: ends.hi,
        direction: dir || null, is_kavach: kavach, remarks: remarks || null });
    }}>
      <input placeholder="Name (e.g. DN MAIN)" value={name} onChange={(e) => setName(e.target.value)} required />
      <select value={type} onChange={(e) => setType(e.target.value)}>
        {TRACK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <SectionEndpoints a={start} b={end} direction={dir}
        onChange={(a, b, d) => { setStart(a); setEnd(b); setDir(d); }} />
      <label className="checkbox-label">
        <input type="checkbox" checked={kavach} onChange={(e) => setKavach(e.target.checked)} /> KAVACH line
      </label>
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting || !!ends.error}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

type BorderDraft = { line_label: string; border_m: string; border_tag_ref: string; track_id: string };
const toDraft = (b: StationBorder): BorderDraft => ({ line_label: b.line_label, border_m: String(b.border_m),
  border_tag_ref: b.border_tag_ref ?? "", track_id: b.track_id != null ? String(b.track_id) : "" });

function AdjacentForm({ tracks, initial, onSubmit, onCancel, submitting }: {
  tracks: Track[]; initial?: AdjacentStation; onSubmit: (p: Partial<AdjacentStation>) => void;
  onCancel?: () => void; submitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kid, setKid] = useState(initial?.kavach_station_id ?? "");
  const [side, setSide] = useState(initial?.side ?? "Lower km");
  const [dist, setDist] = useState(initial?.distance_m != null ? String(initial.distance_m) : "");
  const [cfg, setCfg] = useState(initial?.line_config ?? "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  // Border per line (H2.16). A station with one border for all lines just uses one row.
  const [borders, setBorders] = useState<BorderDraft[]>(
    initial?.borders?.length ? initial.borders.map(toDraft)
      : initial?.border_m != null ? [{ line_label: "All lines", border_m: String(initial.border_m), border_tag_ref: "", track_id: "" }]
      : [{ line_label: "DN line", border_m: "", border_tag_ref: "", track_id: "" }]);
  const setB = (i: number, patch: Partial<BorderDraft>) =>
    setBorders(borders.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const sides = ["Lower km", "Higher km", "Nominal", "Reverse"];

  return (
    <form onSubmit={(e) => {
      e.preventDefault();
      const rows = borders.filter((b) => b.border_m.trim() !== "");
      onSubmit({ name, kavach_station_id: kid || null, side, border_m: null, distance_m: num(dist),
        line_config: cfg || null, remarks: remarks || null,
        borders: rows.map((b) => ({ line_label: b.line_label.trim() || "All lines", border_m: parseFloat(b.border_m),
          border_tag_ref: b.border_tag_ref.trim() || null, track_id: b.track_id ? parseInt(b.track_id) : null })) });
    }}>
      <div className="inline-form wrap">
        <input placeholder="Station name (e.g. Aler-PBP-IB)" value={name} onChange={(e) => setName(e.target.value)} required />
        <input placeholder="KAVACH ID" value={kid} onChange={(e) => setKid(e.target.value)} style={{ width: 100 }} />
        <select value={side} onChange={(e) => setSide(e.target.value)} title="Which side of this station the neighbour is on">
          {[...new Set([side, ...sides])].map((s) => <option key={s} value={s}>{s} side</option>)}
        </select>
        <input type="number" step="0.001" placeholder="Distance (m)" value={dist} style={{ width: 120 }}
          onChange={(e) => setDist(e.target.value)} title="Centre line to centre line, as written on the layout" />
        <select value={cfg} onChange={(e) => setCfg(e.target.value)} title="Section between the stations (H2.22)">
          <option value="">Section —</option>
          {LINE_CONFIGS.map((c) => <option key={c} value={c}>{c} line</option>)}
        </select>
        <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      </div>
      <div className="muted small">Border line location on each line (H2.16), with its border tag:</div>
      {borders.map((b, i) => (
        <div key={i} className="inline-form wrap">
          <input placeholder="Line (e.g. DN line)" value={b.line_label} style={{ width: 130 }}
            onChange={(e) => setB(i, { line_label: e.target.value })} />
          <input type="number" step="0.001" placeholder="Border (m), e.g. 265278" value={b.border_m} style={{ width: 170 }}
            onChange={(e) => setB(i, { border_m: e.target.value })} />
          <span className="muted small" style={{ minWidth: 80 }}>{km(num(b.border_m))}</span>
          <input placeholder="Border tag (e.g. S7D)" value={b.border_tag_ref} style={{ width: 140 }}
            onChange={(e) => setB(i, { border_tag_ref: e.target.value })} />
          {tracks.length > 0 && (
            <select value={b.track_id} onChange={(e) => setB(i, { track_id: e.target.value })} title="Optional: link to a recorded line">
              <option value="">Linked line —</option>
              {tracks.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          )}
          <button type="button" className="link-btn danger" onClick={() => setBorders(borders.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div className="inline-form">
        <button type="button" className="secondary"
          onClick={() => setBorders([...borders, { line_label: borders.length === 1 ? "UP line" : "", border_m: "", border_tag_ref: "", track_id: "" }])}>
          + Border on another line
        </button>
        <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
