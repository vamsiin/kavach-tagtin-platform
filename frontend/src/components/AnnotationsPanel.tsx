import { useEffect, useState } from "react";
import { api } from "../api";
import type { Annotation, Track } from "../types";
import { RegisterTable, type ColumnDef } from "./RegisterTable";
import { LineSelect, lineName } from "./ElementsPanel";

const KINDS = ["Track circuit", "Section note", "Feature"] as const;
const HINTS: Record<string, string> = {
  "Track circuit": "Name over a stretch of the line, e.g. DMAT, UMAT (start and end chainage)",
  "Section note": "Note over a stretch, e.g. Axle Counter Section, B/BPAC Section (start and end chainage)",
  Feature: "Something at the site, e.g. Sand hump, Tower wagon shed (chainage; end is optional)",
};

/** Things the approved layouts show that are not tags, TINs or signals: track circuit names,
 *  section notes and site features. Drawn on the layout sheet only; not part of verification. */
export function AnnotationsPanel({ stationId, tracks, readOnly, lockReason }: {
  stationId: number; tracks: Track[]; readOnly?: boolean; lockReason?: string;
}) {
  const [rows, setRows] = useState<Annotation[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try { setRows(await api.listAnnotations(stationId)); setError(null); }
    catch (e) { setError(String(e).replace(/^Error: /, "")); }
  }
  useEffect(() => { reload(); }, [stationId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const columns: ColumnDef<Annotation>[] = [
    { key: "kind", label: "Kind" },
    { key: "label", label: "Label" },
    { key: "track_id", label: "Line", render: (a) => lineName(tracks, a.track_id) },
    { key: "start_m", label: "From (m)" },
    { key: "end_m", label: "To (m)", render: (a) => a.end_m ?? "—" },
    { key: "remarks", label: "Remarks" },
  ];
  const lockMsg = readOnly ? (lockReason ?? "Registers are locked while this station is not in Draft.") : undefined;

  return (
    <>
      {error && <p className="error">{error}</p>}
      <RegisterTable
        title="Drawing annotations (track circuits, section notes, site features)"
        rows={rows}
        columns={columns}
        readOnly={readOnly}
        readOnlyReason={lockMsg}
        onAdd={async (p) => { await api.addAnnotation(stationId, p); await reload(); }}
        onUpdate={async (id, p) => { await api.updateAnnotation(stationId, id, p); await reload(); }}
        onDelete={async (id) => { await api.deleteAnnotation(stationId, id); await reload(); }}
        renderForm={(submit, submitting) => (
          <AnnotationForm tracks={tracks} onSubmit={submit} submitting={submitting} />)}
        renderEditForm={(row, submit, cancel, submitting) => (
          <AnnotationForm tracks={tracks} initial={row} onSubmit={submit} onCancel={cancel} submitting={submitting} />)}
      />
    </>
  );
}

function AnnotationForm({ tracks, initial, onSubmit, onCancel, submitting }: {
  tracks: Track[]; initial?: Annotation;
  onSubmit: (p: Partial<Annotation>) => void; onCancel?: () => void; submitting: boolean;
}) {
  const [kind, setKind] = useState<string>(initial?.kind ?? KINDS[0]);
  const [label, setLabel] = useState(initial?.label ?? "");
  const [track, setTrack] = useState(initial?.track_id != null ? String(initial.track_id) : "");
  const [from, setFrom] = useState(initial ? String(initial.start_m) : "");
  const [to, setTo] = useState(initial?.end_m != null ? String(initial.end_m) : "");
  const [remarks, setRemarks] = useState(initial?.remarks ?? "");
  return (
    <form className="inline-form wrap" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({
        kind, label: label.trim(), track_id: track ? parseInt(track) : null,
        start_m: parseFloat(from), end_m: to ? parseFloat(to) : null, remarks: remarks || null,
      });
    }}>
      <select value={kind} onChange={(e) => setKind(e.target.value)} title={HINTS[kind]}>
        {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
      </select>
      <input placeholder={kind === "Track circuit" ? "Name (e.g. DMAT)" : kind === "Section note" ? "Note (e.g. Axle Counter Section)" : "Feature (e.g. Sand hump)"}
             value={label} onChange={(e) => setLabel(e.target.value)} required />
      <LineSelect tracks={tracks} value={track} onChange={setTrack} />
      <input type="number" step="0.001" placeholder="From (m)" value={from} onChange={(e) => setFrom(e.target.value)}
             required style={{ width: 120 }} />
      <input type="number" step="0.001" placeholder={kind === "Feature" ? "To (m, optional)" : "To (m)"} value={to}
             onChange={(e) => setTo(e.target.value)} required={kind !== "Feature"} style={{ width: 130 }} />
      <input placeholder="Remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      <button type="submit" disabled={submitting}>{submitting ? "Saving…" : initial ? "Save" : "Add"}</button>
      {onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
    </form>
  );
}
