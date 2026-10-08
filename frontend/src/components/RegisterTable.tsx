import { useState, type ReactNode } from "react";
import { Pencil, Trash2, Check, X } from "lucide-react";

export interface ColumnDef<T> {
  key: keyof T | `_${string}`;   // "_name" = computed column, needs render
  label: string;
  render?: (row: T) => ReactNode;
}

interface Props<T> {
  title: string;
  rows: T[];
  columns: ColumnDef<T>[];
  /** Renders the create form. Called with a submit handler and a submitting flag. */
  renderForm: (onSubmit: (payload: Partial<T>) => void, submitting: boolean) => ReactNode;
  /**
   * Renders the SAME form shape but pre-filled for editing an existing row, and
   * wired to a different submit handler. Kept separate from renderForm (rather
   * than trying to make one form do both) because prefilling controlled inputs
   * from a row's current values is meaningfully different wiring from a blank
   * create form, and forcing them into one component made both harder to read.
   */
  renderEditForm: (row: T, onSubmit: (payload: Partial<T>) => void, onCancel: () => void, submitting: boolean) => ReactNode;
  onAdd: (payload: Partial<T>) => Promise<void>;
  onUpdate: (id: number, payload: Partial<T>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  readOnly?: boolean;
  readOnlyReason?: string;
}

export function RegisterTable<T extends { id: number }>({
  title, rows, columns, renderForm, renderEditForm, onAdd, onUpdate, onDelete, readOnly, readOnlyReason,
}: Props<T>) {
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAddSubmit(payload: Partial<T>) {
    setSubmitting(true);
    setError(null);
    try {
      await onAdd(payload);
      setShowForm(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleEditSubmit(id: number, payload: Partial<T>) {
    setSubmitting(true);
    setError(null);
    try {
      await onUpdate(id, payload);
      setEditingId(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteConfirm(id: number) {
    setSubmitting(true);
    setError(null);
    try {
      await onDelete(id);
      setPendingDeleteId(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>{title} <span className="muted">({rows.length})</span></h3>
        {!readOnly && <button onClick={() => { setShowForm(!showForm); setEditingId(null); }}>
          {showForm ? "Cancel" : "+ Add"}
        </button>}
      </div>

      {readOnly && readOnlyReason && <div className="muted small">{readOnlyReason}</div>}

      {showForm && !readOnly && (
        <div className="inline-form-wrap">
          {renderForm(handleAddSubmit, submitting)}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <table className="register-table">
        <thead>
          <tr>
            {columns.map((c) => <th key={String(c.key)}>{c.label}</th>)}
            {!readOnly && <th className="actions-col">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) =>
            editingId === row.id ? (
              <tr key={row.id} className="row-editing">
                <td colSpan={columns.length + (readOnly ? 0 : 1)}>
                  {renderEditForm(
                    row,
                    (payload) => handleEditSubmit(row.id, payload),
                    () => setEditingId(null),
                    submitting,
                  )}
                </td>
              </tr>
            ) : (
              <tr key={row.id}>
                {columns.map((c) => (
                  <td key={String(c.key)}>{c.render ? c.render(row) : String(row[c.key as keyof T] ?? "")}</td>
                ))}
                {!readOnly && (
                  <td className="actions-col">
                    {pendingDeleteId === row.id ? (
                      <span className="confirm-delete">
                        <span className="small">Delete?</span>
                        <button className="icon-btn danger" title="Confirm delete"
                                onClick={() => handleDeleteConfirm(row.id)} disabled={submitting}>
                          <Check size={16} />
                        </button>
                        <button className="icon-btn" title="Cancel"
                                onClick={() => setPendingDeleteId(null)} disabled={submitting}>
                          <X size={16} />
                        </button>
                      </span>
                    ) : (
                      <span className="row-actions">
                        <button className="icon-btn" title="Edit"
                                onClick={() => { setEditingId(row.id); setShowForm(false); }}>
                          <Pencil size={16} />
                        </button>
                        <button className="icon-btn danger" title="Delete"
                                onClick={() => setPendingDeleteId(row.id)}>
                          <Trash2 size={16} />
                        </button>
                      </span>
                    )}
                  </td>
                )}
              </tr>
            )
          )}
          {rows.length === 0 && (
            <tr><td colSpan={columns.length + (readOnly ? 0 : 1)} className="muted">No rows yet</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
