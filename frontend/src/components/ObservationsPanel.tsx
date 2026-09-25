import { Fragment, useEffect, useMemo, useState } from "react";
import type { Element, Observation, ObservationDraft, ObservationSummary, Tag, TIN } from "../types";
import { OBS_CATEGORIES, OBS_SEVERITIES, OBS_STATUS_LABELS } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";

interface Props {
  stationId: number;
  stationStatus: string;
  tags: Tag[];
  elements: Element[];
  tins: TIN[];
  draft: ObservationDraft | null;      // prefill, e.g. from a failing verification row
  onDraftConsumed: () => void;
  onSummary?: (s: ObservationSummary) => void;
}

const ACTION_LABELS: Record<string, string> = {
  resolve: "Mark resolved", close: "Verify & close", reopen: "Reopen",
  withdraw: "Withdraw", comment: "Comment",
};
const ACTION_PROMPTS: Record<string, string> = {
  resolve: "What did you change to address this?",
  close: "Verification note (optional)",
  reopen: "Why is the fix not adequate?",
  withdraw: "Why is this being withdrawn?",
  comment: "Add a comment…",
};
const STATUS_BADGE: Record<string, string> = {
  open: "fail", reopened: "fail", resolved: "warn", closed: "pass", withdrawn: "na",
};
const EMPTY: ObservationDraft = { description: "", severity: "major", category: "", clause: "", subject_kind: "station", subject_id: null };

function when(iso: string) {
  return iso.slice(0, 16).replace("T", " ");
}

/** BRD FR-008: tracked, individually resolvable review observations. */
export function ObservationsPanel({ stationId, stationStatus, tags, elements, tins, draft, onDraftConsumed, onSummary }: Props) {
  const can = useCan();
  const isReviewer = can("observations.raise");
  const frozen = stationStatus === "railway_submitted";

  const [items, setItems] = useState<Observation[]>([]);
  const [summary, setSummary] = useState<ObservationSummary | null>(null);
  const [filter, setFilter] = useState<"active" | "all">("active");
  const [form, setForm] = useState<ObservationDraft | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [pending, setPending] = useState<{ id: number; action: string } | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const r = await api.listObservations(stationId);
    setItems(r.observations);
    setSummary(r.summary);
    onSummary?.(r.summary);
  }
  useEffect(() => { reload().catch((e) => setError(String(e))); }, [stationId]);
  useEffect(() => {
    if (draft) { setForm({ ...EMPTY, ...draft }); onDraftConsumed(); }
  }, [draft]);

  const visible = useMemo(
    () => items.filter((o) => filter === "all" || !["closed", "withdrawn"].includes(o.status)),
    [items, filter],
  );

  const subjectOptions: { value: string; label: string }[] =
    form?.subject_kind === "tag" ? tags.map((t) => ({ value: String(t.id), label: t.tag_ref }))
    : form?.subject_kind === "element" ? elements.map((e) => ({ value: String(e.id), label: `${e.element_ref} — ${e.element_type}` }))
    : form?.subject_kind === "tin" ? tins.map((t) => ({ value: String(t.id), label: `TIN ${t.tin_no}` }))
    : [];

  async function submitRaise() {
    if (!form) return;
    setBusy(true); setError(null);
    try {
      const payload: ObservationDraft = {
        description: form.description, severity: form.severity,
        category: form.category || undefined, clause: form.clause || undefined,
        subject_kind: form.subject_kind,
        subject_id: form.subject_kind === "station" ? null : form.subject_id ?? null,
        subject_ref: form.subject_id ? null : form.subject_ref ?? null,
      };
      const o = await api.raiseObservation(stationId, payload);
      setForm(null);
      setExpanded(o.id);
      await reload();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  async function submitAction() {
    if (!pending) return;
    setBusy(true); setError(null);
    try {
      await api.observationAction(stationId, pending.id, pending.action as never, text);
      setPending(null); setText("");
      await reload();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  const textRequired = pending && ["resolve", "reopen", "withdraw", "comment"].includes(pending.action);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Review Observations</h3>
        <div className="inline-form">
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
            <option value="active">Active</option>
            <option value="all">All (incl. closed / withdrawn)</option>
          </select>
          {isReviewer && !frozen && !form && <button onClick={() => setForm({ ...EMPTY })}>Raise observation</button>}
        </div>
      </div>

      {summary && (
        <div className="workflow-meta">
          <span>Open / reopened: <strong>{summary.unresolved}</strong></span>
          <span>Awaiting verification: <strong>{summary.unverified}</strong></span>
          <span>Closed: <strong>{summary.by_status.closed ?? 0}</strong></span>
          <span className="muted small">Info-severity items never block the workflow.</span>
        </div>
      )}
      {summary && summary.unresolved > 0 && (
        <div className="status-banner fail">
          {summary.unresolved} observation(s) must be resolved before self-check / submit.
        </div>
      )}
      {summary && summary.unresolved === 0 && summary.unverified > 0 && (
        <div className="status-banner warn">
          {summary.unverified} resolved observation(s) must be verified and closed by a reviewer before check / approval.
        </div>
      )}

      {form && (
        <div className="comment-modal">
          <textarea rows={3} placeholder="Describe the observation…" value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <div className="form-grid">
            <label>Severity
              <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                {OBS_SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label>Category
              <select value={form.category ?? ""} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">—</option>
                {OBS_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label>Clause
              <input placeholder="e.g. H2.6" value={form.clause ?? ""} onChange={(e) => setForm({ ...form, clause: e.target.value })} />
            </label>
            <label>About
              <select value={form.subject_kind} onChange={(e) => setForm({ ...form, subject_kind: e.target.value, subject_id: null, subject_ref: null })}>
                <option value="station">Whole layout</option>
                <option value="tag">A tag</option>
                <option value="element">An element</option>
                <option value="tin">A TIN</option>
              </select>
            </label>
            {form.subject_kind !== "station" && (
              <label>Which
                <select value={form.subject_id ? String(form.subject_id) : ""}
                  onChange={(e) => setForm({ ...form, subject_id: e.target.value ? Number(e.target.value) : null, subject_ref: null })}>
                  <option value="">{form.subject_ref ? `${form.subject_ref} (from verification)` : "— choose —"}</option>
                  {subjectOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>
            )}
          </div>
          <div className="comment-modal-actions">
            <button onClick={submitRaise}
              disabled={busy || !form.description?.trim() || (form.subject_kind !== "station" && !form.subject_id && !form.subject_ref)}>
              Raise
            </button>
            <button className="secondary" onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <table className="register-table">
        <thead>
          <tr><th>No.</th><th>Severity</th><th>Status</th><th>About</th><th>Observation</th><th>Raised</th><th></th></tr>
        </thead>
        <tbody>
          {visible.map((o) => (
            <Fragment key={o.id}>
              <tr className={["open", "reopened"].includes(o.status) && o.severity !== "info" ? "row-fail" : ""}>
                <td><strong>{o.label}</strong></td>
                <td><span className={`badge sev-${o.severity}`}>{o.severity}</span></td>
                <td><span className={`badge ${STATUS_BADGE[o.status] ?? "na"}`}>{OBS_STATUS_LABELS[o.status] ?? o.status}</span></td>
                <td className="small">
                  {o.subject_kind === "station" ? "Layout" : <>{o.subject_kind} <strong>{o.subject_ref}</strong></>}
                  {!o.subject_exists && <div className="muted">(since removed)</div>}
                  {o.clause && <div className="muted">Clause {o.clause}</div>}
                </td>
                <td>{o.description}{o.category && <div className="muted small">{o.category}</div>}</td>
                <td className="small">{o.raised_by}<div className="muted">{when(o.raised_at)} · v{o.layout_version}</div></td>
                <td className="row-actions">
                  <button className="link-btn" onClick={() => setExpanded(expanded === o.id ? null : o.id)}>
                    {expanded === o.id ? "Hide" : `Thread (${o.comments.length})`}
                  </button>
                </td>
              </tr>
              {expanded === o.id && (
                <tr className="row-editing">
                  <td colSpan={7}>
                    <ol className="obs-thread">
                      {o.comments.map((c) => (
                        <li key={c.id}>
                          <span className="muted small">{when(c.created_at)}</span>{" "}
                          <strong>{c.author}</strong> <span className="muted small">({c.author_role})</span>{" "}
                          {c.action !== "comment" && <span className="badge na">{c.action}{c.to_status && c.to_status !== c.from_status ? ` → ${c.to_status}` : ""}</span>}
                          {c.text && <div>{c.text}</div>}
                        </li>
                      ))}
                    </ol>
                    {!frozen && (
                      <div className="workflow-actions">
                        {o.allowed_actions.map((a) => (
                          <button key={a} className={a === "comment" || a === "withdraw" ? "secondary" : ""}
                            onClick={() => { setPending({ id: o.id, action: a }); setText(""); }}>
                            {ACTION_LABELS[a] ?? a}
                          </button>
                        ))}
                      </div>
                    )}
                    {pending?.id === o.id && (
                      <div className="comment-modal">
                        <textarea rows={2} placeholder={ACTION_PROMPTS[pending.action]} value={text} onChange={(e) => setText(e.target.value)} />
                        <div className="comment-modal-actions">
                          <button onClick={submitAction} disabled={busy || (!!textRequired && !text.trim())}>
                            {ACTION_LABELS[pending.action]}
                          </button>
                          <button className="secondary" onClick={() => setPending(null)}>Cancel</button>
                        </div>
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {visible.length === 0 && (
            <tr><td colSpan={7} className="muted">
              {items.length === 0 ? "No observations raised on this station." : "No active observations."}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
