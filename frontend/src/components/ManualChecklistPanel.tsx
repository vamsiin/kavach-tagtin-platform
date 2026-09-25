import { useEffect, useState } from "react";
import type { ManualChecklist } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
  stationStatus: string;
}

/** FR-006: manual checklist items a reviewer confirms for this station in the current
 *  review cycle. A new cycle (rework / revise / reopen) starts them afresh. */
export function ManualChecklistPanel({ stationId, stationStatus }: Props) {
  const [data, setData] = useState<ManualChecklist | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.stationChecklist(stationId).then(setData).catch((e) => setError(String(e))); }, [stationId, stationStatus]);

  async function respond(ruleId: number, status: string) {
    setError(null);
    try {
      setData(await api.respondChecklist(stationId, ruleId, status, notes[ruleId] ?? ""));
    } catch (e) { setError(String(e)); }
  }

  if (!data) return null;
  const s = data.summary;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Manual Checklist <span className="muted small">{s.answered}/{s.total} confirmed this cycle</span></h3>
      </div>
      {s.pending_blocking.length > 0 && (
        <div className="status-banner warn">Must be confirmed before “Mark checked”: {s.pending_blocking.join(", ")}</div>
      )}
      {s.failed.length > 0 && <div className="status-banner fail">Confirmed as FAIL: {s.failed.join(", ")}</div>}
      {!data.can_respond && (
        <p className="muted small">Checkers, approvers and admins confirm these items while the station is Submitted or Checked.</p>
      )}
      {error && <div className="error">{error}</div>}
      <table className="register-table">
        <thead><tr><th>Clause</th><th>What must be checked by hand</th><th>Result</th><th>By</th>{data.can_respond && <th>Confirm</th>}</tr></thead>
        <tbody>
          {data.items.map((i) => (
            <tr key={i.rule_id} className={i.status === "FAIL" ? "row-fail" : i.status === "PASS" ? "row-pass" : ""}>
              <td><strong>{i.clause}</strong>{i.blocking && <div><span className="badge warn">blocks check</span></div>}</td>
              <td className="small">{i.description || i.title}</td>
              <td>{i.status ? <span className={`badge ${i.status.toLowerCase()}`}>{i.status}</span> : <span className="muted">pending</span>}
                {i.note && <div className="small">{i.note}</div>}</td>
              <td className="small">{i.responded_by ?? "—"}{i.responded_at && <div className="muted">{i.responded_at.slice(0, 16).replace("T", " ")}</div>}</td>
              {data.can_respond && (
                <td className="confirm-cell">
                  <input placeholder="Note (required for FAIL / NA)" value={notes[i.rule_id] ?? ""}
                    onChange={(e) => setNotes({ ...notes, [i.rule_id]: e.target.value })} />
                  <div className="inline-form">
                    <button onClick={() => respond(i.rule_id, "PASS")}>Pass</button>
                    <button className="secondary" onClick={() => respond(i.rule_id, "FAIL")}>Fail</button>
                    <button className="secondary" onClick={() => respond(i.rule_id, "NA")}>N/A</button>
                  </div>
                </td>
              )}
            </tr>
          ))}
          {data.items.length === 0 && <tr><td colSpan={5} className="muted">No manual checklist items are enabled.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
