import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Workspace } from "../types";
import { api } from "../api";

const KEY = "kavach_workspace";

interface Ctx {
  workspaces: Workspace[];
  /** Selected workspace id; null = all workspaces (only offered when the user sees more than one). */
  currentId: number | null;
  current: Workspace | null;
  setCurrentId: (id: number | null) => void;
  byId: (id: number | null | undefined) => Workspace | undefined;
  reload: () => Promise<void>;
}

const WorkspaceContext = createContext<Ctx | null>(null);

function stored(): number | null {
  try { const v = localStorage.getItem(KEY); return v ? Number(v) : null; } catch { return null; }
}

/** Railway-zone workspaces the user can see, and the one they're working in. */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentId, setCurrent] = useState<number | null>(stored());

  const reload = useCallback(async () => {
    const ws = await api.listWorkspaces();
    setWorkspaces(ws);
    setCurrent((cur) => {
      if (cur != null && ws.some((w) => w.id === cur)) return cur;
      return ws.length === 1 ? ws[0].id : null;
    });
  }, []);
  useEffect(() => { reload().catch(console.error); }, [reload]);

  const setCurrentId = (id: number | null) => {
    setCurrent(id);
    try { if (id == null) localStorage.removeItem(KEY); else localStorage.setItem(KEY, String(id)); } catch { /* ignore */ }
  };
  const byId = (id: number | null | undefined) => workspaces.find((w) => w.id === id);

  return (
    <WorkspaceContext.Provider value={{ workspaces, currentId, current: byId(currentId) ?? null, setCurrentId, byId, reload }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): Ctx {
  const c = useContext(WorkspaceContext);
  if (!c) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return c;
}

export function WorkspaceSwitcher() {
  const { workspaces, currentId, setCurrentId } = useWorkspace();
  if (workspaces.length === 0) return null;
  if (workspaces.length === 1) {
    return <span className="badge na" title={workspaces[0].name}>{workspaces[0].code}</span>;
  }
  return (
    <select value={currentId ?? ""} onChange={(e) => setCurrentId(e.target.value ? Number(e.target.value) : null)}
      title="Railway zone workspace">
      <option value="">All workspaces</option>
      {workspaces.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
    </select>
  );
}
