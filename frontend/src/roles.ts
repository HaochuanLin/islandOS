// Role capabilities used by the console UI.
//
// The API is the authority: `POST /api/v1/sites` requires owner or analyst,
// and membership endpoints require owner. These helpers only keep the browser
// from offering a control that the service will reject, so the UI and the
// service never disagree about who can do what.

export type WorkspaceRole = "owner" | "analyst" | "viewer";

export const ROLES: readonly WorkspaceRole[] = ["owner", "analyst", "viewer"];

export function canCreateSite(role: string): boolean {
  return role === "owner" || role === "analyst";
}

export function canManageMembers(role: string): boolean {
  return role === "owner";
}
