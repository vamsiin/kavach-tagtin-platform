import { useEffect, useState } from "react";
import type { Station, User } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";

interface Props {
  station: Station;
  assignedChecker: string | null;
  onStationChanged: (s: Station) => void;
}

/** Project Manager: assign the designer; reassign the checker while submitted. */
export function AssignmentPanel({ station, assignedChecker, onStationChanged }: Props) {
  const can = useCan();
  const [designers, setDesigners] = useState<User[]>([]);
  const [checkers, setCheckers] = useState<User[]>([]);
  const [designer, setDesigner] = useState(station.assigned_designer ?? "");
  const [checker, setChecker] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const canDesigner = can("assign.designer");
  const canChecker = can("assign.checker") && station.status === "submitted";

  useEffect(() => {
    setDesigner(station.assigned_designer ?? "");
    if (canDesigner) api.listUsersByRole("designer", station.workspace_id).then(setDesigners).catch(() => {});
    if (canChecker) api.listUsersByRole("checker", station.workspace_id).then(setCheckers).catch(() => {});
  }, [station.id, station.status, station.assigned_designer]);

  if (!canDesigner && !canChecker) return null;

  async function run(fn: () => Promise<Station>, ok: string) {
    setError(null); setMsg(null);
    try { onStationChanged(await fn()); setMsg(ok); setComment(""); } catch (e) { setError(String(e)); }
  }

  return (
    <div className="panel">
      <h3>Assignment</h3>
      <div className="inline-form wrap">
        {canDesigner && (
          <>
            <label className="small">Designer&nbsp;
              <select value={designer} onChange={(e) => setDesigner(e.target.value)}>
                <option value="">Any designer (unassigned)</option>
                {designers.map((d) => <option key={d.username} value={d.username}>{d.full_name} ({d.username})</option>)}
              </select>
            </label>
            <button disabled={designer === (station.assigned_designer ?? "")}
              onClick={() => run(() => api.assignDesigner(station.id, designer || null, comment), "Designer assignment saved")}>
              Assign designer
            </button>
          </>
        )}
        {canChecker && (
          <>
            <label className="small">Checker (now {assignedChecker ?? "—"})&nbsp;
              <select value={checker} onChange={(e) => setChecker(e.target.value)}>
                <option value="">— choose —</option>
                {checkers.filter((c) => c.username !== assignedChecker).map((c) =>
                  <option key={c.username} value={c.username}>{c.full_name} ({c.username})</option>)}
              </select>
            </label>
            <button disabled={!checker}
              onClick={() => run(() => api.reassignChecker(station.id, checker, comment), `Reassigned to ${checker}`)}>
              Reassign checker
            </button>
          </>
        )}
        <input placeholder="Comment (recorded)" value={comment} onChange={(e) => setComment(e.target.value)} style={{ minWidth: 220 }} />
      </div>
      <p className="muted small">
        When a designer is assigned, only they (or an admin) can edit the registers and inputs, self-check and submit.
        Checker reassignment is available while the station is Submitted for check.
      </p>
      {msg && <div className="status-banner ok">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
