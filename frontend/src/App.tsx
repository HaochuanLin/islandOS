import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";
import Icon from "./Icon";
import IslandAtlas from "./IslandAtlas";
import MemberManagement from "./MemberManagement";
import { canCreateSite } from "./roles";
import "./workflow.css";
import type { Notification, Session, Site, Telemetry } from "./api";

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
  // The selected site is read through a ref so `refresh` keeps a stable identity.
  // Deriving it from state made every selection recreate `refresh`, which re-fired
  // the session effect and sent a second `telemetry/latest` probe for a brand-new
  // site (two 404s on the console for an empty site).
  const siteIdRef = useRef("");
  useEffect(() => { siteIdRef.current = siteId; }, [siteId]);

  useEffect(() => {
    api.health().then((result) => setHealth(result.status === "ok" ? "online" : "unavailable"))
      .catch(() => setHealth("offline"));
  }, []);

  const refresh = useCallback(async (token: string, preferredSite?: string) => {
    const [siteResult, notificationResult] = await Promise.all([api.sites(token), api.notifications(token)]);
    setSites(siteResult.sites);
    setNotifications(notificationResult.notifications);
    const current = siteIdRef.current;
    const nextId = preferredSite && siteResult.sites.some((site) => site.id === preferredSite)
      ? preferredSite : siteResult.sites.some((site) => site.id === current) ? current : siteResult.sites[0]?.id ?? "";
    siteIdRef.current = nextId;
    setSiteId(nextId);
    if (nextId) {
      try {
        setTelemetry(await api.latestTelemetry(token, nextId));
        setError("");
      } catch (err) {
        setTelemetry(null);
        setError(err instanceof Error ? err.message : "Telemetry refresh failed");
      }
    } else setTelemetry(null);
    setLastUpdated(new Date().toLocaleTimeString());
  }, []);

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
    setSiteId(id); setTelemetry(null); setError("");
    if (!session || !id) return;
    try { setTelemetry(await api.latestTelemetry(session.access_token, id)); }
    catch (err) { setTelemetry(null); setError(err instanceof Error ? err.message : "Telemetry refresh failed"); }
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
    <aside className="login-story">
      <IslandAtlas className="story-atlas" />
      <div className="login-brand">
        <div className="brand-mark" aria-hidden="true">I</div>
        <div className="brand-wordmark"><strong>IslandOS</strong><span>Energy & resource intelligence</span></div>
      </div>
      <div className="story-copy">
        <h1>Power and water, planned together.</h1>
        <p className="story-lede">A local reference console for reviewing sites, validated telemetry and operating notices before the next cycle.</p>
        <ul className="story-principles">
          <li><span className="story-icon"><Icon name="lock" size={17} /></span><div><strong>Read-only by design</strong><span>No equipment commands leave this console.</span></div></li>
          <li><span className="story-icon"><Icon name="pulse" size={17} /></span><div><strong>Human review stays central</strong><span>Telemetry and recommendations are evidence, not instructions.</span></div></li>
          <li><span className="story-icon"><Icon name="database" size={17} /></span><div><strong>A local reference surface</strong><span>Loopback only, with no public account registration.</span></div></li>
        </ul>
      </div>
      <p className="story-foot"><span className="story-seal" aria-hidden="true">岛</span><span>Local reference · Loopback only · API v1</span></p>
    </aside>
    <section className="login-panel">
      <div className="login-form-wrap">
        <div className="login-heading">
          <h2>Sign in</h2>
          <p>Use the account created for this workspace.</p>
        </div>
        <form onSubmit={handleLogin}>
          <label className="field"><span>Email address</span><input type="email" autoComplete="username" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label className="field"><span>Password</span><input type="password" autoComplete="current-password" placeholder="Your workspace password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          <button className="primary full" disabled={busy}>{busy ? "Signing in…" : <>Sign in <Icon name="arrow" size={16} /></>}</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
        <div className={`access-note ${health === "online" ? "online" : ""}`} aria-live="polite">
          <span className={health === "online" ? "dot good" : "dot"} />
          <div>
            <strong>API {health}</strong>
            <span>{health === "online" ? "Registration is closed. Ask a workspace owner for an invitation." : "The local API is not reachable. Start it before signing in."}</span>
          </div>
        </div>
        <p className="login-foot">IslandOS is a decision-support interface. It does not issue equipment commands.</p>
      </div>
    </section>
  </main>;

  const canAddSite = canCreateSite(session.role);

  return <div className="app-shell">
    <aside className="sidebar">
      <IslandAtlas className="sidebar-atlas" />
      <div className="side-brand"><div className="brand-mark" aria-hidden="true">I</div><div className="brand-wordmark"><strong>IslandOS</strong><span>Operations console</span></div></div>
      <div className="side-workspace">
        <div className="side-label">Workspace</div>
        <div className="tenant-card"><span className="tenant-icon"><Icon name="site" size={18} /></span><div><strong>Workspace</strong><small>{session.tenant_id.slice(0, 8)}…</small></div></div>
      </div>
      <div className="site-block">
        <div className="side-label site-label"><span>Sites</span><span className="side-count">{sites.length}</span></div>
        <div className="site-list">
          {sites.map((site) => <button key={site.id} className={site.id === siteId ? "site-choice active" : "site-choice"} onClick={() => selectSite(site.id)}><span className="site-dot" />{site.name}</button>)}
          {!sites.length && <p className="empty-small">{canAddSite ? "No sites yet. Add your first site below." : "No sites yet. An owner or analyst adds them."}</p>}
        </div>
        {canAddSite ? <form className="add-site" onSubmit={handleCreateSite}>
          <label>New site<input value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="e.g. North microgrid" required maxLength={120} /></label>
          <label>Timezone<input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="UTC or Asia/Tokyo" required maxLength={80} /></label>
          <button className="outline full" disabled={busy || !siteName.trim()}><Icon name="plus" size={14} /> Add site</button>
        </form> : <p className="empty-small viewer-note">Viewer role: site creation is restricted to owners and analysts.</p>}
      </div>
      <div className="sidebar-bottom"><div className="user-line"><div className="avatar">{session.role.slice(0,1).toUpperCase()}</div><div><strong>{session.role}</strong><small>{session.role} access</small></div></div><button className="logout" onClick={handleLogout} disabled={busy}>Sign out <Icon name="arrow" size={14} /></button></div>
    </aside>

    <main className="main-content">
      <header className="topbar">
        <div>
          <h1>{selectedSite?.name ?? "Island operations"}</h1>
          <p className="topbar-meta">{selectedSite ? `Local reference surface · ${sites.length} registered site${sites.length === 1 ? "" : "s"}` : "Local reference surface · workspace overview"}</p>
        </div>
        <div className="top-actions">
          <span className="status-pill"><span className={health === "online" ? "dot good" : "dot"} />API {health}</span>
          <button className="outline refresh-button" onClick={() => refresh(session.access_token)} disabled={busy}><Icon name="refresh" size={15} /> Refresh</button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")}>Dismiss</button></div>}
      <section className="notice">
        <span className="notice-icon"><Icon name="lock" size={17} /></span>
        <div><strong>Read-only decision support</strong><p>Telemetry and recommendations are for operator review. Physical device writes are disabled in this reference service.</p></div>
      </section>
      <nav className="planning-paths" aria-label="Planning paths">
        <div className="planning-head"><h2>Planning runs</h2><p>Planning runs open in the Streamlit demo.</p></div>
        <div className="planning-links">
          <a href="https://islandos.streamlit.app/Customer_Decision_Dashboard" target="_blank" rel="noopener noreferrer">Decision dashboard ↗</a>
          <a href="https://islandos.streamlit.app/Forecast_Led_Joint_Resource_Optimizer" target="_blank" rel="noopener noreferrer">Joint resource optimizer ↗</a>
          <a href="https://islandos.streamlit.app/Device_Flexibility_Planner" target="_blank" rel="noopener noreferrer">Device flexibility planner ↗</a>
        </div>
      </nav>
      <section className="snapshot-panel" aria-label="Workspace summary">
        <article className="snapshot-item"><span className="metric-label">Registered sites</span><strong>{sites.length}</strong><small>In this workspace</small></article>
        <article className="snapshot-item"><span className="metric-label">Unread notifications</span><strong>{unread}</strong><small>Requires review</small></article>
        <article className="snapshot-item"><span className="metric-label">Latest telemetry</span><strong className={telemetry ? "snapshot-value is-date" : "snapshot-value"}>{telemetry ? new Date(telemetry.timestamp_utc).toLocaleString() : "—"}</strong><small>{telemetry ? `Source: ${telemetry.source}` : "No validated record"}</small></article>
      </section>
      {sites.length === 0 && <section className="onboarding" aria-label="First-run checklist">
        <div className="onboarding-copy">
          <h2>Start with one site.</h2>
          <p>A site carries its own timezone, read-only telemetry and operating notices. Add the first one in the sidebar, then review what arrives.</p>
        </div>
        <ol className="onboarding-steps">
          <li><span className="step-no">01</span><div><strong>Name the site</strong><span>Set a timezone that matches the field.</span></div></li>
          <li><span className="step-no">02</span><div><strong>Connect a read-only source</strong><span>No device writes are enabled.</span></div></li>
          <li><span className="step-no">03</span><div><strong>Review the first record</strong><span>Telemetry and notices land here.</span></div></li>
        </ol>
      </section>}
      <MemberManagement token={session.access_token} role={session.role} />
      <div className="content-grid">
        <section className="panel telemetry-panel"><div className="panel-head"><h2>Latest telemetry</h2><span className="tag">{telemetry ? "Validated record" : "No data"}</span></div>
          {!selectedSite ? <div className="empty-state"><span className="empty-icon"><Icon name="site" size={21} /></span><strong>Create a site to get started</strong><p>Each site has its own timezone and isolated telemetry records.</p></div> : !telemetry ? <div className="empty-state"><span className="empty-icon"><Icon name="pulse" size={21} /></span><strong>No telemetry received</strong><p>Connect an approved read-only data source or submit a validated telemetry record to the local API.</p></div> : <><div className="data-grid">{telemetryEntries.map(([key, value]) => <div className="data-cell" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{String(value)}</strong></div>)}</div><div className="telemetry-foot">Received {new Date(telemetry.received_at_utc).toLocaleString()} · Physical write: no</div></>}
        </section>
        <section className="panel notifications-panel"><div className="panel-head"><h2>Notifications</h2><span className="tag">{notifications.length} recent</span></div>
          {!notifications.length ? <div className="empty-state compact"><span className="empty-icon"><Icon name="bell" size={21} /></span><strong>All quiet</strong><p>Data-quality and system notices will appear here.</p></div> : <div className="notification-list">{notifications.map((item) => <article className={item.read_at ? "notification read" : "notification"} key={item.id}><span className={`severity ${item.severity}`} /><div className="notification-body"><div className="notification-title"><strong>{item.title}</strong><small>{new Date(item.created_at).toLocaleString()}</small></div><p>{item.message}</p>{!item.read_at && <button className="text-button" onClick={() => markRead(item)}>Mark as read</button>}</div></article>)}</div>}
        </section>
      </div>
      <footer className="page-foot"><span>Last refreshed: {lastUpdated || "—"}</span><span>IslandOS · Customer Console · API v1 · <a className="foot-link" href="./application-views.html" target="_blank" rel="noopener noreferrer">Contract viewer (read only) ↗</a></span></footer>
    </main>
  </div>;
}

export default App;
