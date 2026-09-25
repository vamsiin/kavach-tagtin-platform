import type {
  Station, Element, Tag, TIN, VerificationReport, ToCCrossValidation,
  User, TokenResponse, WorkflowStatus,
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

  // ---- workflow ----
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
