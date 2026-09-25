import { useEffect, useState } from "react";
import type { DxfCandidate, DxfCalibration, DxfImportResult, Element } from "../types";
import { ELEMENT_TYPES, TAG_TYPES, TAG_TYPE_LABELS } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
  file: File | null;          // a freshly picked .dxf not yet uploaded
  documentId: number | null;  // an already-stored DXF revision
  canCommit: boolean;
  existingElements: Element[];
  onClose: () => void;
  onImported: (docId: number) => Promise<void>;
  onCommitted: () => Promise<void>;
}

interface RowState {
  include: boolean;
  kind: "tag" | "element";
  ref: string;
  type: string;
  location_m: string;
  linked_element_ref: string;
}

function initialRow(c: DxfCandidate): RowState {
  return {
    include: c.kind !== "unclassified",
    kind: c.kind === "element" ? "element" : "tag",
    ref: c.text.startsWith("[block:") ? "" : c.text,
    type: "",
    location_m: c.suggested_location_m != null ? String(c.suggested_location_m) : "",
    linked_element_ref: "",
  };
}

function num(s: string): number | undefined {
  if (s.trim() === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

/** FR-002: human review of DXF import candidates. Nothing reaches the registers
 *  until "Commit" -- and the commit is all-or-nothing on the server. */
export function DxfReviewPanel({ stationId, file, documentId, canCommit, existingElements, onClose, onImported, onCommitted }: Props) {
  const [docType, setDocType] = useState("SIP");
  const [versionLabel, setVersionLabel] = useState("");
  const [cal, setCal] = useState({ ref_x: "", ref_m: "", units_per_m: "" });
  const [result, setResult] = useState<DxfImportResult | null>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const calibration = (): DxfCalibration => ({
    ref_x: num(cal.ref_x), ref_m: num(cal.ref_m), units_per_m: num(cal.units_per_m),
  });

  function applyResult(r: DxfImportResult, keepEdits: boolean) {
    setResult(r);
    setRows((prev) => r.candidates.map((c, i) => {
      const fresh = initialRow(c);
      if (!keepEdits || !prev[i]) return fresh;
      // re-calibration: keep the reviewer's edits, refresh only the suggested chainage
      return { ...prev[i], location_m: fresh.location_m || prev[i].location_m };
    }));
  }

  useEffect(() => {
    if (documentId === null) { setResult(null); setRows([]); return; }
    if (result?.document.id === documentId) return;
    setError(null);
    api.dxfCandidates(stationId, documentId, calibration())
      .then((r) => applyResult(r, false))
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationId, documentId]);

  async function parseNew() {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const r = await api.importDxf(stationId, file, docType, versionLabel, calibration());
      applyResult(r, false);
      await onImported(r.document.id);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  async function recalibrate() {
    if (!result) return;
    setBusy(true); setError(null);
    try {
      applyResult(await api.dxfCandidates(stationId, result.document.id, calibration()), true);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  function update(i: number, patch: Partial<RowState>) {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  const included = rows.map((r, i) => ({ r, i })).filter(({ r }) => r.include);
  const batchElementRefs = included.filter(({ r }) => r.kind === "element" && r.ref).map(({ r }) => r.ref);
  const linkableRefs = Array.from(new Set([...existingElements.map((e) => e.element_ref), ...batchElementRefs]));

  function rowProblem(r: RowState): string | null {
    if (!r.ref.trim()) return "ref required";
    if (!r.type) return "type required";
    if (num(r.location_m) === undefined) return "chainage required";
    return null;
  }
  const problems = included.map(({ r, i }) => ({ i, p: rowProblem(r) })).filter((x) => x.p);

  async function commit() {
    if (!result) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      const payload = {
        elements: included.filter(({ r }) => r.kind === "element").map(({ r }) => ({
          element_ref: r.ref.trim(), element_type: r.type, location_m: num(r.location_m)!,
        })),
        tags: included.filter(({ r }) => r.kind === "tag").map(({ r }) => ({
          tag_ref: r.ref.trim(), tag_type: r.type, location_m: num(r.location_m)!,
          linked_element_ref: r.linked_element_ref || null,
        })),
      };
      const out = await api.dxfCommit(stationId, result.document.id, payload);
      setMessage(`Committed ${out.elements_created} element(s) and ${out.tags_created} tag(s), all traced to ` +
        `DXF rev ${result.document.revision}. Review them in Registers and run verification.`);
      setRows(rows.map((r) => ({ ...r, include: false })));
      await onCommitted();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>DXF Import Review {result && <span className="muted small">— {result.document.original_filename} (rev {result.document.revision})</span>}</h3>
        <button className="secondary" onClick={onClose}>Close</button>
      </div>
      <p className="muted small">
        Layer-name heuristics classify text as tag / element. Nothing is saved to the registers until you
        commit. DXF coordinates aren't chainage — give one reference point and a scale to get suggested chainage (m),
        or type it per row.
      </p>

      <div className="inline-form wrap">
        {file && !result && (
          <>
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              <option value="SIP">Store as: SIP drawing</option>
              <option value="ADJACENT_LAYOUT">Store as: Adjacent Station Layout</option>
              <option value="OTHER">Store as: Other</option>
            </select>
            <input placeholder="Drawing rev label" value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} />
          </>
        )}
        <input title="Reference X (drawing units)" placeholder="Reference X (drawing units)" value={cal.ref_x} onChange={(e) => setCal({ ...cal, ref_x: e.target.value })} />
        <input title="Chainage (m) at the reference X" placeholder="…is at chainage (m)" value={cal.ref_m} onChange={(e) => setCal({ ...cal, ref_m: e.target.value })} />
        <input title="Drawing units per metre (e.g. 1 if the drawing is in metres, 1000 if in mm)" placeholder="Drawing units per metre" value={cal.units_per_m} onChange={(e) => setCal({ ...cal, units_per_m: e.target.value })} />
        {file && !result
          ? <button onClick={parseNew} disabled={busy}>{busy ? "Parsing…" : `Upload & parse ${file.name}`}</button>
          : <button className="secondary" onClick={recalibrate} disabled={busy || !result}>Apply calibration</button>}
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="status-banner ok">{message}</div>}
      {result?.warnings.map((w, i) => <div key={i} className="status-banner warn">{w}</div>)}
      {result && <p className="muted small">Layers found: {result.layers.join(", ") || "—"}</p>}

      {result && (
        <>
          <table className="register-table">
            <thead>
              <tr><th></th><th>DXF text</th><th>Layer</th><th>X</th><th>As</th><th>Ref</th><th>Type</th><th>Chainage (m)</th><th>Linked element</th></tr>
            </thead>
            <tbody>
              {result.candidates.map((c, i) => {
                const r = rows[i];
                if (!r) return null;
                const p = r.include ? rowProblem(r) : null;
                return (
                  <tr key={c.index} className={p ? "row-warn" : ""}>
                    <td><input type="checkbox" checked={r.include} disabled={!canCommit} onChange={(e) => update(i, { include: e.target.checked })} /></td>
                    <td>{c.text}{c.kind === "unclassified" && <div className="muted small">unclassified</div>}</td>
                    <td className="small">{c.layer}</td>
                    <td className="small">{c.x.toFixed(1)}</td>
                    <td>
                      <select value={r.kind} disabled={!r.include} onChange={(e) => update(i, { kind: e.target.value as RowState["kind"], type: "" })}>
                        <option value="tag">Tag</option>
                        <option value="element">Element</option>
                      </select>
                    </td>
                    <td><input value={r.ref} disabled={!r.include} size={8} onChange={(e) => update(i, { ref: e.target.value })} /></td>
                    <td>
                      <select value={r.type} disabled={!r.include} onChange={(e) => update(i, { type: e.target.value })}>
                        <option value="">— choose —</option>
                        {r.kind === "tag"
                          ? TAG_TYPES.map((t) => <option key={t} value={t}>{t} – {TAG_TYPE_LABELS[t]}</option>)
                          : ELEMENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td><input value={r.location_m} disabled={!r.include} size={8} onChange={(e) => update(i, { location_m: e.target.value })} /></td>
                    <td>
                      {r.kind === "tag" && (
                        <select value={r.linked_element_ref} disabled={!r.include} onChange={(e) => update(i, { linked_element_ref: e.target.value })}>
                          <option value="">—</option>
                          {linkableRefs.map((ref) => <option key={ref} value={ref}>{ref}</option>)}
                        </select>
                      )}
                    </td>
                  </tr>
                );
              })}
              {result.candidates.length === 0 && <tr><td colSpan={9} className="muted">No candidates found.</td></tr>}
            </tbody>
          </table>
          {canCommit && (
            <div className="inline-form">
              <button onClick={commit} disabled={busy || included.length === 0 || problems.length > 0}>
                Commit {included.length} row(s) to registers
              </button>
              {problems.length > 0 && <span className="error">{problems.length} selected row(s) incomplete (ref, type and chainage are required)</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
