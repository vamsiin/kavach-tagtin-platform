import { useEffect, useState } from "react";
import type { Dashboard, DashboardRow } from "../types";
import { STATUS_LABELS, ACTION_LABELS } from "../types";
import { api } from "../api";

interface Props {
  onOpen: (stationId: number) => void;
}

const STALE_DAYS = 7;

/** Portfolio view for everyone (primarily the Project Manager): where every station
 *  is, who has it, how long it has sat there, and what is blocking it. */
export function DashboardPanel({ onOpen }: Props) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  async function load() {
    setError(null);
    try { setData(await api.dashboard()); } catch (e) { setError(String(e)); }
  }
  useEffect(() => { load(); }, []);

  if (error) return <div className="panel"><div className="error">{error}</div></div>;
  if (!data) return <div className="panel"><p className="muted">Loading dashboard…</p></div>;

  const rows = data.stations.filter((r) =>
    filter === "all" ? true : filter === "attention" ? needsAttention(r) : r.status === filter);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Portfolio Dashboard <span className="muted small">{data.total} station(s)</span></h3>
        <button className="secondary" onClick={load}>Refresh</button>
      </div>
      <div className="status-chips">
        <button className={filter === "all" ? "chip active" : "chip"} onClick={() => setFilter("all")}>All {data.total}</button>
        <button className={filter === "attention" ? "chip active" : "chip"} onClick={() => setFilter("attention")}>
          Needs attention {data.stations.filter(needsAttention).length}
        </button>
        {Object.entries(data.by_status).map(([s, n]) => (
          <button key={s} className={filter === s ? "chip active" : "chip"} onClick={() => setFilter(s)}>
            {STATUS_LABELS[s] ?? s} {n}
          </button>
        ))}
      </div>
      <table className="register-table dashboard-table">
        <thead>
          <tr><th>Station</th><th>Status</th><th>Layout</th><th>Designer</th><th>Checker</th><th>In status</th>
            <th>Last action</th><th>Checks</th><th>Observations</th><th>Inputs</th><th>Railway</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)} title="Open station">
              <td><strong>{r.name}</strong> <span className="muted small">({r.kavach_station_id})</span></td>
              <td><span className={`status-pill status-${r.status}`}>{STATUS_LABELS[r.status] ?? r.status}</span></td>
              <td>{r.layout_version}</td>
              <td className="small">{r.assigned_designer ?? <span className="muted">any</span>}</td>
              <td className="small">{r.assigned_checker ?? "—"}</td>
              <td className={r.days_in_status !== null && r.days_in_status > STALE_DAYS && !["approved", "railway_submitted"].includes(r.status) ? "warn-text" : ""}>
                {r.days_in_status === null ? "—" : `${r.days_in_status} d`}
              </td>
              <td className="small">{r.last_action ? `${ACTION_LABELS[r.last_action] ?? r.last_action} · ${r.last_actor}` : "—"}</td>
              <td>{r.fail_count > 0 ? <span className="badge fail">{r.fail_count} fail</span>
                : r.warn_count > 0 ? <span className="badge warn">{r.warn_count} warn</span>
                : <span className="badge pass">pass</span>}</td>
              <td>{r.open_observations > 0 ? <span className="badge fail">{r.open_observations} open</span>
                : r.unverified_observations > 0 ? <span className="badge warn">{r.unverified_observations} to verify</span>
                : <span className="muted">—</span>}</td>
              <td>{r.missing_inputs > 0 ? <span className="badge warn">{r.missing_inputs} missing</span> : <span className="badge pass">ok</span>}</td>
              <td className="small">{r.railway_reference ?? "—"}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={11} className="muted">No stations match.</td></tr>}
        </tbody>
      </table>
      <p className="muted small">Click a row to open the station. "In status" turns amber after {STALE_DAYS} days without progress.</p>
    </div>
  );
}

function needsAttention(r: DashboardRow): boolean {
  if (["approved", "railway_submitted"].includes(r.status)) return false;
  return r.fail_count > 0 || r.open_observations > 0 || r.unverified_observations > 0 ||
    (r.days_in_status !== null && r.days_in_status > STALE_DAYS);
}
