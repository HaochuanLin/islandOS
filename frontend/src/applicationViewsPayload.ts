import type {
  AnnualProjection,
  DeviceFlexibilitySummary,
  RunRequest,
  RunResultSummary,
} from "./contracts";

export const CONTRACT_SCHEMA_VERSION = 3;

export type Views = {
  request: RunRequest;
  result: RunResultSummary | DeviceFlexibilitySummary;
  annual: AnnualProjection | null;
};

function schemaVersionOf(value: unknown): number | undefined {
  if (!value || typeof value !== "object") return undefined;
  const version = (value as Record<string, unknown>).schema_version;
  return typeof version === "number" ? version : undefined;
}

function requireCurrentVersion(value: unknown, label: string): void {
  const version = schemaVersionOf(value);
  if (version === undefined) {
    throw new Error(`${label} has no numeric schema_version; this viewer reads v${CONTRACT_SCHEMA_VERSION}.`);
  }
  if (version !== CONTRACT_SCHEMA_VERSION) {
    throw new Error(
      `${label} schema_version ${version} is not supported; this viewer reads v${CONTRACT_SCHEMA_VERSION}.`,
    );
  }
}

/**
 * Read a downloaded report's `application_views` block.
 *
 * The viewer refuses a v2 request or result rather than rendering half of an old
 * shape. The JSON Schema remains the full validating artifact; this is the one
 * guard the viewer itself can enforce before it casts fields.
 */
export function readViews(payload: unknown): Views {
  if (!payload || typeof payload !== "object") throw new Error("The file is not a JSON object.");
  const record = payload as Record<string, unknown>;
  const source = record.application_views ?? record;
  if (!source || typeof source !== "object") {
    throw new Error("No application_views block: load a report downloaded from page 05, 06 or 09.");
  }
  const views = source as Record<string, unknown>;
  if (!views.request || !views.result) {
    throw new Error("The block must carry both request and result.");
  }
  requireCurrentVersion(views.request, "Request");
  requireCurrentVersion(views.result, "Result");
  return {
    request: views.request as RunRequest,
    result: views.result as RunResultSummary | DeviceFlexibilitySummary,
    annual: (views.annual as AnnualProjection | null | undefined) ?? null,
  };
}
