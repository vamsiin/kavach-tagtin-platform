import { useEffect, useState } from "react";
import type { AdjacentStation, Station, StationBorder, Track } from "../types";
import { KIND_FOR_LINE_TYPE, LINE_TYPES, TRACK_TYPES, expectedLineDirection, guessLineType } from "../types";
import { useWorkspace } from "../workspace/WorkspaceContext";
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

  const { byId } = useWorkspace();
  const dnDirection = byId(station.workspace_id)?.dn_direction ?? "Nominal";
  const dirty = (station.centre_line_m ?? null) !== num(centre);
  const reason = readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft.") : undefined;

  const trackCols: ColumnDef<Track>[] = [
    { key: "name", label: "Line" },
    { key: "line_type", label: "Line type", render: (t) => t.line_type ?? guessLineType(t.name) },
    { key: "track_type", label: "Kind" },
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
    { key: "border_m", label: "Line-wise border mapping",
      render: (a) => a.borders?.length
        ? <>{a.borders.map((b, i) => (
            <div key={i}><strong>{b.line_label}</strong>{b.neighbour_line ? ` → ${b.neighbour_line}` : ""} at {b.border_m} ({km(b.border_m)}){b.border_tag_ref ? ` · ${b.border_tag_ref}` : ""}</div>
          ))}</>
        : a.border_m == null ? <span className="badge fail">not recorded</span> : `${a.border_m} (${km(a.border_m)})` },
    { key: "distance_m", label: "Distance (m)", render: (a) => a.distance_m ?? "—" },
    { key: "line_config", label: "Section", render: (a) => a.line_config ? `${a.line_config} line` : "—" },
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
        renderForm={(submit, submitting) => <TrackForm dnDirection={dnDirection} onSubmit={submit} submitting={submitting} />}
        renderEditForm={(row, submit, cancel, submitting) => (
          <TrackForm dnDirection={dnDirection} initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />
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

function TrackForm({ initial, onSubmit, onCancel, submitting, dnDirection }: {
  initial?: Track; onSubmit: (p: Partial<Track>) => void; onCancel?: () => void; submitting: boolean;
  dnDirection: "Nominal" | "Reverse";
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState(initial?.track_type ?? "Main");
  const [lineType, setLineType] = useState(initial?.line_type ?? (initial ? guessLineType(initial.name) : ""));
  // until the user picks a line type, follow the name ("DN MAIN" -> DN MAIN)
  const [lineTypeTouched, setLineTypeTouched] = useState(!!initial);
  const [start, setStart] = useState(initial ? String(initial.start_m) : "");
  const [end, setEnd] = useState(initial ? String(initial.end_m) : "");
  const [dir, setDir] = useState(initial?.direction ?? "");
  const ends = normaliseEndpoints(start, end);
  function pickLineType(lt: string) {
    setLineType(lt);
    if (KIND_FOR_LINE_TYPE[lt] && type !== "Block") setType(KIND_FOR_LINE_TYPE[lt]);
    if (!dir) setDir(expectedLineDirection(lt, dnDirection));
  }
  const expected = expectedLineDirection(lineType, dnDirection);
  const [kavach, setKavach] = useState(initial?.is_kavach ?? true);
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      if (ends.error) return;
      onSubmit({ name, track_type: type, line_type: lineType || guessLineType(name), start_m: ends.lo, end_m: ends.hi,
        direction: dir || null, is_kavach: kavach, remarks: remarks || null });
    }}>
      <input placeholder="Name (e.g. DN MAIN)" value={name} required
        onChange={(e) => { setName(e.target.value); if (!lineTypeTouched) pickLineType(guessLineType(e.target.value)); }} />
      <select value={lineType || "OTHER"} title="Line type: the five running lines; sidings and all other lines are OTHER"
        onChange={(e) => { setLineTypeTouched(true); pickLineType(e.target.value); }}>
        {LINE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <select value={type} onChange={(e) => setType(e.target.value)} title="Kind of line (Siding marks sidings for H2.20)">
        {TRACK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <SectionEndpoints a={start} b={end} direction={dir}
        onChange={(a, b, d) => { setStart(a); setEnd(b); setDir(d); }} />
      {expected && dir && dir !== expected && (
        <span className="small" style={{ color: "#8a6116" }}>{lineType} lines normally run {expected} in this zone</span>
      )}
      <label className="checkbox-label">
        <input type="checkbox" checked={kavach} onChange={(e) => setKavach(e.target.checked)} /> KAVACH line
      </label>
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting || !!ends.error}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

type BorderDraft = { line_label: string; border_m: string; border_tag_ref: string; track_id: string; neighbour_line: string };
const toDraft = (b: StationBorder): BorderDraft => ({ line_label: b.line_label, border_m: String(b.border_m),
  border_tag_ref: b.border_tag_ref ?? "", track_id: b.track_id != null ? String(b.track_id) : "",
  neighbour_line: b.neighbour_line ?? "" });
const emptyRow = (): BorderDraft => ({ line_label: "", border_m: "", border_tag_ref: "", track_id: "", neighbour_line: "" });

const isLower = (side: string) => /lower|reverse/i.test(side);

/** What trains on this line do at the border: enter the station from the neighbour or
 *  leave towards it (from the line's direction and the side the neighbour is on). */
function movementAtBorder(t: Track | undefined, side: string): string {
  if (!t?.direction) return "—";
  if (t.direction === "Both") return "both ways";
  const entering = (t.direction === "Nominal") === isLower(side);
  return entering ? "trains enter from the neighbour" : "trains leave towards the neighbour";
}

function derivedSection(rows: BorderDraft[]): string {
  const n = new Set(rows.filter((r) => r.border_m.trim() !== "").map((r) => r.track_id || r.line_label.trim().toLowerCase())).size;
  return n === 0 ? "—" : n === 1 ? "Single line" : n === 2 ? "Double line" : `Multiple line (${n} lines)`;
}

function AdjacentForm({ tracks, initial, onSubmit, onCancel, submitting }: {
  tracks: Track[]; initial?: AdjacentStation; onSubmit: (p: Partial<AdjacentStation>) => void;
  onCancel?: () => void; submitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [kid, setKid] = useState(initial?.kavach_station_id ?? "");
  const [side, setSide] = useState(initial?.side ?? "Lower km");
  const [dist, setDist] = useState(initial?.distance_m != null ? String(initial.distance_m) : "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  // Line-wise mapping (H2.16 / H2.22): one row per line of this station that crosses the
  // border; single / double / multiple line follows from the number of rows.
  const [borders, setBorders] = useState<BorderDraft[]>(
    initial?.borders?.length ? initial.borders.map(toDraft)
      : initial?.border_m != null ? [{ ...emptyRow(), line_label: "All lines", border_m: String(initial.border_m) }]
      : [emptyRow()]);
  const setB = (i: number, patch: Partial<BorderDraft>) =>
    setBorders(borders.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const sides = ["Lower km", "Higher km", "Nominal", "Reverse"];
  const trackById = (id: string) => tracks.find((t) => String(t.id) === id);
  const lineKind = (t: Track) => t.line_type ?? guessLineType(t.name);

  function pickLine(i: number, id: string) {
    const t = trackById(id);
    const b = borders[i];
    setB(i, { track_id: id, line_label: t?.name ?? b.line_label,
      neighbour_line: b.neighbour_line || (t ? (lineKind(t) !== "OTHER" ? lineKind(t) : t.name) : ""),
      border_m: b.border_m || (t ? String(isLower(side) ? Math.min(t.start_m, t.end_m) : Math.max(t.start_m, t.end_m)) : "") });
  }
  function mapMainLines() {
    const used = new Set(borders.map((b) => b.track_id));
    const add = tracks.filter((t) => ["UP MAIN", "DN MAIN"].includes(lineKind(t)) && !used.has(String(t.id)))
      .map((t) => ({ ...emptyRow(), track_id: String(t.id), line_label: t.name, neighbour_line: lineKind(t),
        border_m: String(isLower(side) ? Math.min(t.start_m, t.end_m) : Math.max(t.start_m, t.end_m)) }));
    setBorders([...borders.filter((b) => b.track_id || b.border_m || b.line_label), ...add]);
  }
  const dupLine = borders.some((b, i) => b.track_id && borders.findIndex((x) => x.track_id === b.track_id) !== i);
  const unmapped = tracks.length > 0 && borders.some((b) => b.border_m.trim() !== "" && !b.track_id);

  return (
    <form onSubmit={(e) => {
      e.preventDefault();
      if (dupLine) return;
      const rows = borders.filter((b) => b.border_m.trim() !== "");
      onSubmit({ name, kavach_station_id: kid || null, side, border_m: null, distance_m: num(dist),
        line_config: null, remarks: remarks || null,
        borders: rows.map((b) => ({ line_label: b.line_label.trim() || trackById(b.track_id)?.name || "All lines",
          border_m: parseFloat(b.border_m), border_tag_ref: b.border_tag_ref.trim() || null,
          track_id: b.track_id ? parseInt(b.track_id) : null, neighbour_line: b.neighbour_line.trim() || null })) });
    }}>
      <div className="inline-form wrap">
        <input placeholder="Station name (e.g. Aler-PBP-IB)" value={name} onChange={(e) => setName(e.target.value)} required />
        <input placeholder="KAVACH ID" value={kid} onChange={(e) => setKid(e.target.value)} style={{ width: 100 }} />
        <select value={side} onChange={(e) => setSide(e.target.value)} title="Which side of this station the neighbour is on">
          {[...new Set([side, ...sides])].map((s) => <option key={s} value={s}>{s} side</option>)}
        </select>
        <input type="number" step="0.001" placeholder="Distance (m)" value={dist} style={{ width: 120 }}
          onChange={(e) => setDist(e.target.value)} title="Centre line to centre line, as written on the layout" />
        <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>
        <strong>Line-wise border mapping (H2.16):</strong> one row for each line of this station that crosses the
        border, with the line it continues as at {name || "the neighbour"}, the border chainage and the border tag.
        Section: <strong>{derivedSection(borders)}</strong> (from the mapped lines, H2.22).
      </div>
      <datalist id="neighbour-lines">{LINE_TYPES.filter((t) => t !== "OTHER").map((t) => <option key={t} value={t} />)}</datalist>
      <table className="register-table compact">
        <thead><tr><th>This station's line</th><th>Continues at neighbour as</th><th>Border chainage (m)</th>
          <th>Border tag</th><th>At the border</th><th></th></tr></thead>
        <tbody>
          {borders.map((b, i) => {
            const t = trackById(b.track_id);
            return (
              <tr key={i}>
                <td>{tracks.length > 0
                  ? <select value={b.track_id} onChange={(e) => pickLine(i, e.target.value)} required={b.border_m.trim() !== ""}>
                      <option value="">Pick a line…</option>
                      {tracks.map((x) => <option key={x.id} value={x.id}>{x.name} ({lineKind(x)})</option>)}
                    </select>
                  : <input placeholder="Line (e.g. DN MAIN)" value={b.line_label} style={{ width: 130 }}
                      onChange={(e) => setB(i, { line_label: e.target.value })} />}</td>
                <td><input list="neighbour-lines" placeholder="e.g. DN MAIN" value={b.neighbour_line} style={{ width: 140 }}
                  onChange={(e) => setB(i, { neighbour_line: e.target.value })} /></td>
                <td><input type="number" step="0.001" min="0" placeholder="e.g. 265279" value={b.border_m} style={{ width: 120 }}
                  onChange={(e) => setB(i, { border_m: e.target.value })} />
                  <div className="muted small">{km(num(b.border_m))}</div></td>
                <td><input placeholder="e.g. R-903 or S7D" value={b.border_tag_ref} style={{ width: 130 }}
                  onChange={(e) => setB(i, { border_tag_ref: e.target.value })} /></td>
                <td className="small">{movementAtBorder(t, side)}</td>
                <td><button type="button" className="link-btn danger" onClick={() => setBorders(borders.filter((_, j) => j !== i))}>Remove</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {dupLine && <div className="error small">A line can cross the border with this neighbour only once.</div>}
      {unmapped && <div className="small" style={{ color: "#8a6116" }}>Pick this station's line for every border row.</div>}
      <div className="inline-form">
        <button type="button" className="secondary" onClick={() => setBorders([...borders, emptyRow()])}>+ Map another line</button>
        {tracks.some((t) => ["UP MAIN", "DN MAIN"].includes(lineKind(t))) && (
          <button type="button" className="secondary" onClick={mapMainLines} title="Adds UP MAIN / DN MAIN with their end on this side as the border">
            Map main lines</button>
        )}
        <button type="submit" disabled={submitting || dupLine}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
        {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}
