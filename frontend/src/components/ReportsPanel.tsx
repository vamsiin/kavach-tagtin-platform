import { useEffect, useState } from "react";
import type { GeneratedReport, ReportType, Revision } from "../types";
import { STATUS_LABELS, ACTION_LABELS } from "../types";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";

interface Props {
  stationId: number;
  stationStatus: string;
}

function when(iso: string | null) {
  return (iso ?? "").slice(0, 16).replace("T", " ");
}

/** BRD FR-007 / Section 11: the eight reports, archived verification evidence,
 *  and the drawing revision table. */
export function ReportsPanel({ stationId, stationStatus }: Props) {
  const { user } = useAuth();
  const canEditRevisions = stationStatus === "draft" && (user?.role === "designer" || user?.role === "admin");

  const [types, setTypes] = useState<ReportType[]>([]);
  const [archived, setArchived] = useState<GeneratedReport[]>([]);
  const [log, setLog] = useState<GeneratedReport[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [rev, setRev] = useState({ rev_no: "", date: "", description: "" });

  async function reload() {
    const [a, l, r] = await Promise.all([
      api.reportLog(stationId, true), api.reportLog(stationId, false), api.listRevisions(stationId),
    ]);
    setArchived(a);
    setLog(l.filter((x) => !x.archived).slice(0, 25));
    setRevisions(r);
  }
  useEffect(() => { api.listReportTypes().then(setTypes).catch((e) => setError(String(e))); }, []);
  useEffect(() => { reload().catch((e) => setError(String(e))); }, [stationId]);

  async function generate(code: string, fmt: "pdf" | "docx") {
    setBusy(`${code}.${fmt}`);
    setError(null);
    try {
      await api.downloadReport(stationId, code, fmt);
      await reload();
    } catch (e) { setError(String(e)); } finally { setBusy(null); }
  }

  async function addRevision() {
    setError(null);
    try {
      await api.addRevision(stationId, { rev_no: rev.rev_no, date: rev.date || null, description: rev.description });
      setRev({ rev_no: "", date: "", description: "" });
      await reload();
    } catch (e) { setError(String(e)); }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header"><h3>Reports</h3></div>
        <p className="muted small">
          Generated from the station's current data at the moment you click. Every generation is logged.
          Verification reports are also archived automatically at each self-check, check, approval and
          Railway submission, so the evidence behind those steps is kept as it was.
        </p>
        {error && <div className="error">{error}</div>}
        <div className="report-grid">
          {types.map((t) => (
            <div key={t.code} className="report-card">
              <div className="report-title">{t.title}</div>
              <div className="muted small">{t.description}</div>
              <div className="report-actions">
                <button onClick={() => generate(t.code, "pdf")} disabled={!!busy}>
                  {busy === `${t.code}.pdf` ? "Generating…" : "PDF"}
                </button>
                <button className="secondary" onClick={() => generate(t.code, "docx")} disabled={!!busy}>
                  {busy === `${t.code}.docx` ? "Generating…" : "Word"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3>Archived verification reports</h3>
        <table className="register-table">
          <thead><tr><th>Workflow step</th><th>When</th><th>By</th><th>Layout</th><th>Status after</th><th>SHA-256</th><th></th></tr></thead>
          <tbody>
            {archived.map((a) => (
              <tr key={a.id}>
                <td>{ACTION_LABELS[a.trigger ?? ""] ?? a.trigger}</td>
                <td className="small">{when(a.generated_at)}</td>
                <td className="small">{a.generated_by}</td>
                <td>{a.layout_version}</td>
                <td className="small">{a.station_status}</td>
                <td><code title={a.sha256}>{a.sha256.slice(0, 10)}…</code></td>
                <td><button className="link-btn" onClick={() =>
                  api.downloadArchivedReport(stationId, a.id, `${a.report_id}.pdf`).catch((e) => setError(String(e)))}>Download</button></td>
              </tr>
            ))}
            {archived.length === 0 && (
              <tr><td colSpan={7} className="muted">None yet. One is archived at the next self-check, check, approval or Railway submission.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3>Drawing revision table</h3>
        <p className="muted small">The revision block as written on the drawing. It feeds the Revision History report. You can edit it only in Draft.</p>
        {canEditRevisions && (
          <div className="inline-form wrap">
            <input placeholder="Rev" value={rev.rev_no} style={{ width: 70 }} onChange={(e) => setRev({ ...rev, rev_no: e.target.value })} />
            <input type="date" value={rev.date} onChange={(e) => setRev({ ...rev, date: e.target.value })} />
            <input placeholder="Description of change" value={rev.description} style={{ flex: 1, minWidth: 260 }}
              onChange={(e) => setRev({ ...rev, description: e.target.value })} />
            <button onClick={addRevision} disabled={!rev.rev_no.trim() || !rev.description.trim()}>Add revision</button>
          </div>
        )}
        {!canEditRevisions && stationStatus !== "draft" && (
          <p className="muted small">Locked: station is {STATUS_LABELS[stationStatus] ?? stationStatus}.</p>
        )}
        <table className="register-table">
          <thead><tr><th>Rev</th><th>Date</th><th>Description</th><th>Layout</th><th>Recorded</th><th></th></tr></thead>
          <tbody>
            {revisions.map((r) => (
              <tr key={r.id}>
                <td><strong>{r.rev_no}</strong></td>
                <td>{r.date ?? "—"}</td>
                <td>{r.description}</td>
                <td>{r.layout_version ?? "—"}</td>
                <td className="small">{r.created_by} · {when(r.created_at)}</td>
                <td>{canEditRevisions && (
                  <button className="link-btn danger" onClick={async () => {
                    try { await api.deleteRevision(stationId, r.id); await reload(); } catch (e) { setError(String(e)); }
                  }}>Delete</button>
                )}</td>
              </tr>
            ))}
            {revisions.length === 0 && <tr><td colSpan={6} className="muted">No revisions recorded.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <button className="link-btn" onClick={() => setShowLog(!showLog)}>
          {showLog ? "Hide" : "Show"} generation log ({log.length} recent)
        </button>
        {showLog && (
          <table className="register-table">
            <thead><tr><th>Report</th><th>Format</th><th>When</th><th>By</th><th>Layout</th><th>Report ID</th></tr></thead>
            <tbody>
              {log.map((l) => (
                <tr key={l.id}>
                  <td>{types.find((t) => t.code === l.report_type)?.title ?? l.report_type}</td>
                  <td>{l.fmt.toUpperCase()}</td>
                  <td className="small">{when(l.generated_at)}</td>
                  <td className="small">{l.generated_by}</td>
                  <td>{l.layout_version}</td>
                  <td className="small"><code>{l.report_id}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
