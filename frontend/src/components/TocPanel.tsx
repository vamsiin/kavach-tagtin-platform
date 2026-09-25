import { useRef, useState } from "react";
import type { ToCCrossValidation } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
}

export function TocPanel({ stationId }: Props) {
  const [result, setResult] = useState<ToCCrossValidation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.verifyAgainstToc(stationId, file);
      setResult(r);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Table of Control Cross-Validation</h3>
        <button onClick={() => fileInput.current?.click()} disabled={loading}>
          {loading ? "Checking…" : "Upload ToC file"}
        </button>
        <input ref={fileInput} type="file" accept=".csv,.xlsx,.xls,.docx" style={{ display: "none" }} onChange={handleUpload} />
      </div>
      <p className="muted small">
        Checks the current Tag Register against each route's expected RFID tag chain
        and inter-tag distances, as encoded in the station's Table of Control export.
        This catches placement errors that static distance rules alone would miss.
        Accepts .csv, .xlsx, .xls, or .docx — legacy .doc (Word 97-2003) is not
        supported; please save as .docx first.
      </p>

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <div className={`status-banner ${result.summary.fail_count === 0 ? "ok" : "fail"}`}>
            {result.summary.fail_count === 0
              ? `All ${result.summary.total_checks} chain checks passed`
              : `${result.summary.fail_count} of ${result.summary.total_checks} chain checks FAILED — routes: ${result.summary.routes_with_failures.join(", ")}`}
          </div>
          {result.summary.missing_tags.length > 0 && (
            <div className="status-banner fail">
              Tags expected by ToC but missing from Tag Register: {result.summary.missing_tags.join(", ")}
            </div>
          )}
          <table className="register-table">
            <thead>
              <tr><th>Route</th><th>Entry → Exit</th><th>Status</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {result.results.map((r, i) => (
                <tr key={i} className={`row-${r.status.toLowerCase()}`}>
                  <td>{r.route_s_no}</td>
                  <td>{r.entry_signal} → {r.exit_signal}</td>
                  <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                  <td>{r.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
