import { useEffect, useState } from "react";
import type { Traceability } from "../types";
import { api } from "../api";

interface Props {
  stationId: number;
}

/** FR-011: Input document → Tag/Element/TIN → Layout version → Workflow
 *  (each event carries the input package snapshot that was current at the time). */
export function TraceabilityPanel({ stationId }: Props) {
  const [data, setData] = useState<Traceability | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "untraced" | "outdated">("all");

  async function load() {
    setError(null);
    try { setData(await api.getTraceability(stationId)); } catch (e) { setError(String(e)); }
  }
  useEffect(() => { load(); }, [stationId]);

  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!data) return <div className="panel"><p className="muted">Loading…</p></div>;

  const rows = data.rows.filter((r) =>
    filter === "all" ? true : filter === "untraced" ? !r.source : r.source_outdated);
  const s = data.summary;

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <h3>Traceability — {data.station_name} <span className="muted small">layout {data.layout_version} · {data.status}</span></h3>
          <button className="secondary" onClick={load}>Refresh</button>
        </div>
        <div className="workflow-meta">
          <span>Tags traced: <strong>{s.tags_traced}/{s.tags}</strong></span>
          <span>Elements traced: <strong>{s.elements_traced}/{s.elements}</strong></span>
          <span>Current inputs: <strong>{s.current_documents}</strong></span>
          <span>On superseded inputs: <strong>{s.rows_on_superseded_inputs}</strong></span>
        </div>
        {data.gaps.length === 0
          ? <div className="status-banner ok">No traceability gaps.</div>
          : data.gaps.map((g, i) => <div key={i} className="status-banner fail">{g}</div>)}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Register → Source</h3>
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="all">All rows</option>
            <option value="untraced">No source</option>
            <option value="outdated">On superseded revision</option>
          </select>
        </div>
        <table className="register-table">
          <thead><tr><th>Kind</th><th>Ref</th><th>Type</th><th>km</th><th>Linked element</th><th>Source input</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.kind}-${r.id}`} className={!r.source || r.source_outdated ? "row-fail" : ""}>
                <td>{r.kind}</td>
                <td>{r.ref}</td>
                <td>{r.type}</td>
                <td>{r.location_km?.toFixed(3)}</td>
                <td>{r.linked_element_ref ?? "—"}</td>
                <td>
                  {r.source
                    ? <>{r.source.doc_type} rev {r.source.revision}{r.source.version_label ? ` (${r.source.version_label})` : ""}
                        <div className="muted small">{r.source.original_filename}{r.source_outdated ? " — SUPERSEDED" : ""}</div></>
                    : <span className="muted">none</span>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="muted">Nothing to show.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3>Workflow → Input package at each step</h3>
        <table className="register-table">
          <thead><tr><th>When</th><th>Action</th><th>By</th><th>Fails</th><th>Inputs in force</th></tr></thead>
          <tbody>
            {data.workflow.map((e) => (
              <tr key={e.id}>
                <td className="small">{e.timestamp.slice(0, 16).replace("T", " ")}</td>
                <td>{e.action} <span className="muted small">({e.from_status} → {e.to_status})</span></td>
                <td>{e.actor_username}</td>
                <td>{e.verification_fail_count ?? "—"}</td>
                <td className="small">
                  {e.input_snapshot == null
                    ? <span className="muted">not recorded</span>
                    : e.input_snapshot.length === 0
                      ? <span className="muted">no inputs uploaded</span>
                      : e.input_snapshot.map((i) => (
                          <div key={i.id} title={i.sha256}>{i.doc_type} rev {i.revision} — {i.original_filename}</div>
                        ))}
                </td>
              </tr>
            ))}
            {data.workflow.length === 0 && <tr><td colSpan={5} className="muted">No workflow events yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
