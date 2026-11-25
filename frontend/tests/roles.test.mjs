import assert from "node:assert/strict";
import test from "node:test";

import { ROLES, canCreateSite, canManageMembers } from "../dist-tests/roles.js";

test("only owners and analysts may create a site", () => {
  assert.equal(canCreateSite("owner"), true);
  assert.equal(canCreateSite("analyst"), true);
  assert.equal(canCreateSite("viewer"), false);
});

test("unknown or empty roles never gain a capability", () => {
  for (const role of ["", "Owner", "admin", "unknown", "viewer "]) {
    assert.equal(canCreateSite(role), false, `canCreateSite(${JSON.stringify(role)})`);
    assert.equal(canManageMembers(role), false, `canManageMembers(${JSON.stringify(role)})`);
  }
});

test("membership management stays owner-only", () => {
  assert.equal(canManageMembers("owner"), true);
  assert.equal(canManageMembers("analyst"), false);
  assert.equal(canManageMembers("viewer"), false);
});

test("the declared role list matches the service contract", () => {
  assert.deepEqual([...ROLES], ["owner", "analyst", "viewer"]);
});
