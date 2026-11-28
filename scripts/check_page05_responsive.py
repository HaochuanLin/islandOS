#!/usr/bin/env python3
"""Render Page05 in a real browser and assert its responsive layout.

This is the persistent CI counterpart to the one-off public acceptance review.
It deliberately uses the existing Playwright dependency and the deployment
checker's frame helper rather than introducing a second browser framework.

Run against a locally started Streamlit app:

    python scripts/check_page05_responsive.py \
      --base-url http://127.0.0.1:8501 \
      --report page05-responsive.json

The checks are DOM/layout assertions, not screenshot comparisons. A screenshot
is optional evidence only; the pass/fail decision is based on rendered text,
line boxes and card geometry.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_deployment import app_frame  # noqa: E402 - same Playwright setup

VIEWPORTS = (
    (320, 800),
    (390, 844),
    (670, 844),
    (1024, 900),
    (1180, 900),
    (1181, 900),
    (1440, 900),
)
EXPECTED_LABELS = (
    "recommended policy",
    "estimated 24h energy cost",
    "unmet energy",
    "modeled cost difference vs grid-first",
    "net present value",
    "simple payback",
    "discounted payback",
    "break-even annual energy saving",
)
EXPECTED_VALUES = (
    "Battery First",
    "24.52 USD",
    "0.00 kWh",
    "10.55 USD",
    "21,302 USD",
    "6.0 years",
    "8.5 years",
    "32,825 USD",
)
PAGE_PATH = "/Customer_Decision_Dashboard"
MAX_LABEL_LINE_END = re.compile(r"[-\u2010\u2011\u2012\u2013\u2014]$")
GRID_PHRASE = "grid-first"

DOM_JS = r"""
() => {
  // Only the eight visible decision metrics belong to the responsive surface.
  // The collapsed paired-policy expander also contains metric placeholders in
  // Streamlit's DOM with empty labels; scoping keeps them out of the check.
  const metricSelector =
    '[class*="st-key-decision-snapshot-metrics"] [data-testid="stMetric"], ' +
    '[class*="st-key-investment-metrics"] [data-testid="stMetric"]';
  const metricEls = [...document.querySelectorAll(metricSelector)];
  const labels = metricEls.map((metric) => metric.querySelector('[data-testid="stMetricLabel"]')).filter(Boolean).map((el) => {
    const p = el.querySelector('p') || el;
    const card = el.closest('[data-testid="stMetric"]');
    const cardRect = card ? card.getBoundingClientRect() : null;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(p);
    const lines = [];
    let buffer = '';
    let lineTop = null;
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, null);
    let node;
    const range = document.createRange();
    while ((node = walker.nextNode())) {
      const text = node.nodeValue || '';
      for (let index = 0; index < text.length; index += 1) {
        range.setStart(node, index);
        range.setEnd(node, index + 1);
        const glyph = range.getBoundingClientRect();
        if (glyph.width === 0 && glyph.height === 0) {
          buffer += text[index];
          continue;
        }
        const top = Math.round(glyph.top);
        if (lineTop === null) lineTop = top;
        if (Math.abs(top - lineTop) > 2) {
          lines.push(buffer.trim());
          buffer = '';
          lineTop = top;
        }
        buffer += text[index];
      }
    }
    if (buffer.trim()) lines.push(buffer.trim());
    return {
      text: el.innerText.trim(),
      font_size: parseFloat(style.fontSize),
      client_width: el.clientWidth,
      client_height: el.clientHeight,
      scroll_width: el.scrollWidth,
      scroll_height: el.scrollHeight,
      lines,
      card: cardRect && {
        x: Math.round(cardRect.x),
        y: Math.round(cardRect.y),
        width: Math.round(cardRect.width),
        height: Math.round(cardRect.height),
      },
      label_in_card:
        !!cardRect &&
        rect.left >= cardRect.left - 1 &&
        rect.right <= cardRect.right + 1 &&
        rect.top >= cardRect.top - 1 &&
        rect.bottom <= cardRect.bottom + 1,
    };
  });
  const values = metricEls.map((metric) => metric.querySelector('[data-testid="stMetricValue"]')).filter(Boolean).map((el) => {
    const card = el.closest('[data-testid="stMetric"]');
    const cardRect = card ? card.getBoundingClientRect() : null;
    const rect = el.getBoundingClientRect();
    return {
      text: el.innerText.trim(),
      client_width: el.clientWidth,
      scroll_width: el.scrollWidth,
      card_width: cardRect ? Math.round(cardRect.width) : null,
      value_in_card:
        !!cardRect &&
        rect.left >= cardRect.left - 1 &&
        rect.right <= cardRect.right + 1 &&
        rect.top >= cardRect.top - 1 &&
        rect.bottom <= cardRect.bottom + 1,
    };
  });
  return { labels, values };
}
"""


def normalize(text: str) -> str:
    return " ".join(text.replace("\u2011", "-").split()).lower()


def group_rows(cards: list[dict], tolerance: int = 8) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for card in sorted(cards, key=lambda item: (item["y"], item["x"])):
        for row in rows:
            if abs(row[0]["y"] - card["y"]) <= tolerance:
                row.append(card)
                break
        else:
            rows.append([card])
    return rows


def check_layout(labels: list[dict], values: list[dict], width: int) -> list[str]:
    failures: list[str] = []
    if len(labels) != len(EXPECTED_LABELS):
        failures.append(f"expected 8 metric labels, found {len(labels)}")
    if len(values) != len(EXPECTED_VALUES):
        failures.append(f"expected 8 metric values, found {len(values)}")

    normalized_labels = [normalize(item["text"]) for item in labels]
    if normalized_labels != list(EXPECTED_LABELS):
        failures.append(
            "metric labels changed: " + repr(normalized_labels)
        )
    normalized_values = [item["text"] for item in values]
    if normalized_values != list(EXPECTED_VALUES):
        failures.append("protected metric values changed: " + repr(normalized_values))

    for item in labels:
        if item["scroll_width"] > item["client_width"] + 1:
            failures.append(f"label horizontally overflows: {item['text']!r}")
        if item["scroll_height"] > item["client_height"] + 1:
            failures.append(f"label vertically overflows: {item['text']!r}")
        if not item["label_in_card"]:
            failures.append(f"label leaves its metric card: {item['text']!r}")
        if width <= 560 and item["font_size"] < 12.0:
            failures.append(f"label font below 12 px at {width}px: {item['font_size']}")
        for line in item["lines"]:
            if MAX_LABEL_LINE_END.search(line):
                failures.append(f"label line ends with a hyphen: {item['text']!r}: {line!r}")

    grid_label = next(
        (item for item in labels if GRID_PHRASE in normalize(item["text"])), None
    )
    if grid_label is None:
        failures.append("grid-first label is missing")
    else:
        normalized_lines = [normalize(line) for line in grid_label["lines"]]
        if not any(GRID_PHRASE in line for line in normalized_lines):
            failures.append(
                "grid-first is split across lines: " + repr(grid_label["lines"])
            )

    for item in values:
        if item["scroll_width"] > item["client_width"] + 1:
            failures.append(f"value horizontally overflows: {item['text']!r}")
        if not item["value_in_card"]:
            failures.append(f"value leaves its metric card: {item['text']!r}")

    cards = [item["card"] for item in labels if item["card"]]
    rows = group_rows(cards)
    expected_rows = 4 if width <= 560 else 2
    expected_per_row = 2 if width <= 560 else 4
    if len(rows) != expected_rows or any(len(row) != expected_per_row for row in rows):
        failures.append(
            f"unexpected card layout: {[(len(row), row[0]['y']) for row in rows]}"
        )
    if any(card["width"] < 120 or card["height"] < 80 for card in cards):
        failures.append("a metric card is too small to read: " + repr(cards))

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8501")
    parser.add_argument("--page", default=PAGE_PATH)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument(
        "--screenshot-dir",
        type=Path,
        default=None,
        help="optional directory for per-viewport dashboard screenshots",
    )
    args = parser.parse_args()

    failures: list[str] = []
    viewport_reports: list[dict] = []
    report: dict = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "page": args.page,
        "viewports": viewport_reports,
        "failures": failures,
        "ok": False,
    }

    if args.screenshot_dir is not None:
        args.screenshot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            session = browser.new_page(viewport={"width": 1440, "height": 900})
            session.goto(
                args.base_url.rstrip("/") + args.page,
                wait_until="domcontentloaded",
                timeout=args.timeout * 1000,
            )
            app = app_frame(session, args.timeout)
            if app is None:
                failures.append("no Streamlit app frame was found")
                return 1
            try:
                app.locator('[data-testid="stMetricLabel"]').first.wait_for(
                    timeout=args.timeout * 1000
                )
            except PlaywrightTimeoutError:
                failures.append("Page05 metric labels did not render before the timeout")
                return 1
            # Let Streamlit finish its first render before measuring.
            session.wait_for_timeout(700)

            for width, height in VIEWPORTS:
                session.set_viewport_size({"width": width, "height": height})
                # CSS media queries reflow synchronously; the short wait covers
                # Streamlit's own layout settling after a resize, not a reload.
                session.wait_for_timeout(500)
                measured = app.evaluate(DOM_JS)
                width_failures = check_layout(
                    measured["labels"], measured["values"], width
                )
                failures.extend(f"{width}px: {message}" for message in width_failures)

                snapshot = None
                if args.screenshot_dir is not None:
                    try:
                        snapshot = str(
                            args.screenshot_dir / f"page05-{width}.png"
                        )
                        app.locator(
                            '[class*="st-key-decision-snapshot-metrics"]'
                        ).first.screenshot(path=snapshot)
                    except Exception as error:  # noqa: BLE001 - evidence only
                        failures.append(f"{width}px: screenshot failed: {type(error).__name__}")

                viewport_reports.append(
                    {
                        "width": width,
                        "height": height,
                        "inner_width": session.evaluate("() => window.innerWidth"),
                        "ok": not width_failures,
                        "failures": width_failures,
                        "labels": measured["labels"],
                        "values": measured["values"],
                        "screenshot": snapshot,
                    }
                )
        except Exception as error:  # noqa: BLE001 - Playwright raises many types
            failures.append(f"{type(error).__name__}: {str(error)[:500]}")
        finally:
            browser.close()

    report["ok"] = not failures
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "viewports": [
                    {"width": item["width"], "ok": item["ok"]}
                    for item in viewport_reports
                ],
                "failures": failures,
            },
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
