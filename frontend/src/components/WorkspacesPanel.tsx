import { useEffect, useState } from "react";
import type { User, Workspace } from "../types";
import { ROLE_LABELS } from "../types";
import { api } from "../api";
import { useCan } from "../auth/AuthContext";
import { useWorkspace } from "../workspace/WorkspaceContext";

type Draft = { code: string; name: string; dn_direction: "Nominal" | "Reverse"; open_to_all: boolean; remarks: string };
const EMPTY: Draft = { code: "", name: "", dn_direction: "Nominal", open_to_all: false, remarks: "" };

/** Railway-zone workspaces: each zone's stations, allotment charts and checklist
 *  overrides, its SIP direction convention, and who can see it. Configuration
 *  Manager / admin create and manage them; everyone sees the ones they belong to. */
export function WorkspacesPanel() {
  const can = useCan();
  const manage = can("workspace.manage");
  const { workspaces, reload } = useWorkspace();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState<Draft | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [membersOf, setMembersOf] = useState<Workspace | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (manage) api.workspaceUsers().then(setUsers).catch((e) => setError(String(e))); }, [manage]);

  async function save() {
    if (!form) return;
    setError(null);
    try {
      const p = { ...form, remarks: form.remarks || null };
      if (editId == null) await api.createWorkspace(p); else await api.updateWorkspace(editId, p);
      setForm(null); setEditId(null);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  async function saveMembers() {
    if (!membersOf) return;
    setError(null);
    try { await api.setWorkspaceMembers(membersOf.id, [...picked]); setMembersOf(null); await reload(); }
    catch (e) { setError(String(e)); }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <h3>Workspaces (railway zones)</h3>
          {manage && !form && <button onClick={() => { setForm({ ...EMPTY }); setEditId(null); }}>New workspace</button>}
        </div>
        <p className="muted small">
          Each zone keeps its own stations, allotment charts and checklist overrides. Users see only the workspaces
          they're members of (Configuration Managers and admins see all). The direction convention says which KAVACH
          direction the zone's SIP "Down" movements are: Nominal in most zones; in ECR, SIP Up is Nominal, so SIP
          Down is Reverse. Odd/even tag numbering follows the KAVACH direction everywhere.
        </p>
        {error && <div className="error">{error}</div>}

        {form && (
          <div className="comment-modal">
            <div className="form-grid">
              <label>Code<input value={form.code} placeholder="ECR" onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} /></label>
              <label>Name<input value={form.name} placeholder="East Central Railway" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label>SIP "Down" movements are
                <select value={form.dn_direction} onChange={(e) => setForm({ ...form, dn_direction: e.target.value as Draft["dn_direction"] })}>
                  <option value="Nominal">Nominal (SIP Down = DN, e.g. SCR)</option>
                  <option value="Reverse">Reverse (SIP Up = Nominal, e.g. ECR)</option>
                </select>
              </label>
              <label>Remarks<input value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} /></label>
              <label className="checkbox-label"><input type="checkbox" checked={form.open_to_all}
                onChange={(e) => setForm({ ...form, open_to_all: e.target.checked })} /> Open to all users</label>
            </div>
            <div className="comment-modal-actions">
              <button onClick={save} disabled={!form.code.trim() || !form.name.trim()}>{editId == null ? "Create" : "Save"}</button>
              <button className="secondary" onClick={() => { setForm(null); setEditId(null); }}>Cancel</button>
            </div>
          </div>
        )}

        <table className="register-table">
          <thead><tr><th>Code</th><th>Name</th><th>SIP Down =</th><th>Stations</th><th>Checklist overrides</th><th>Members</th><th></th></tr></thead>
          <tbody>
            {workspaces.map((w) => (
              <tr key={w.id}>
                <td><strong>{w.code}</strong></td>
                <td>{w.name}{w.remarks && <div className="muted small">{w.remarks}</div>}</td>
                <td>{w.dn_direction}<div className="muted small">SIP Up = {w.dn_direction === "Nominal" ? "Reverse" : "Nominal"}</div></td>
                <td>{w.station_count}</td>
                <td>{w.override_count}</td>
                <td className="small">{w.open_to_all ? <span className="badge na">everyone</span> : w.members.join(", ") || "—"}</td>
                <td className="row-actions">
                  {manage && <button className="link-btn" onClick={() => {
                    setEditId(w.id);
                    setForm({ code: w.code, name: w.name, dn_direction: w.dn_direction, open_to_all: w.open_to_all, remarks: w.remarks ?? "" });
                  }}>Edit</button>}
                  {manage && !w.open_to_all && <button className="link-btn" onClick={() => { setMembersOf(w); setPicked(new Set(w.members)); }}>Members</button>}
                </td>
              </tr>
            ))}
            {workspaces.length === 0 && <tr><td colSpan={7} className="muted">No workspaces yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {membersOf && (
        <div className="panel">
          <div className="panel-header"><h3>Members of {membersOf.code}</h3>
            <div className="inline-form">
              <button onClick={saveMembers}>Save members ({picked.size})</button>
              <button className="secondary" onClick={() => setMembersOf(null)}>Cancel</button>
            </div>
          </div>
          <p className="muted small">Configuration Managers and admins see every workspace whether or not they're listed.</p>
          <table className="register-table">
            <thead><tr><th></th><th>User</th><th>Name</th><th>Role</th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.username}>
                  <td><input type="checkbox" checked={picked.has(u.username)} onChange={(e) => {
                    const n = new Set(picked);
                    if (e.target.checked) n.add(u.username); else n.delete(u.username);
                    setPicked(n);
                  }} /></td>
                  <td>{u.username}</td><td>{u.full_name}</td><td className="small">{ROLE_LABELS[u.role] ?? u.role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
