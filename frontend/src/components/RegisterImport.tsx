import { useRef, useState } from "react";
import { api, type ImportPreview } from "../api";

const TITLES: Record<string, string> = { elements: "Elements", tags: "Tags", tins: "TINs" };
const COLUMNS: Record<string, string> = {
  elements: "#, Name of the Signal, Type of Signal, Location(m), Line, Dir (Down / Up), Remarks",
  tags: "#, Tag Number (e.g. R-775), Type of Tag (e.g. S - Signal Foot Tag), Chainage(m), Line, Dir (Nominal (DN) / Reverse (UP)), Linked element, Pair group ID, Legend, Border tag (Yes / No)",
  tins: "#, TIN Number, TIN Placement (Station / Block), Line, Color, Start (m), End (m) (either order), No KAVACH territory (Yes / No)",
};

/** "Upload CSV" for a register: pick a .csv / .xlsx file, see every row checked
 *  (add / update / error) before anything is saved, then import it in one go. */
export function RegisterImport({ stationId, kind, onDone }: { stationId: number; kind: "elements" | "tags" | "tins"; onDone: () => Promise<void> }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [update, setUpdate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function check(f: File, upd: boolean) {
    setBusy(true); setError(null); setDone(null);
    try { setPreview(await api.importRegister(stationId, kind, f, false, upd)); }
    catch (e) { setError(String(e).replace(/^Error: /, "")); setPreview(null); }
    finally { setBusy(false); }
  }

  async function apply() {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const r = await api.importRegister(stationId, kind, file, true, update);
      if (r.applied) {
        await onDone();
        setDone(`${r.counts.add} added, ${r.counts.update} updated`);
        setPreview(null); setFile(null);
      } else setPreview(r);
    } catch (e) { setError(String(e).replace(/^Error: /, "")); }
    finally { setBusy(false); }
  }

  const close = () => { setPreview(null); setFile(null); setError(null); };
  const open = !!(file && (preview || error || busy));

  return (
    <>
      <button className="secondary" onClick={() => input.current?.click()} title="Add or update many rows from a CSV or Excel file">
        Upload CSV
      </button>
      <input ref={input} type="file" accept=".csv,.txt,.xlsx" style={{ display: "none" }}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) { setFile(f); check(f, update); } }} />
      {done && <span className="muted small">{done} ✓</span>}

      {open && (
        <div className="modal-overlay" onClick={close}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="panel-header">
              <h3>Upload {TITLES[kind]} — {file?.name}</h3>
              <button className="secondary" onClick={close}>Close</button>
            </div>
            <p className="muted small">
              Columns: {COLUMNS[kind]}. "-" means empty; when updating, an empty cell keeps what is already recorded.{" "}
              <button className="link-btn" onClick={() => api.downloadRegisterTemplate(stationId, kind)}>Download template</button>
            </p>
            {busy && <div className="muted">Checking…</div>}
            {error && <div className="error">{error}</div>}
            {preview && (
              <>
                <div className={`status-banner ${preview.can_apply ? "ok" : preview.counts.error ? "fail" : "warn"}`}>
                  {preview.counts.add} to add · {preview.counts.update} to update · {preview.counts.error} with errors
                  {preview.counts.error > 0 && " — fix them in the file and upload again; nothing is saved while any row has an error"}
                </div>
                {preview.ignored_columns.length > 0 && (
                  <div className="small" style={{ color: "#8a6116" }}>Columns not recognised (ignored): {preview.ignored_columns.join(", ")}</div>
                )}
                <label className="checkbox-label">
                  <input type="checkbox" checked={update} onChange={(e) => { setUpdate(e.target.checked); if (file) check(file, e.target.checked); }} />
                  Update rows that already exist (same {kind === "tags" ? "tag ID" : kind === "tins" ? "TIN number and line" : "ref and line"})
                </label>
                <div style={{ maxHeight: "50vh", overflow: "auto", marginTop: 8 }}>
                  <table className="register-table compact">
                    <thead><tr><th>Row</th><th>Entry</th><th>Action</th><th>Problems / notes</th></tr></thead>
                    <tbody>
                      {preview.rows.map((r) => (
                        <tr key={r.row} className={r.action === "error" ? "row-fail" : r.warnings.length ? "row-warn" : ""}>
                          <td>{r.row}</td><td>{r.key}</td>
                          <td><span className={`badge ${r.action === "error" ? "fail" : r.action === "update" ? "warn" : "pass"}`}>{r.action}</span></td>
                          <td className="small">
                            {r.errors.map((x) => <div key={x} className="error">{x}</div>)}
                            {r.warnings.map((x) => <div key={x} style={{ color: "#8a6116" }}>{x}</div>)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="inline-form" style={{ marginTop: 8 }}>
                  <button onClick={apply} disabled={busy || !preview.can_apply}>
                    Import {preview.counts.add + preview.counts.update} row(s)</button>
                  <button className="secondary" onClick={close}>Cancel</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
