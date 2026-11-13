"""Local customer workspace UI for the single-host reference service.

This page is intentionally unavailable unless an explicit loopback API URL is
configured. It is not a hosted SaaS login surface and does not send credentials
to a non-loopback endpoint.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import streamlit as st


st.set_page_config(page_title="IslandOS | Local Workspace", page_icon="🔐", layout="wide")
st.title("Customer workspace")
st.caption("Local reference UI for tenant members and notifications")

API_BASE = os.environ.get("ISLANDOS_API_BASE_URL", "").strip().rstrip("/")
parsed = urlparse(API_BASE) if API_BASE else None
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

if not API_BASE:
    st.warning(
        "Local workspace API is not configured. Set ISLANDOS_API_BASE_URL to a loopback "
        "address such as http://127.0.0.1:8765, then restart Streamlit."
    )
    st.info(
        "The public Streamlit demonstration does not run this local tenant service. "
        "The reference API is loopback-only; this page intentionally rejects remote URLs "
        "and is not a production multi-user deployment."
    )
    st.stop()

if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS or not parsed.port:
    st.error("For this single-host reference build, API URL must be http://localhost:<port> or http://127.0.0.1:<port>.")
    st.stop()


def api_request(method: str, path: str, payload: dict | None = None, *, authenticated: bool = True):
    headers = {"Accept": "application/json"}
    token = st.session_state.get("islandos_access_token")
    if authenticated:
        if not token:
            raise RuntimeError("Please sign in first.")
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
    request = Request(API_BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise RuntimeError("API response exceeded the 64 KiB UI limit.")
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        try:
            body = json.loads(exc.read(65537).decode("utf-8"))
            message = body.get("error", f"HTTP {exc.code}")
        except Exception:
            message = f"HTTP {exc.code}"
        raise RuntimeError(message) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Cannot reach the local IslandOS API. Check that it is running.") from exc


try:
    api_health = api_request("GET", "/api/v1/health", authenticated=False)
    if api_health.get("device_write_enabled") is not False:
        st.error("API did not confirm the no-device-write boundary.")
        st.stop()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if not st.session_state.get("islandos_access_token"):
    login_tab, register_tab = st.tabs(["Sign in", "Create local tenant"])
    with login_tab:
        with st.form("islandos_login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            try:
                session = api_request(
                    "POST", "/api/v1/auth/login",
                    {"email": email, "password": password}, authenticated=False,
                )
                st.session_state["islandos_access_token"] = session["access_token"]
                st.session_state["islandos_role"] = session.get("role", "unknown")
                st.session_state["islandos_tenant_id"] = session.get("tenant_id")
                st.rerun()
            except (RuntimeError, KeyError) as exc:
                st.error(str(exc))
    with register_tab:
        st.caption("Registration succeeds only when the local API owner explicitly enables bootstrap registration.")
        with st.form("islandos_register"):
            tenant_name = st.text_input("Organization / tenant name")
            new_email = st.text_input("Owner email")
            new_password = st.text_input("Password (12–256 characters)", type="password")
            register = st.form_submit_button("Create tenant")
        if register:
            try:
                api_request(
                    "POST", "/api/v1/auth/register",
                    {"tenant_name": tenant_name, "email": new_email, "password": new_password},
                    authenticated=False,
                )
                st.success("Tenant created. Sign in using the owner credentials.")
            except RuntimeError as exc:
                st.error(str(exc))
    st.stop()

st.sidebar.success(f"Signed in · role: {st.session_state.get('islandos_role', 'unknown')}")
st.sidebar.caption(f"Tenant: {st.session_state.get('islandos_tenant_id', 'not returned')}")
if st.sidebar.button("Sign out"):
    st.session_state.pop("islandos_access_token", None)
    st.session_state.pop("islandos_role", None)
    st.session_state.pop("islandos_tenant_id", None)
    st.rerun()

members_tab, notifications_tab = st.tabs(["Members & invitations", "Notification inbox"])
with members_tab:
    st.subheader("Organization members")
    try:
        members = api_request("GET", "/api/v1/members").get("members", [])
        if members:
            st.dataframe(members, use_container_width=True, hide_index=True)
        else:
            st.info("No member records returned.")
    except RuntimeError as exc:
        st.error(str(exc))

    if st.session_state.get("islandos_role") == "owner":
        st.subheader("Invite a teammate")
        with st.form("islandos_invite"):
            invite_email = st.text_input("Teammate email")
            invite_role = st.selectbox("Role", ["analyst", "viewer"])
            expiry_days = st.selectbox("Invitation expiry", [1, 3, 7, 14], index=2)
            invite = st.form_submit_button("Create invitation")
        if invite:
            try:
                created = api_request(
                    "POST", "/api/v1/members/invitations",
                    {"email": invite_email, "role": invite_role,
                     "expires_in_seconds": int(expiry_days) * 86400},
                )
                token = created.get("invitation_token")
                if token:
                    st.success("Invitation created. Copy this one-time token and send it to the teammate through an approved channel.")
                    st.code(token)
                else:
                    st.warning("Invitation created, but the API did not return a one-time token. Check the server response.")
            except RuntimeError as exc:
                st.error(str(exc))

        st.subheader("Manage member access")
        if members:
            options = {
                f"{item.get('email', item.get('user_id', 'member'))} · {item.get('role', 'unknown')}": item
                for item in members if item.get("role") != "owner"
            }
            if options:
                selected_label = st.selectbox("Member", list(options))
                selected_member = options[selected_label]
                role_col, remove_col = st.columns(2)
                with role_col:
                    next_role = st.selectbox("Change role to", ["analyst", "viewer"], key="member_role_update")
                    if st.button("Update role"):
                        try:
                            api_request("POST", f"/api/v1/members/{selected_member['user_id']}/role", {"role": next_role})
                            st.success("Role updated.")
                            st.rerun()
                        except (RuntimeError, KeyError) as exc:
                            st.error(str(exc))
                with remove_col:
                    if st.button("Remove member", type="secondary"):
                        try:
                            api_request("DELETE", f"/api/v1/members/{selected_member['user_id']}")
                            st.success("Member removed.")
                            st.rerun()
                        except (RuntimeError, KeyError) as exc:
                            st.error(str(exc))
            else:
                st.caption("No removable non-owner members are available.")

with notifications_tab:
    st.subheader("Notifications")
    unread_only = st.checkbox("Unread only")
    if st.button("Refresh inbox"):
        st.rerun()
    try:
        query = "?"+urlencode({"unread_only": str(unread_only).lower(), "limit": 100})
        notifications = api_request("GET", "/api/v1/notifications" + query).get("notifications", [])
        if not notifications:
            st.info("No notifications.")
        for item in notifications:
            with st.container(border=True):
                st.write(f"**{item.get('title', 'Notification')}**")
                st.caption(f"{item.get('severity', 'info')} · {item.get('category', 'general')} · {item.get('created_at', '')}")
                st.write(item.get("message", ""))
                if not item.get("read_at") and st.button("Mark as read", key=f"read_{item.get('id')}"):
                    api_request("POST", f"/api/v1/notifications/{item['id']}/read", {})
                    st.rerun()
    except RuntimeError as exc:
        st.error(str(exc))

st.caption(
    "Security boundary: bearer token remains in this Streamlit session only; "
    "the local API must remain loopback-bound. This reference UI does not provide "
    "MFA/SSO, production TLS, external email delivery, or production-grade session management."
)
