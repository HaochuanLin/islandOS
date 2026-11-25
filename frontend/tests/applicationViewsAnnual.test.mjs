import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/ApplicationViews.tsx", import.meta.url), "utf8");

const PAGE_COPY = [
  [
    "customer_dashboard",
    "This report has no annual projection. The 05 investment screen uses its own entered annual bills, not the 06 operating projection.",
  ],
  [
    "joint_resource_optimizer",
    "The equal-days assumption was not declared for this run, so no annual projection is included.",
  ],
  [
    "device_flexibility_planner",
    "09 is a 24-hour device schedule; it has no annual projection.",
  ],
];

test("the annual-unavailable panel has an explicit title", () => {
  assert.ok(source.includes("Not included in this report"));
});

test("each application page has its own unavailable copy", () => {
  for (const [page, copy] of PAGE_COPY) {
    assert.ok(source.includes(`case "${page}":`), `missing case for ${page}`);
    assert.ok(source.includes(copy), `missing copy for ${page}`);
  }
  assert.ok(source.includes("No annual projection is included in this report."));
});

test("the normal annual projection path is still present", () => {
  assert.ok(source.includes("{annual && figures ? ("));
  assert.ok(source.includes("ANNUAL PROJECTION"));
});

test("the panel does not render a null or undefined annual value", () => {
  assert.ok(!source.includes("annual: null"));
  assert.ok(!source.includes("{String(annual)}"));
});
