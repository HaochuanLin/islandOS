import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

const PATHS = [
  ["Decision dashboard", "https://islandos.streamlit.app/Customer_Decision_Dashboard"],
  ["Joint resource optimizer", "https://islandos.streamlit.app/Forecast_Led_Joint_Resource_Optimizer"],
  ["Device flexibility planner", "https://islandos.streamlit.app/Device_Flexibility_Planner"],
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function anchorFor(url) {
  const match = source.match(
    new RegExp(`<a\\b[^>]*href="${escapeRegExp(url)}"[^>]*>([^<]*)</a>`),
  );
  assert.ok(match, `App.tsx has no anchor pointing at ${url}`);
  return { tag: match[0].slice(0, match[0].indexOf(">")), label: match[1].trim() };
}

test("console copy frames itself as a local reference surface, not the planning surface", () => {
  assert.ok(source.includes("local reference surface"), "missing 'local reference surface' positioning");
  assert.ok(
    source.includes("Planning runs open in the Streamlit demo."),
    "missing 'Planning runs open in the Streamlit demo.' sentence",
  );
});

test("the three public planning paths are linked", () => {
  for (const [label, url] of PATHS) {
    const anchor = anchorFor(url);
    assert.ok(
      anchor.label.startsWith(label),
      `anchor for ${url} should be labelled '${label}', got '${anchor.label}'`,
    );
  }
});

test("planning links open a new tab without leaking the opener", () => {
  for (const [, url] of PATHS) {
    const anchor = anchorFor(url);
    assert.ok(anchor.tag.includes('target="_blank"'), `${url} must set target="_blank"`);
    assert.ok(anchor.tag.includes('rel="noopener noreferrer"'), `${url} must set rel="noopener noreferrer"`);
  }
});

test("the existing contract viewer link and API version line are untouched", () => {
  assert.ok(source.includes("./application-views.html"), "the contract viewer link must stay");
  assert.ok(source.includes("Contract viewer (read only)"), "the contract viewer label must stay");
  assert.ok(source.includes("API v1"), "the API v1 copy must stay");
});
