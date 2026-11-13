import { useCallback, useEffect, useState } from "react";

type Member = { id: string; email: string; role: "owner" | "analyst" | "viewer"; created_at: string };
type Invitation = { invitation_id: string; email: string; role: string; expires_at: string; invitation_token: string; email_delivery_performed: false };

async function call<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload as T;
}

export default function MemberManagement({ token, role }: { token: string; role: string }) {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"analyst" | "viewer">("analyst");
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canManage = role === "owner";

  const refresh = useCallback(async () => {
    const result = await call<{ members: Member[] }>("/api/v1/members", token);
    setMembers(result.members);
  }, [token]);

  useEffect(() => {
    refresh().catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load members"));
  }, [refresh]);

  async function invite(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setInvitation(null);
    try {
      const result = await call<Invitation>("/api/v1/members/invitations", token, {
        method: "POST", body: JSON.stringify({ email, role: inviteRole, expires_in_seconds: 604800 })
      });
      setInvitation(result); setEmail(""); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Invitation failed"); }
    finally { setBusy(false); }
  }

  async function changeRole(member: Member, nextRole: "analyst" | "viewer") {
    setBusy(true); setError("");
    try {
      await call(`/api/v1/members/${encodeURIComponent(member.id)}/role`, token, {
        method: "POST", body: JSON.stringify({ role: nextRole })
      });
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Role update failed"); }
    finally { setBusy(false); }
  }

  async function remove(member: Member) {
    if (!window.confirm(`Remove ${member.email} from this workspace?`)) return;
    setBusy(true); setError("");
    try {
      await call(`/api/v1/members/${encodeURIComponent(member.id)}`, token, { method: "DELETE" });
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "Member removal failed"); }
    finally { setBusy(false); }
  }

  return <section className="panel member-panel">
    <div className="panel-head"><div><p className="eyebrow">WORKSPACE ACCESS</p><h2>Team members & invitations</h2></div><span className="tag">{members.length} MEMBERS</span></div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="member-list">
      {members.map((member) => <div className="member-row" key={member.id}>
        <div><strong>{member.email}</strong><small>{member.role} · Joined {new Date(member.created_at).toLocaleDateString()}</small></div>
        {canManage && member.role !== "owner" ? <div className="member-actions">
          <select aria-label={`Role for ${member.email}`} value={member.role} disabled={busy} onChange={(e) => changeRole(member, e.target.value as "analyst" | "viewer")}>
            <option value="analyst">Analyst</option><option value="viewer">Viewer</option>
          </select>
          <button className="text-button danger-text" disabled={busy} onClick={() => remove(member)}>Remove</button>
        </div> : <span className="tag">{member.role.toUpperCase()}</span>}
      </div>)}
      {!members.length && <p className="muted">No workspace members were returned by the service.</p>}
    </div>
    {canManage && <form className="invite-form" onSubmit={invite}>
      <label>Invite by email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="colleague@example.com" required /></label>
      <label>Workspace role<select value={inviteRole} onChange={(e) => setInviteRole(e.target.value as "analyst" | "viewer")}><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select></label>
      <button className="primary" disabled={busy || !email.trim()}>{busy ? "Working…" : "Create invitation"}</button>
    </form>}
    {invitation && <div className="invitation-result"><strong>Invitation created — email was not sent</strong><p>Share this one-time token with the invited person through an approved private channel. It expires {new Date(invitation.expires_at).toLocaleString()}.</p><code>{invitation.invitation_token}</code><button className="outline" type="button" onClick={() => navigator.clipboard?.writeText(invitation.invitation_token)}>Copy token</button></div>}
    {!canManage && <p className="muted">Your role is read-only for workspace membership. Ask an owner to invite or manage members.</p>}
  </section>;
}
