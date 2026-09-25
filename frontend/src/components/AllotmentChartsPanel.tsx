import { Fragment, useEffect, useRef, useState } from "react";
import type { AllotmentChart, AllotmentChartDetail, AllotmentParse, AllotmentRow } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";

const TEMPLATE_HEADER = ["S.No.", "Station / Block Section", "Division Code", "Station Code", "Station ID",
  "TIN Range", "TIN Allotted", "RFID Tag Numbers Range", "Total"];

function downloadTemplate() {
  const csv = TEMPLATE_HEADER.join(",") + "\n26,Aler,00,103,00103,169-192,,775-902,128\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "allotment-chart-template.csv";
  a.click();
}

const strip = (r: AllotmentRow): AllotmentRow => {
  const { id: _i, tag_count: _t, tin_count: _n, problems: _p, ...rest } = r;
  return rest as AllotmentRow;
};

function RowsTable({ rows }: { rows: AllotmentRow[] }) {
  return (
    <table className="register-table">
      <thead>
        <tr><th>S.No</th><th>Station / block section</th><th>Stn code</th><th>Station ID</th><th>TIN range</th>
          <th>TINs</th><th>Tag range</th><th>Tags</th><th>Total (chart)</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <Fragment key={i}>
            <tr className={r.problems?.length ? "row-fail" : ""}>
              <td>{r.s_no ?? ""}</td><td><strong>{r.name}</strong></td><td>{r.station_code ?? ""}</td>
              <td>{r.station_id ?? ""}</td><td>{r.tin_ranges ?? "—"}</td><td>{r.tin_count ?? ""}</td>
              <td>{r.tag_ranges ?? "—"}</td><td>{r.tag_count ?? ""}</td><td>{r.tag_total ?? "—"}</td>
            </tr>
            {!!r.problems?.length && (
              <tr><td></td><td colSpan={8} className="small">{r.problems.map((p) => <div key={p} className="error">{p}</div>)}</td></tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

/** BRD BR-001 / FR-004: the RFID Tag / TIN allotment charts issued by RDSO / the
 *  Railway. Division-level reference data; a revised chart supersedes the current one. */
export function AllotmentChartsPanel() {
  const can = useCan();
  const canManage = can("allotment.manage");
  const [charts, setCharts] = useState<AllotmentChart[]>([]);
  const [view, setView] = useState<AllotmentChartDetail | null>(null);
  const [preview, setPreview] = useState<AllotmentParse | null>(null);
  const [meta, setMeta] = useState({ title: "", division: "", reference_no: "", issued_on: "", issued_by: "", remarks: "" });
  const [supersede, setSupersede] = useState(true);
  const [original, setOriginal] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sheetInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [attachFor, setAttachFor] = useState<number | null>(null);

  async function reload() { setCharts(await api.listAllotmentCharts()); }
  useEffect(() => { reload().catch((e) => setError(String(e))); }, []);

  async function pickSheet(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setError(null); setView(null);
    try { setPreview(await api.parseAllotmentChart(f)); } catch (err) { setError(String(err)); }
  }

  async function save() {
    if (!preview) return;
    setBusy(true); setError(null);
    try {
      const c = await api.createAllotmentChart({
        ...meta, reference_no: meta.reference_no || null, issued_on: meta.issued_on || null,
        issued_by: meta.issued_by || null, remarks: meta.remarks || null,
        rows: preview.rows.map(strip), supersede_current: supersede,
      });
      if (original) await api.attachAllotmentFile(c.id, original);
      setPreview(null); setOriginal(null);
      setMeta({ title: "", division: "", reference_no: "", issued_on: "", issued_by: "", remarks: "" });
      await reload();
      setView(await api.getAllotmentChart(c.id));
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  async function attach(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || attachFor == null) return;
    try { await api.attachAllotmentFile(attachFor, f); await reload(); } catch (err) { setError(String(err)); }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <h3>RFID Tag / TIN allotment charts</h3>
          {canManage && !preview && (
            <div className="inline-form">
              <button className="secondary" onClick={downloadTemplate}>Download template</button>
              <button onClick={() => sheetInput.current?.click()}>Import chart (.xlsx / .csv)…</button>
            </div>
          )}
          <input ref={sheetInput} type="file" accept=".xlsx,.csv" style={{ display: "none" }} onChange={pickSheet} />
          <input ref={fileInput} type="file" accept=".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg" style={{ display: "none" }} onChange={attach} />
        </div>
        <p className="muted small">
          The chart issued by RDSO / the Railway for a division (BR-001). Each station and adjacent block section is
          matched to its row by KAVACH station ID. Tag and TIN numbers on a layout must fall in the station's own row or
          its adjacent sections'. Charts are never edited: load a revised chart and it supersedes the current one for
          that division. {!canManage && "Only a Configuration Manager or admin can load charts."}
        </p>
        {error && <div className="error">{error}</div>}

        <table className="register-table">
          <thead><tr><th>Chart</th><th>Division</th><th>Reference</th><th>Issued</th><th>Rows</th><th>Status</th><th>Original</th><th></th></tr></thead>
          <tbody>
            {charts.map((c) => (
              <tr key={c.id}>
                <td><strong>{c.title}</strong><div className="muted small">loaded by {c.created_by} · {c.created_at.slice(0, 10)}</div></td>
                <td>{c.division}</td><td className="small">{c.reference_no ?? "—"}</td><td>{c.issued_on ?? "—"}</td>
                <td>{c.row_count}</td>
                <td>{c.is_current ? <span className="badge pass">Current</span>
                  : <span className="badge na">Superseded{c.superseded_by_id ? ` by #${c.superseded_by_id}` : ""}</span>}</td>
                <td className="small">
                  {c.source_filename
                    ? <button className="link-btn" onClick={() => api.downloadAllotmentFile(c).catch((e) => setError(String(e)))}>{c.source_filename}</button>
                    : "—"}
                  {canManage && <div><button className="link-btn" onClick={() => { setAttachFor(c.id); fileInput.current?.click(); }}>
                    {c.source_filename ? "Replace file" : "Attach issued chart"}</button></div>}
                </td>
                <td className="row-actions">
                  <button className="link-btn" onClick={() => api.getAllotmentChart(c.id).then(setView).catch((e) => setError(String(e)))}>View rows</button>
                  {canManage && !c.is_current && (
                    <button className="link-btn" onClick={() => api.makeAllotmentCurrent(c.id).then(reload).catch((e) => setError(String(e)))}>Make current</button>
                  )}
                </td>
              </tr>
            ))}
            {charts.length === 0 && <tr><td colSpan={8} className="muted">No allotment chart loaded. Numbers are only checked against 1-1023 / 1-255 until one is.</td></tr>}
          </tbody>
        </table>
      </div>

      {preview && (
        <div className="panel">
          <div className="panel-header"><h3>Check the imported chart before saving</h3>
            <button className="secondary" onClick={() => setPreview(null)}>Cancel</button></div>
          {preview.errors.length > 0 && (
            <div className="status-banner fail">Fix these in the spreadsheet and import again:
              <ul>{preview.errors.map((e) => <li key={e}>{e}</li>)}</ul></div>
          )}
          {preview.warnings.length > 0 && (
            <div className="status-banner warn">Recorded as on the chart, but check:
              <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
          )}
          <div className="form-grid">
            <label>Title<input value={meta.title} placeholder="Secunderabad Division RFID Tag / TIN Allocation Chart"
              onChange={(e) => setMeta({ ...meta, title: e.target.value })} /></label>
            <label>Division<input value={meta.division} placeholder="Secunderabad" onChange={(e) => setMeta({ ...meta, division: e.target.value })} /></label>
            <label>Letter reference<input value={meta.reference_no} placeholder="RDSO-SIG0MISC(GEN)/1/2021"
              onChange={(e) => setMeta({ ...meta, reference_no: e.target.value })} /></label>
            <label>Issued on<input type="date" value={meta.issued_on} onChange={(e) => setMeta({ ...meta, issued_on: e.target.value })} /></label>
            <label>Issued by<input value={meta.issued_by} placeholder="RDSO, ED/Telecom-II" onChange={(e) => setMeta({ ...meta, issued_by: e.target.value })} /></label>
            <label>Remarks<input value={meta.remarks} onChange={(e) => setMeta({ ...meta, remarks: e.target.value })} /></label>
          </div>
          <div className="inline-form wrap">
            <label className="checkbox-label"><input type="checkbox" checked={supersede} onChange={(e) => setSupersede(e.target.checked)} />
              Make this the current chart for the division</label>
            <label className="small">Issued chart (PDF, optional): <input type="file" accept=".pdf,.xlsx,.xls,.png,.jpg,.jpeg"
              onChange={(e) => setOriginal(e.target.files?.[0] ?? null)} /></label>
            <button onClick={save} disabled={busy || preview.errors.length > 0 || !meta.title.trim() || !meta.division.trim()}>
              {busy ? "Saving…" : `Save chart (${preview.rows.length} rows)`}</button>
          </div>
          <RowsTable rows={preview.rows} />
        </div>
      )}

      {view && !preview && (
        <div className="panel">
          <div className="panel-header"><h3>{view.title} <span className="muted small">{view.reference_no} · {view.issued_on}</span></h3>
            <button className="secondary" onClick={() => setView(null)}>Close</button></div>
          {view.warnings.length > 0 && (
            <div className="status-banner warn">As printed on the chart, but check:
              <ul>{view.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
          )}
          <RowsTable rows={view.rows} />
        </div>
      )}
    </>
  );
}
