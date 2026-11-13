import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, Notification, Session, Site, Telemetry } from "./api";

function App() {
  const [health, setHealth] = useState("checking");
  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState("");
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [siteName, setSiteName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("");

  const selectedSite = useMemo(() => sites.find((site) => site.id === siteId) ?? null, [sites, siteId]);

  useEffect(() => {
    api.health().then((result) => setHealth(result.status === "ok" ? "online" : "unavailable"))
      .catch(() => setHealth("offline"));
  }, []);

  const refresh = useCallback(async (token: string, preferredSite?: string) => {
    const [siteResult, notificationResult] = await Promise.all([api.sites(token), api.notifications(token)]);
    setSites(siteResult.sites);
    setNotifications(notificationResult.notifications);
    const nextId = preferredSite && siteResult.sites.some((site) => site.id === preferredSite)
      ? preferredSite : siteResult.sites.some((site) => site.id === siteId) ? siteId : siteResult.sites[0]?.id ?? "";
    setSiteId(nextId);
    if (nextId) {
      try { setTelemetry(await api.latestTelemetry(token, nextId)); }
      catch (err) { if (err instanceof Error && !err.message.includes("no telemetry")) setTelemetry(null); else setTelemetry(null); }
    } else setTelemetry(null);
    setLastUpdated(new Date().toLocaleTimeString());
  }, [siteId]);

  useEffect(() => {
    if (!session) return;
    refresh(session.access_token).catch((err: unknown) => setError(err instanceof Error ? err.message : "Refresh failed"));
  }, [session, refresh]);

  async function handleLogin(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { setSession(await api.login(email, password)); setPassword(""); }
    catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
    finally { setBusy(false); }
  }

  async function handleLogout() {
    if (!session) return;
    setBusy(true);
    try { await api.logout(session.access_token); }
    catch (err) { setError(err instanceof Error ? err.message : "Logout failed"); }
    finally { setSession(null); setSites([]); setTelemetry(null); setNotifications([]); setBusy(false); }
  }

  async function handleCreateSite(event: FormEvent) {
    event.preventDefault(); if (!session) return;
    setBusy(true); setError("");
    try {
      const created = await api.createSite(session.access_token, siteName, timezone);
      setSiteName("");
      await refresh(session.access_token, created.id);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create site"); }
    finally { setBusy(false); }
  }

  async function selectSite(id: string) {
    setSiteId(id); setTelemetry(null);
    if (!session || !id) return;
    try { setTelemetry(await api.latestTelemetry(session.access_token, id)); }
    catch { setTelemetry(null); }
  }

  async function markRead(item: Notification) {
    if (!session || item.read_at) return;
    try {
      await api.markRead(session.access_token, item.id);
      setNotifications((current) => current.map((n) => n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n));
    } catch (err) { setError(err instanceof Error ? err.message : "Could not update notification"); }
  }

  const telemetryEntries = telemetry ? Object.entries(telemetry.values) : [];
  const unread = notifications.filter((item) => !item.read_at).length;

  if (!session) return <main className="login-shell">
    <div className="login-brand"><div className="brand-mark">I</div><div><strong>IslandOS</strong><span>ENERGY & RESOURCE INTELLIGENCE</span></div></div>
    <section className="login-card">
      <p className="eyebrow">CUSTOMER CONSOLE · LOCAL REFERENCE</p>
      <h1>Welcome back.</h1>
      <p className="muted">Sign in to review your sites, validated telemetry and operational notifications.</p>
      <form onSubmit={handleLogin}>
        <label>Email address<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        <button className="primary full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="service-note"><span className={health === "online" ? "dot good" : "dot"} /> API {health}. Registration is disabled by default; create the first owner through the controlled local bootstrap.</div>
    </section>
    <p className="login-foot">IslandOS is a decision-support interface. It does not issue equipment commands.</p>
  </main>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="side-brand"><div className="brand-mark">I</div><div><strong>IslandOS</strong><span>OPERATIONS CONSOLE</span></div></div>
      <div className="side-label">WORKSPACE</div>
      <div className="tenant-card"><span className="tenant-icon">◈</span><div><strong>Workspace</strong><small>{session.tenant_id.slice(0, 8)}…</small></div></div>
      <div className="side-label site-label">SITES <span>{sites.length}</span></div>
      <div className="site-list">
        {sites.map((site) => <button key={site.id} className={site.id === siteId ? "site-choice active" : "site-choice"} onClick={() => selectSite(site.id)}><span className="site-dot" />{site.name}</button>)}
        {!sites.length && <p className="empty-small">No sites yet. Add your first site below.</p>}
      </div>
      <form className="add-site" onSubmit={handleCreateSite}>
        <label>New site<input value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="e.g. North microgrid" required maxLength={120} /></label>
        <label>Timezone<input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="UTC or Asia/Tokyo" required maxLength={80} /></label>
        <button className="outline full" disabled={busy || !siteName.trim()}>+ Add site</button>
      </form>
      <div className="sidebar-bottom"><div className="user-line"><div className="avatar">{session.role.slice(0,1).toUpperCase()}</div><div><strong>{session.role}</strong><small>{session.role} access</small></div></div><button className="logout" onClick={handleLogout} disabled={busy}>Sign out ↗</button></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div><p className="eyebrow">SITE OVERVIEW</p><h1>{selectedSite?.name ?? "Your workspace"}</h1></div><div className="top-actions"><span className="api-status"><span className={health === "online" ? "dot good" : "dot"} />API {health}</span><button className="outline" onClick={() => refresh(session.access_token)} disabled={busy}>↻ Refresh</button></div></header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")}>Dismiss</button></div>}
      <section className="notice"><span className="notice-icon">i</span><div><strong>Read-only decision support</strong><p>Telemetry and recommendations are for operator review. Physical device writes are disabled in this reference service.</p></div></section>
      <section className="metric-grid">
        <article className="metric-card"><span className="metric-label">REGISTERED SITES</span><strong>{sites.length}</strong><small>In this workspace</small></article>
        <article className="metric-card"><span className="metric-label">UNREAD NOTIFICATIONS</span><strong>{unread}</strong><small>Requires review</small></article>
        <article className="metric-card"><span className="metric-label">LATEST TELEMETRY</span><strong className="metric-date">{telemetry ? new Date(telemetry.timestamp_utc).toLocaleString() : "—"}</strong><small>{telemetry ? `Source: ${telemetry.source}` : "No validated record"}</small></article>
      </section>
      <div className="content-grid">
        <section className="panel telemetry-panel"><div className="panel-head"><div><p className="eyebrow">LIVE DATA · READ ONLY</p><h2>Latest telemetry</h2></div><span className="tag">{telemetry ? "VALIDATED RECORD" : "NO DATA"}</span></div>
          {!selectedSite ? <div className="empty-state"><div className="empty-icon">⌂</div><strong>Create a site to get started</strong><p>Each site has its own timezone and isolated telemetry records.</p></div> : !telemetry ? <div className="empty-state"><div className="empty-icon">⌁</div><strong>No telemetry received</strong><p>Connect an approved read-only data source or submit a validated telemetry record to the local API.</p></div> : <><div className="data-grid">{telemetryEntries.map(([key, value]) => <div className="data-cell" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{String(value)}</strong></div>)}</div><div className="telemetry-foot">Received {new Date(telemetry.received_at_utc).toLocaleString()} · Physical write: no</div></>}
        </section>
        <section className="panel notifications-panel"><div className="panel-head"><div><p className="eyebrow">ACTIVITY</p><h2>Notifications</h2></div><span className="tag">{notifications.length} RECENT</span></div>
          {!notifications.length ? <div className="empty-state compact"><strong>All quiet</strong><p>Data-quality and system notices will appear here.</p></div> : <div className="notification-list">{notifications.map((item) => <article className={item.read_at ? "notification read" : "notification"} key={item.id}><span className={`severity ${item.severity}`} /><div className="notification-body"><div className="notification-title"><strong>{item.title}</strong><small>{new Date(item.created_at).toLocaleString()}</small></div><p>{item.message}</p>{!item.read_at && <button className="text-button" onClick={() => markRead(item)}>Mark as read</button>}</div></article>)}</div>}
        </section>
      </div>
      <footer className="page-foot"><span>Last refreshed: {lastUpdated || "—"}</span><span>IslandOS · Customer Console · API v1</span></footer>
    </main>
  </div>;
}

export default App;
