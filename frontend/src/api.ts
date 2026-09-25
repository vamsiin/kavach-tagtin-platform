import type {
  Station, Element, Tag, TIN, VerificationReport, ToCCrossValidation,
  User, TokenResponse, WorkflowStatus,
  RailwaySubmission, RailwaySubmitPayload,
  DocType, InputDocument, DxfImportResult, DxfCalibration, DxfCommitPayload, Traceability,
} from "./types";

// Defaults to the SAME host the browser used to load this page, on port 8000 --
// not a hardcoded "localhost". Hardcoding localhost broke access from any other
// machine on the network: when a second machine loads the frontend at
// http://172.16.2.71:5173, "localhost" in ITS browser refers to that second
// machine itself (which has no backend running), not the server. The failed
// connection to a nonexistent local backend then gets reported as a CORS error
// by the browser, which is misleading -- the real problem was never CORS, it was
// this default. Using window.location.hostname makes the frontend automatically
// target the correct backend regardless of whether it's reached via localhost,
// 127.0.0.1, or a LAN IP, with no per-machine configuration needed.
// VITE_API_URL still overrides this explicitly when set (e.g. for a deployment
// where the backend is NOT on the same host as the frontend).
const BASE_URL = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;
const TOKEN_KEY = "kavach_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (!(options?.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { headers, ...options });
  if (res.status === 401) {
    setToken(null);
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // ---- auth ----
  login: (username: string, password: string) =>
    request<TokenResponse>("/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }),
    }),
  me: () => request<User>("/auth/me"),
  listUsers: () => request<User[]>("/auth/users"),
  listUsersByRole: (role: string) => request<User[]>(`/auth/users/by-role/${role}`),
  createUser: (payload: { username: string; full_name: string; email?: string; role: string; password: string }) =>
    request<User>("/auth/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (username: string, payload: { full_name: string; email?: string; role: string; is_active: boolean }) =>
    request<User>(`/auth/users/${username}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteUser: (username: string) =>
    request<void>(`/auth/users/${username}`, { method: "DELETE" }),
  registerFirstAdmin: (payload: { username: string; full_name: string; password: string }) =>
    request<User>("/auth/register", {
      method: "POST", body: JSON.stringify({ ...payload, role: "admin" }),
    }),
  forgotPassword: (username: string) =>
    request<{ message: string }>("/auth/forgot-password", {
      method: "POST", body: JSON.stringify({ username }),
    }),
  resetPassword: (token: string, new_password: string) =>
    request<{ message: string }>("/auth/reset-password", {
      method: "POST", body: JSON.stringify({ token, new_password }),
    }),

  // ---- stations / registers ----
  listStations: () => request<Station[]>("/stations"),
  createStation: (payload: Partial<Station>) =>
    request<Station>("/stations", { method: "POST", body: JSON.stringify(payload) }),
  deleteStation: (stationId: number) =>
    request<void>(`/stations/${stationId}`, { method: "DELETE" }),

  listElements: (stationId: number) => request<Element[]>(`/stations/${stationId}/elements`),
  addElement: (stationId: number, payload: Partial<Element>) =>
    request<Element>(`/stations/${stationId}/elements`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  updateElement: (stationId: number, elementId: number, payload: Partial<Element>) =>
    request<Element>(`/stations/${stationId}/elements/${elementId}`, {
      method: "PUT", body: JSON.stringify(payload),
    }),
  deleteElement: (stationId: number, elementId: number) =>
    request<void>(`/stations/${stationId}/elements/${elementId}`, { method: "DELETE" }),

  listTags: (stationId: number) => request<Tag[]>(`/stations/${stationId}/tags`),
  addTag: (stationId: number, payload: Partial<Tag>) =>
    request<Tag>(`/stations/${stationId}/tags`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  updateTag: (stationId: number, tagId: number, payload: Partial<Tag>) =>
    request<Tag>(`/stations/${stationId}/tags/${tagId}`, {
      method: "PUT", body: JSON.stringify(payload),
    }),
  deleteTag: (stationId: number, tagId: number) =>
    request<void>(`/stations/${stationId}/tags/${tagId}`, { method: "DELETE" }),

  listTins: (stationId: number) => request<TIN[]>(`/stations/${stationId}/tins`),
  addTin: (stationId: number, payload: Partial<TIN>) =>
    request<TIN>(`/stations/${stationId}/tins`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  updateTin: (stationId: number, tinId: number, payload: Partial<TIN>) =>
    request<TIN>(`/stations/${stationId}/tins/${tinId}`, {
      method: "PUT", body: JSON.stringify(payload),
    }),
  deleteTin: (stationId: number, tinId: number) =>
    request<void>(`/stations/${stationId}/tins/${tinId}`, { method: "DELETE" }),

  verifyStation: (stationId: number) =>
    request<VerificationReport>(`/stations/${stationId}/verify`),

  verifyAgainstToc: (stationId: number, file: File) => {
    const form = new FormData();
    form.append("toc_file", file);
    return request<ToCCrossValidation>(`/stations/${stationId}/verify-toc`, {
      method: "POST", body: form,
    });
  },

  // ---- design inputs (FR-001) ----
  listDocTypes: () => request<DocType[]>("/document-types"),
  listDocuments: (stationId: number) =>
    request<InputDocument[]>(`/stations/${stationId}/documents`),
  uploadDocument: (stationId: number, file: File, docType: string, versionLabel = "", notes = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    if (versionLabel) form.append("version_label", versionLabel);
    if (notes) form.append("notes", notes);
    return request<InputDocument>(`/stations/${stationId}/documents`, { method: "POST", body: form });
  },
  deleteDocument: (stationId: number, docId: number) =>
    request<void>(`/stations/${stationId}/documents/${docId}`, { method: "DELETE" }),
  // Download needs the bearer token, so it can't be a plain <a href> -- fetch the
  // blob and hand it to the browser as an object URL.
  downloadDocument: async (stationId: number, doc: InputDocument) => {
    const token = getToken();
    const res = await fetch(`${BASE_URL}/stations/${stationId}/documents/${doc.id}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.original_filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  // ---- DXF import (FR-002) ----
  importDxf: (stationId: number, file: File, docType: string, versionLabel: string, cal: DxfCalibration) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    if (versionLabel) form.append("version_label", versionLabel);
    for (const [k, v] of Object.entries(cal)) if (v !== undefined && !Number.isNaN(v)) form.append(k, String(v));
    return request<DxfImportResult>(`/stations/${stationId}/import-dxf`, { method: "POST", body: form });
  },
  dxfCandidates: (stationId: number, docId: number, cal: DxfCalibration) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(cal)) if (v !== undefined && !Number.isNaN(v)) qs.set(k, String(v));
    return request<DxfImportResult>(`/stations/${stationId}/documents/${docId}/dxf-candidates?${qs}`);
  },
  dxfCommit: (stationId: number, docId: number, payload: DxfCommitPayload) =>
    request<{ elements_created: number; tags_created: number }>(
      `/stations/${stationId}/documents/${docId}/dxf-commit`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  // ---- traceability (FR-011) ----
  getTraceability: (stationId: number) =>
    request<Traceability>(`/stations/${stationId}/traceability`),

  // ---- workflow ----
  getStation: (stationId: number) => request<Station>(`/stations/${stationId}`),
  selfCheckStation: (stationId: number, comment = "") =>
    request<Station>(`/stations/${stationId}/self-check`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
  reviseStation: (stationId: number, comment = "") =>
    request<Station>(`/stations/${stationId}/revise`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
  railwaySubmit: (stationId: number, payload: RailwaySubmitPayload) =>
    request<RailwaySubmission>(`/stations/${stationId}/railway-submit`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  listRailwaySubmissions: (stationId: number) =>
    request<RailwaySubmission[]>(`/stations/${stationId}/railway-submissions`),
  getWorkflowStatus: (stationId: number) =>
    request<WorkflowStatus>(`/stations/${stationId}/workflow`),
  submitStation: (stationId: number, assignedCheckerUsername: string, comment = "") =>
    request<Station>(`/stations/${stationId}/submit`, {
      method: "POST", body: JSON.stringify({ assigned_checker_username: assignedCheckerUsername, comment }),
    }),
  checkStation: (stationId: number, comment = "") =>
    request<Station>(`/stations/${stationId}/check`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
  approveStation: (stationId: number, comment = "") =>
    request<Station>(`/stations/${stationId}/approve`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
  requestChanges: (stationId: number, comment: string) =>
    request<Station>(`/stations/${stationId}/request-changes`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
  reopenStation: (stationId: number, comment = "") =>
    request<Station>(`/stations/${stationId}/reopen`, {
      method: "POST", body: JSON.stringify({ comment }),
    }),
};
