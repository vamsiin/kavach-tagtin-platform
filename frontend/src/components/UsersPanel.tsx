import { useEffect, useState } from "react";
import { Pencil, Trash2, Check, X } from "lucide-react";
import type { User } from "../types";
import { ROLES } from "../types";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";

export function UsersPanel() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingUsername, setEditingUsername] = useState<string | null>(null);
  const [pendingDeleteUsername, setPendingDeleteUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function reload() {
    try {
      setUsers(await api.listUsers());
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => { reload(); }, []);

  async function handleCreate(payload: { username: string; full_name: string; email: string; role: string; password: string }) {
    setSubmitting(true);
    setError(null);
    try {
      await api.createUser(payload);
      setShowForm(false);
      await reload();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdate(username: string, payload: { full_name: string; email: string; role: string; is_active: boolean }) {
    setSubmitting(true);
    setError(null);
    try {
      await api.updateUser(username, payload);
      setEditingUsername(null);
      await reload();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(username: string) {
    setSubmitting(true);
    setError(null);
    try {
      await api.deleteUser(username);
      setPendingDeleteUsername(null);
      await reload();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Users <span className="muted">({users.length})</span></h3>
        <button onClick={() => { setShowForm(!showForm); setEditingUsername(null); }}>
          {showForm ? "Cancel" : "+ New user"}
        </button>
      </div>

      {showForm && (
        <div className="inline-form-wrap">
          <UserCreateForm onSubmit={handleCreate} submitting={submitting} />
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <table className="register-table">
        <thead>
          <tr><th>Username</th><th>Full name</th><th>Email</th><th>Role</th><th>Active</th><th className="actions-col">Actions</th></tr>
        </thead>
        <tbody>
          {users.map((u) =>
            editingUsername === u.username ? (
              <tr key={u.username} className="row-editing">
                <td colSpan={6}>
                  <UserEditForm
                    user={u}
                    onSubmit={(payload) => handleUpdate(u.username, payload)}
                    onCancel={() => setEditingUsername(null)}
                    submitting={submitting}
                  />
                </td>
              </tr>
            ) : (
              <tr key={u.username}>
                <td>{u.username}</td>
                <td>{u.full_name}</td>
                <td>{u.email || "—"}</td>
                <td>{u.role}</td>
                <td>{u.is_active ? "Yes" : "No"}</td>
                <td className="actions-col">
                  {pendingDeleteUsername === u.username ? (
                    <span className="confirm-delete">
                      <span className="small">Delete?</span>
                      <button className="icon-btn danger" title="Confirm delete"
                              onClick={() => handleDelete(u.username)} disabled={submitting}>
                        <Check size={16} />
                      </button>
                      <button className="icon-btn" title="Cancel"
                              onClick={() => setPendingDeleteUsername(null)} disabled={submitting}>
                        <X size={16} />
                      </button>
                    </span>
                  ) : (
                    <span className="row-actions">
                      <button className="icon-btn" title="Edit"
                              onClick={() => { setEditingUsername(u.username); setShowForm(false); }}>
                        <Pencil size={16} />
                      </button>
                      <button
                        className="icon-btn danger"
                        title={u.username === currentUser?.username ? "You cannot delete your own account" : "Delete"}
                        disabled={u.username === currentUser?.username}
                        onClick={() => setPendingDeleteUsername(u.username)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            )
          )}
        </tbody>
      </table>
    </div>
  );
}

function UserCreateForm({ onSubmit, submitting }: {
  onSubmit: (p: { username: string; full_name: string; email: string; role: string; password: string }) => void;
  submitting: boolean;
}) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("designer");
  const [password, setPassword] = useState("");

  return (
    <form className="inline-form" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({ username, full_name: fullName, email, role, password });
    }}>
      <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
      <input placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
      <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <select value={role} onChange={(e) => setRole(e.target.value)}>
        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
      <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      <button type="submit" disabled={submitting}>{submitting ? "Creating…" : "Create"}</button>
    </form>
  );
}

function UserEditForm({ user, onSubmit, onCancel, submitting }: {
  user: User;
  onSubmit: (p: { full_name: string; email: string; role: string; is_active: boolean }) => void;
  onCancel: () => void;
  submitting: boolean;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [email, setEmail] = useState(user.email);
  const [role, setRole] = useState<string>(user.role);
  const [isActive, setIsActive] = useState(user.is_active);

  return (
    <form className="inline-form" onSubmit={(e) => {
      e.preventDefault();
      onSubmit({ full_name: fullName, email, role, is_active: isActive });
    }}>
      <input placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
      <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <select value={role} onChange={(e) => setRole(e.target.value)}>
        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
      </select>
      <label className="checkbox-label">
        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
        Active
      </label>
      <button type="submit" disabled={submitting}>{submitting ? "Saving…" : "Save"}</button>
      <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
    </form>
  );
}
