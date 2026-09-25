import { useEffect, useState, useCallback } from "react";
import type { Station, WorkflowStatus, User } from "../types";
import { STATUS_LABELS, ACTION_LABELS } from "../types";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";

interface Props {
  station: Station;
  onStationChanged: (s: Station) => void;
}

export function WorkflowPanel({ station, onStationChanged }: Props) {
  const { user } = useAuth();
  const [status, setStatus] = useState<WorkflowStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [commentAction, setCommentAction] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [checkers, setCheckers] = useState<User[]>([]);
  const [selectedChecker, setSelectedChecker] = useState("");

  const reload = useCallback(async () => {
    try {
      const s = await api.getWorkflowStatus(station.id);
      setStatus(s);
    } catch (err) {
      setError(String(err));
    }
  }, [station.id]);

  useEffect(() => { reload(); }, [reload]);

  async function runAction(action: string, actionComment = "", assignedChecker = "") {
    setSubmitting(true);
    setError(null);
    try {
      let updatedStation: Station;
      switch (action) {
        case "submit": updatedStation = await api.submitStation(station.id, assignedChecker, actionComment); break;
        case "check": updatedStation = await api.checkStation(station.id, actionComment); break;
        case "approve": updatedStation = await api.approveStation(station.id, actionComment); break;
        case "request_changes": updatedStation = await api.requestChanges(station.id, actionComment); break;
        case "reopen": updatedStation = await api.reopenStation(station.id, actionComment); break;
        default: return;
      }
      onStationChanged(updatedStation);
      await reload();
      setCommentAction(null);
      setComment("");
      setShowAssignForm(false);
      setSelectedChecker("");
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleActionClick(action: string) {
    if (action === "request_changes") {
      setCommentAction(action);
      return;
    }
    if (action === "submit") {
      setError(null);
      try {
        setCheckers(await api.listUsersByRole("checker"));
        setShowAssignForm(true);
      } catch (err) {
        setError(String(err));
      }
      return;
    }
    runAction(action);
  }

  if (!status) return <div className="panel">Loading workflow status…</div>;

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Workflow</h3>
        <span className={`status-pill status-${status.status}`}>
          {STATUS_LABELS[status.status] ?? status.status}
        </span>
      </div>

      <div className="workflow-meta">
        {status.submitted_by && <span>Submitted by: <strong>{status.submitted_by}</strong></span>}
        {status.assigned_checker && <span>Assigned checker: <strong>{status.assigned_checker}</strong></span>}
        {status.checked_by && <span>Checked by: <strong>{status.checked_by}</strong></span>}
      </div>

      <div className="workflow-actions">
        {status.allowed_actions.length === 0 && (
          <span className="muted small">
            {user ? `No actions available for role '${user.role}' at this status.` : ""}
          </span>
        )}
        {status.allowed_actions.map((action) => (
          <button key={action} onClick={() => handleActionClick(action)} disabled={submitting}>
            {ACTION_LABELS[action] ?? action}
          </button>
        ))}
      </div>

      {showAssignForm && (
        <div className="comment-modal">
          <label className="small" style={{ display: "block", marginBottom: "0.4rem" }}>
            Assign to Checker
          </label>
          <select value={selectedChecker} onChange={(e) => setSelectedChecker(e.target.value)}>
            <option value="">Select a checker —</option>
            {checkers.map((c) => (
              <option key={c.username} value={c.username}>{c.full_name} ({c.username})</option>
            ))}
          </select>
          {checkers.length === 0 && (
            <div className="muted small" style={{ marginTop: "0.4rem" }}>
              No checker accounts exist yet — ask an admin to create one in the Users tab.
            </div>
          )}
          <div className="comment-modal-actions">
            <button onClick={() => runAction("submit", "", selectedChecker)} disabled={submitting || !selectedChecker}>
              Submit for check
            </button>
            <button onClick={() => { setShowAssignForm(false); setSelectedChecker(""); }} className="secondary">
              Cancel
            </button>
          </div>
        </div>
      )}

      {commentAction && (
        <div className="comment-modal">
          <textarea
            placeholder="Explain what needs to change…"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
          />
          <div className="comment-modal-actions">
            <button onClick={() => runAction(commentAction, comment)} disabled={submitting || !comment.trim()}>
              Submit
            </button>
            <button onClick={() => { setCommentAction(null); setComment(""); }} className="secondary">
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {status.history.length > 0 && (
        <table className="register-table" style={{ marginTop: "0.75rem" }}>
          <thead>
            <tr><th>When</th><th>Action</th><th>By</th><th>Assigned to</th><th>Result</th><th>Comment</th></tr>
          </thead>
          <tbody>
            {status.history.map((ev) => (
              <tr key={ev.id}>
                <td className="small">{new Date(ev.timestamp).toLocaleString()}</td>
                <td>{ACTION_LABELS[ev.action] ?? ev.action}</td>
                <td>{ev.actor_username} <span className="muted small">({ev.actor_role})</span></td>
                <td>{ev.target_username || "—"}</td>
                <td>{STATUS_LABELS[ev.to_status] ?? ev.to_status}</td>
                <td className="small">{ev.comment || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
