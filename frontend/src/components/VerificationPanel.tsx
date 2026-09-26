import { Fragment, useEffect, useState } from "react";
import type { VerificationReport, CheckResult, CheckDeviation } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
  // When provided (reviewers only), FAIL/WARN rows get a "Raise observation" link.
  onRaiseObservation?: (r: CheckResult) => void;
  // Designer on a draft layout: a failing check can be accepted as a station deviation.
  canRecordDeviations?: boolean;
}

const rowKey = (r: CheckResult) => `${r.clause}|${r.subject_ref ?? ""}`;

export function VerificationPanel({ stationId, onRaiseObservation, canRecordDeviations }: Props) {
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [deviations, setDeviations] = useState<CheckDeviation[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState({ reason: "", reference: "" });
  const [error, setError] = useState<string | null>(null);

  async function loadDeviations() {
    try { setDeviations(await api.listDeviations(stationId)); } catch { /* older server */ }
  }
  useEffect(() => { setReport(null); loadDeviations(); }, [stationId]);

  async function runVerification() {
    setLoading(true); setError(null);
    try {
      setReport(await api.verifyStation(stationId));
      await loadDeviations();
    } finally {
      setLoading(false);
    }
  }

  async function accept(r: CheckResult) {
    setError(null);
    try {
      await api.addDeviation(stationId, { clause: r.clause, subject_ref: r.subject_ref, reason: form.reason.trim(),
                                          reference: form.reference.trim() || null });
      setEditing(null); setForm({ reason: "", reference: "" });
      await runVerification();
    } catch (e) { setError(String(e)); }
  }

  async function withdraw(d: CheckDeviation) {
    if (!confirm(`Withdraw the deviation for ${d.clause} ${d.subject_ref ?? ""}? The check will show as failing again.`)) return;
    setError(null);
    try { await api.deleteDeviation(stationId, d.id); await runVerification(); } catch (e) { setError(String(e)); }
  }

  const s = report?.summary;
  const devCount = s?.deviation_count ?? 0;
  const cols = 4 + (onRaiseObservation || canRecordDeviations ? 1 : 0);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Annexure-H Verification</h3>
        <button onClick={runVerification} disabled={loading}>
          {loading ? "Running…" : "Run verification"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}

      {report && s && (
        <>
          <div className={`status-banner ${s.fail_count === 0 ? "ok" : "fail"}`}>
            {s.fail_count === 0
              ? `All ${s.total_checks} automated checks passed`
              : `${s.fail_count} of ${s.total_checks} checks FAILED — clauses: ${s.clauses_failing.join(", ")}`}
            {devCount > 0 && ` · ${devCount} accepted as station deviation(s)`}
          </div>

          <table className="register-table">
            <thead>
              <tr><th>Clause</th><th>Check</th><th>Status</th><th>Detail</th>{cols > 4 && <th></th>}</tr>
            </thead>
            <tbody>
              {report.results.map((r, i) => (
                <Fragment key={i}>
                  <tr className={`row-${r.status.toLowerCase()}`}>
                    <td>{r.clause}</td>
                    <td>{r.title}</td>
                    <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                    <td>{r.message}</td>
                    {cols > 4 && (
                      <td className="row-actions">
                        {onRaiseObservation && (r.status === "FAIL" || r.status === "WARN" || r.status === "DEVIATION") && (
                          <button className="link-btn" onClick={() => onRaiseObservation(r)}>Raise observation</button>
                        )}
                        {canRecordDeviations && r.status === "FAIL" && editing !== rowKey(r) && (
                          <button className="link-btn" onClick={() => { setEditing(rowKey(r)); setForm({ reason: "", reference: "" }); }}>
                            Accept as station deviation…</button>
                        )}
                      </td>
                    )}
                  </tr>
                  {editing === rowKey(r) && (
                    <tr><td></td><td colSpan={cols - 1}>
                      <div className="inline-form wrap">
                        <input style={{ flex: 3 }} placeholder="Why this rule does not fit this station (e.g. TIN boundary as per SIP)"
                          value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
                        <input style={{ flex: 1 }} placeholder="SIP / LC reference" value={form.reference}
                          onChange={(e) => setForm({ ...form, reference: e.target.value })} />
                        <button disabled={form.reason.trim().length < 5} onClick={() => accept(r)}>Record deviation</button>
                        <button className="secondary" onClick={() => setEditing(null)}>Cancel</button>
                      </div>
                    </td></tr>
                  )}
                </Fragment>
              ))}
              {report.results.length === 0 && (
                <tr><td colSpan={cols} className="muted">No checks produced results — add Elements/Tags/TINs first</td></tr>
              )}
            </tbody>
          </table>

          <p className="muted small">
            Checklist configuration v{report.checklist_version ?? "—"}. Manual items are confirmed in the
            Manual Checklist below; rules are managed in the Checklist tab.
          </p>
          {(report.rules_disabled ?? []).length > 0 && (
            <div className="status-banner warn">Automated rules switched off by an admin: {(report.rules_disabled ?? []).join(", ")}</div>
          )}
        </>
      )}

      {deviations.length > 0 && (
        <>
          <h4>Station deviations ({deviations.length})</h4>
          <p className="muted small">
            Station designs and TIN allocations follow the station's Signal Interlocking Plan and LC gate arrangements.
            A failing check recorded here shows as DEVIATION and does not block self-check; the checker and approver
            see each one with its reason.
          </p>
          <table className="register-table">
            <thead><tr><th>Check</th><th>Reason</th><th>Reference</th><th>Recorded</th><th></th></tr></thead>
            <tbody>
              {deviations.map((d) => (
                <tr key={d.id} className={d.in_use ? "" : "row-warn"}>
                  <td><strong>{d.clause}</strong> {d.subject_ref ?? "(station)"}</td>
                  <td>{d.reason}</td>
                  <td>{d.reference ?? "—"}</td>
                  <td className="small">{d.created_by} · {d.created_at.slice(0, 10)}
                    {!d.in_use && <div className="muted">No longer needed — the check passes now</div>}</td>
                  <td>{canRecordDeviations && <button className="link-btn" onClick={() => withdraw(d)}>Withdraw</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
