export type Site = { id: string; name: string; timezone: string; created_at?: string };
export type Notification = {
  id: string; site_id?: string | null; category: string; severity: "info" | "warning" | "critical";
  title: string; message: string; created_at: string; read_at?: string | null;
};
export type Telemetry = {
  timestamp_utc: string; received_at_utc: string; source: string;
  values: Record<string, number | string | boolean>; physical_write_performed: false;
};
export type Session = { access_token: string; token_type: "Bearer"; expires_at: string; tenant_id: string; role: string };

async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload as T;
}

export const api = {
  health: () => request<{ status: string; api_version: string; mode: string; device_write_enabled: boolean }>("/api/v1/health"),
  login: (email: string, password: string) =>
    request<Session>("/api/v1/auth/login", undefined, { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: (token: string) => request<{ revoked: boolean }>("/api/v1/auth/logout", token),
  sites: (token: string) => request<{ sites: Site[] }>("/api/v1/sites", token),
  createSite: (token: string, name: string, timezone: string) =>
    request<Site>("/api/v1/sites", token, { method: "POST", body: JSON.stringify({ name, timezone }) }),
  latestTelemetry: (token: string, siteId: string) =>
    request<Telemetry>(`/api/v1/sites/${encodeURIComponent(siteId)}/telemetry/latest`, token),
  notifications: (token: string) =>
    request<{ notifications: Notification[] }>("/api/v1/notifications?limit=30", token),
  markRead: (token: string, id: string) =>
    request<{ id: string; read_at: string }>(`/api/v1/notifications/${encodeURIComponent(id)}/read`, token, { method: "POST", body: "{}" })
};
