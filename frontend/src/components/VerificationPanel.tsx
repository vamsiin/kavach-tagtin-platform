import { useState } from "react";
import type { VerificationReport, CheckResult } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
  // When provided (reviewers only), FAIL/WARN rows get a "Raise observation" link.
  onRaiseObservation?: (r: CheckResult) => void;
}

export function VerificationPanel({ stationId, onRaiseObservation }: Props) {
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [showManual, setShowManual] = useState(false);

  async function runVerification() {
    setLoading(true);
    try {
      const r = await api.verifyStation(stationId);
      setReport(r);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Annexure-H Verification</h3>
        <button onClick={runVerification} disabled={loading}>
          {loading ? "Running…" : "Run verification"}
        </button>
      </div>

      {report && (
        <>
          <div className={`status-banner ${report.summary.fail_count === 0 ? "ok" : "fail"}`}>
            {report.summary.fail_count === 0
              ? `All ${report.summary.total_checks} automated checks passed`
              : `${report.summary.fail_count} of ${report.summary.total_checks} checks FAILED — clauses: ${report.summary.clauses_failing.join(", ")}`}
          </div>

          <table className="register-table">
            <thead>
              <tr><th>Clause</th><th>Check</th><th>Status</th><th>Detail</th>{onRaiseObservation && <th></th>}</tr>
            </thead>
            <tbody>
              {report.results.map((r, i) => (
                <tr key={i} className={`row-${r.status.toLowerCase()}`}>
                  <td>{r.clause}</td>
                  <td>{r.title}</td>
                  <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                  <td>{r.message}</td>
                  {onRaiseObservation && (
                    <td>
                      {(r.status === "FAIL" || r.status === "WARN") && (
                        <button className="link-btn" onClick={() => onRaiseObservation(r)}>Raise observation</button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
              {report.results.length === 0 && (
                <tr><td colSpan={4} className="muted">No checks produced results — add Elements/Tags/TINs first</td></tr>
              )}
            </tbody>
          </table>

          <div className="manual-clauses">
            <button className="link-btn" onClick={() => setShowManual(!showManual)}>
              {showManual ? "Hide" : "Show"} clauses requiring manual review ({Object.keys(report.manual_clauses).length})
            </button>
            {showManual && (
              <ul>
                {Object.entries(report.manual_clauses).map(([clause, reason]) => (
                  <li key={clause}><strong>{clause}:</strong> {reason}</li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
