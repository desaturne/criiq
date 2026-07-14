// Thin client for the CRIIQ backend (see ../../../backend/README.md for the
// full endpoint list). Every backend response is {data, error} — apiFetch
// unwraps that envelope and throws on error so callers just get the payload.

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "criiq_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = { ...(options.headers as Record<string, string> | undefined) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  const body = await res.json().catch(() => ({ data: null, error: res.statusText }));
  if (!res.ok || body.error) throw new Error(body.error || `Request failed: ${res.status}`);
  return body.data;
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (!entries.length) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
}

// --- auth --------------------------------------------------------------
export const register = (name: string, email: string, password: string) =>
  apiFetch("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password }) }) as Promise<{
    token: string; user: { id: number; name: string; role: string };
  }>;

export const login = (email: string, password: string) =>
  apiFetch("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }) as Promise<{
    token: string; user: { id: number; name: string; role: string };
  }>;

export const logout = () => apiFetch("/auth/logout", { method: "POST" });
export const me = () => apiFetch("/auth/me");

// --- players -------------------------------------------------------------
export const listPlayers = (params: { search?: string; role?: string; status?: string; page?: number; limit?: number } = {}) =>
  apiFetch(`/players${qs(params)}`) as Promise<{ players: any[]; page: number; limit: number; total: number }>;

export const getPlayer = (id: string) => apiFetch(`/players/${encodeURIComponent(id)}`);
export const getPlayerVsOpponent = (id: string, opponent: string) =>
  apiFetch(`/players/${encodeURIComponent(id)}/vs/${encodeURIComponent(opponent)}`);
export const comparePlayers = (ids: string[]) => apiFetch(`/players/compare${qs({ ids: ids.join(",") })}`);

export const addPlayer = (body: {
  name: string; role: string; country?: string | null;
  batting_hand?: string | null; bowling_style?: string | null; status?: string;
}) => apiFetch("/players", { method: "POST", body: JSON.stringify(body) });

export const updatePlayer = (id: string, body: {
  name: string; role: string; country?: string | null;
  batting_hand?: string | null; bowling_style?: string | null; status?: string;
}) => apiFetch(`/players/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) });

export const deletePlayer = (id: string) => apiFetch(`/players/${encodeURIComponent(id)}`, { method: "DELETE" });

// --- matches / dashboard ---------------------------------------------------
export const listMatches = (completedLimit?: number) =>
  apiFetch(`/matches${qs({ completed_limit: completedLimit })}`) as Promise<{ upcoming: any[]; completed: any[] }>;

export const getMatch = (id: string) => apiFetch(`/matches/${encodeURIComponent(id)}`);
export const dashboardSummary = () => apiFetch("/dashboard/summary");
export const dashboardAlerts = (limit?: number) => apiFetch(`/dashboard/alerts${qs({ limit })}`) as Promise<any[]>;
export const ticker = (matches?: number) => apiFetch(`/ticker${qs({ matches })}`);

// --- selection / recommendations / winprob ---------------------------------
export const getSelection = (matchId: string) => apiFetch(`/selection/${encodeURIComponent(matchId)}`);
export const saveSelection = (matchId: string, body: { xi: string[]; extra: string[]; excluded: string[] }) =>
  apiFetch(`/selection/${encodeURIComponent(matchId)}`, { method: "PUT", body: JSON.stringify(body) });

export const recommendations = (body: { opponent: string; venue?: string; format?: string }) =>
  apiFetch("/recommendations", { method: "POST", body: JSON.stringify(body) }) as Promise<{
    match_context: any; recommendations: { rank: number; player_name: string; role: string; score: number; reason: string }[];
  }>;

export const winProb = (params: { innings?: number; balls_remaining?: number; wickets?: number; runs_required?: number } = {}) =>
  apiFetch(`/winprob${qs(params)}`) as Promise<{
    win_probability_batting: number; win_probability_bowling: number; phase: string; model: string;
  }>;
