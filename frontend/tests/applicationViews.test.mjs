import assert from "node:assert/strict";
import test from "node:test";

import { CONTRACT_SCHEMA_VERSION, readViews } from "../dist-tests/applicationViewsPayload.js";
import { api, ApiError } from "../dist-tests/api.js";

const v3 = {
  application_views: {
    request: { schema_version: CONTRACT_SCHEMA_VERSION },
    result: { schema_version: CONTRACT_SCHEMA_VERSION },
    annual: null,
  },
};

test("readViews accepts a current v3 request and result", () => {
  const views = readViews(v3);
  assert.equal(views.request.schema_version, 3);
  assert.equal(views.result.schema_version, 3);
});

test("readViews refuses a v2 request instead of half-reading it", () => {
  assert.throws(
    () => readViews({
      application_views: { request: { schema_version: 2 }, result: { schema_version: 3 } },
    }),
    /Request schema_version 2 is not supported; this viewer reads v3\./,
  );
});

test("readViews refuses a v2 result", () => {
  assert.throws(
    () => readViews({
      application_views: { request: { schema_version: 3 }, result: { schema_version: 2 } },
    }),
    /Result schema_version 2 is not supported; this viewer reads v3\./,
  );
});

test("readViews refuses a block without a numeric schema_version", () => {
  assert.throws(
    () => readViews({ application_views: { request: {}, result: { schema_version: 3 } } }),
    /Request has no numeric schema_version/,
  );
});

test("latestTelemetry returns null only for the documented 404", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return { ok: false, status: 404, json: async () => ({ error: "no telemetry" }) };
  };
  assert.equal(await api.latestTelemetry("token", "site-1"), null);
  assert.match(calls[0], /site-1\/telemetry\/latest/);
});

test("latestTelemetry surfaces 401 and 500 instead of reporting no data", async () => {
  for (const status of [401, 500]) {
    globalThis.fetch = async () => ({
      ok: false,
      status,
      json: async () => ({ error: `failed ${status}` }),
    });
    await assert.rejects(
      api.latestTelemetry("token", "site-1"),
      (error) => error instanceof ApiError && error.status === status && error.message === `failed ${status}`,
    );
  }
});
