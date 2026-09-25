import { useEffect, useState, useCallback } from "react";
import type { Station, WorkflowStatus, User, RailwaySubmission } from "../types";
import { STATUS_LABELS, ACTION_LABELS } from "../types";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";

interface Props {
  station: Station;
  onStationChanged: (s: Station) => void;
}

// BRD FR-009 lifecycle, in order. "Rework" is not a separate status: it is a
// request_changes back to Draft, visible in the history below.
const LIFECYCLE = ["draft", "self_checked", "submitted", "checked", "approved", "railway_submitted"];

/** Turn "409 Conflict: {json}" from api.request into something readable, and
 *  surface the failing clauses when a self-check is rejected. */
function describeError(err: unknown): { text: string; clauses?: string[] } {
  const raw = String(err).replace(/^Error:\s*/, "");
  const idx = raw.indexOf("{");
  if (idx >= 0) {
    try {
      const body = JSON.parse(raw.slice(idx));
      const d = body.detail;
      if (typeof d === "string") return { text: d };
      if (d && typeof d === "object" && "message" in d) return { text: d.message, clauses: d.clauses_failing };
      if (Array.isArray(d)) return { text: d.map((x: { msg?: string }) => x.msg).join("; ") };
    } catch { /* fall through */ }
  }
  return { text: raw };
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

export function WorkflowPanel({ station, onStationChanged }: Props) {
  const { user } = useAuth();
  const [status, setStatus] = useState<WorkflowStatus | null>(null);
  const [error, setError] = useState<{ text: string; clauses?: string[] } | null>(null);
  const [showRailwayForm, setShowRailwayForm] = useState(false);
  const [railway, setRailway] = useState({ reference_no: "", submitted_on: today(), addressed_to: "", remarks: "" });
  const [submissions, setSubmissions] = useState<RailwaySubmission[]>([]);
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
      setSubmissions(await api.listRailwaySubmissions(station.id));
    } catch (err) {
      setError(describeError(err));
    }
  }, [station.id]);

  useEffect(() => { reload(); }, [reload]);

  async function runAction(action: string, actionComment = "", assignedChecker = "") {
    setSubmitting(true);
    setError(null);
    try {
      let updatedStation: Station;
      switch (action) {
        case "self_check": updatedStation = await api.selfCheckStation(station.id, actionComment); break;
        case "revise": updatedStation = await api.reviseStation(station.id, actionComment); break;
        case "railway_submit":
          await api.railwaySubmit(station.id, {
            reference_no: railway.reference_no, submitted_on: railway.submitted_on,
            addressed_to: railway.addressed_to || undefined, remarks: railway.remarks || undefined,
          });
          updatedStation = await api.getStation(station.id);
          break;
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
      setShowRailwayForm(false);
      setRailway({ reference_no: "", submitted_on: today(), addressed_to: "", remarks: "" });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleActionClick(action: string) {
    if (action === "request_changes") {
      setCommentAction(action);
      return;
    }
    if (action === "railway_submit") {
      setError(null);
      setShowRailwayForm(true);
      return;
    }
    if (action === "submit") {
      setError(null);
      try {
        setCheckers(await api.listUsersByRole("checker"));
        setShowAssignForm(true);
      } catch (err) {
        setError(describeError(err));
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

      <div className="lifecycle">
        {(() => {
          // Layouts that went through the workflow before Self Check existed have no
          // self_check event in the current cycle -- show that step as skipped rather
          // than implying it happened.
          const resets = ["request_changes", "revise", "reopen"];
          let selfChecked = false;
          for (const ev of status.history) {
            if (resets.includes(ev.action)) selfChecked = false;
            if (ev.action === "self_check") selfChecked = true;
          }
          const cur = LIFECYCLE.indexOf(status.status);
          return LIFECYCLE.map((st, i) => {
            const skipped = st === "self_checked" && i < cur && !selfChecked;
            const cls = skipped ? "skipped" : i < cur ? "done" : i === cur ? "current" : "";
            return (
              <span key={st} style={{ display: "contents" }}>
                {i > 0 && <span className="arrow">→</span>}
                <span className={`step ${cls}`} title={skipped ? "Not recorded — this cycle predates the Self Check step" : undefined}>
                  {STATUS_LABELS[st]}{skipped ? " (not recorded)" : ""}
                </span>
              </span>
            );
          });
        })()}
      </div>

      <div className="workflow-meta">
        <span>Designer: <strong>{status.assigned_designer ?? "any"}</strong></span>
        {status.self_checked_by && <span>Self-checked by: <strong>{status.self_checked_by}</strong></span>}
        {status.submitted_by && <span>Submitted by: <strong>{status.submitted_by}</strong></span>}
        {status.assigned_checker && <span>Assigned checker: <strong>{status.assigned_checker}</strong></span>}
        {status.checked_by && <span>Checked by: <strong>{status.checked_by}</strong></span>}
      </div>

      <div className="workflow-actions">
        {status.allowed_actions.filter((a) => a !== "reassign").length === 0 && (
          <span className="muted small">
            {user ? `No actions available for role '${user.role}' at this status.` : ""}
          </span>
        )}
        {/* "reassign" is done from the Assignment panel above (it needs a checker picker) */}
        {status.allowed_actions.filter((a) => a !== "reassign").map((action) => (
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

      {status.status === "draft" && status.allowed_actions.includes("self_check") && (
        <p className="muted small">
          Self-check runs the full Annexure-H verification on the server. It only passes with zero
          failures, and then locks the registers and inputs. Use "Revise" to unlock them again.
        </p>
      )}

      {showRailwayForm && (
        <div className="comment-modal">
          <div className="form-grid">
            <label>Reference / letter no. *
              <input value={railway.reference_no} onChange={(e) => setRailway({ ...railway, reference_no: e.target.value })} />
            </label>
            <label>Date sent *
              <input type="date" value={railway.submitted_on} onChange={(e) => setRailway({ ...railway, submitted_on: e.target.value })} />
            </label>
            <label>Addressed to
              <input placeholder="e.g. Sr. DSTE / Zone" value={railway.addressed_to} onChange={(e) => setRailway({ ...railway, addressed_to: e.target.value })} />
            </label>
          </div>
          <textarea placeholder="Remarks (optional)" rows={2} value={railway.remarks}
            onChange={(e) => setRailway({ ...railway, remarks: e.target.value })} />
          <p className="muted small">
            This records the approved layout (version {station.layout_version}) as sent to the Railway, and keeps
            a copy of the registers and input revisions exactly as they are now.
          </p>
          <div className="comment-modal-actions">
            <button onClick={() => runAction("railway_submit")}
              disabled={submitting || !railway.reference_no.trim() || !railway.submitted_on}>
              Record submission
            </button>
            <button onClick={() => setShowRailwayForm(false)} className="secondary">Cancel</button>
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

      {error && (
        <div className="error">
          {error.text}
          {error.clauses && error.clauses.length > 0 && (
            <ul>{error.clauses.map((c) => <li key={c}>Failing clause {c}</li>)}</ul>
          )}
        </div>
      )}

      {submissions.length > 0 && (
        <>
          <h4 style={{ marginBottom: "0.25rem" }}>Railway submissions</h4>
          <table className="register-table">
            <thead>
              <tr><th>Reference</th><th>Date sent</th><th>To</th><th>Layout</th><th>Package</th><th>Recorded by</th></tr>
            </thead>
            <tbody>
              {submissions.map((r) => (
                <tr key={r.id}>
                  <td>{r.reference_no}{r.remarks && <div className="muted small">{r.remarks}</div>}</td>
                  <td>{r.submitted_on}</td>
                  <td>{r.addressed_to ?? "—"}</td>
                  <td>{r.layout_version}</td>
                  <td className="small">
                    {r.layout_snapshot.elements.length} elements · {r.layout_snapshot.tags.length} tags · {r.layout_snapshot.tins.length} TINs
                    <div className="muted">{(r.input_snapshot ?? []).map((i) => `${i.doc_type} r${i.revision}`).join(", ") || "no inputs"}</div>
                  </td>
                  <td>{r.recorded_by}<div className="muted small">{r.recorded_at.slice(0, 16).replace("T", " ")}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {status.history.length > 0 && (
        <table className="register-table" style={{ marginTop: "0.75rem" }}>
          <thead>
            <tr><th>When</th><th>Action</th><th>By</th><th>Assigned to</th><th>Result</th><th>Fails</th><th>Comment</th></tr>
          </thead>
          <tbody>
            {status.history.map((ev) => (
              <tr key={ev.id}>
                <td className="small">{new Date(ev.timestamp).toLocaleString()}</td>
                <td>{ACTION_LABELS[ev.action] ?? ev.action}</td>
                <td>{ev.actor_username} <span className="muted small">({ev.actor_role})</span></td>
                <td>{ev.target_username || "—"}</td>
                <td>{STATUS_LABELS[ev.to_status] ?? ev.to_status}</td>
                <td>{ev.verification_fail_count ?? "—"}</td>
                <td className="small">{ev.comment || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
