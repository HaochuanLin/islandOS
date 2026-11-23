#!/usr/bin/env python3
"""Check what the hosted deployment can, and cannot, prove about itself.

Run against the public Streamlit app:

    python scripts/check_deployment.py --base-url https://islandos.streamlit.app

Three page routes must answer with the Streamlit front-end shell, and the app
must publish its own checkout commit at ``/app/static/build_info.json``. When
``--expect-commit`` is given, the published commit must equal it; on any other
value the report says why the comparison cannot be made, and never turns "could
not check" into "checked and passed".

Measured facts this script is built on (2026-11-23, islandos.streamlit.app):

* every route — a page, ``/_stcore/health``, even a path that does not exist —
  answers ``200`` with one identical 9,782-byte front-end shell, so HTTP status
  alone proves nothing and no page title or button label is present in the
  HTML (Streamlit draws all of that in the browser);
* an unauthenticated request is redirected through
  ``share.streamlit.io/-/auth/app`` and needs a cookie jar to reach the shell;
* the only app-specific bytes served over HTTP are the files Streamlit exposes
  from ``./static`` at ``/app/static/<name>`` — which is why the build stamp is
  published there instead of being scraped out of the page.

Exit codes: 0 all checks passed, 1 a page route is not the app shell, 2 the
stamp is missing or unreadable, 3 the published commit differs from
``--expect-commit``, 4 a commit was expected but the deployment does not
publish one it can be compared against, 5 the rendered app did not confirm the
stamp.

``--warm`` opens the app once in a headless browser. That is not a convenience:
a Streamlit script only runs when a browser session connects, so on a container
that has just restarted the stamp file does not exist yet, and an HTTP-only
probe would report a missing stamp for an app that is perfectly healthy. The
same page load also proves the app renders without an exception, and lets the
sidebar's ``build`` line be compared with the published file.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

DEFAULT_BASE_URL = "https://islandos.streamlit.app"

PAGE_PATHS: tuple[str, ...] = (
    "/Customer_Decision_Dashboard",
    "/Forecast_Led_Joint_Resource_Optimizer",
    "/Device_Flexibility_Planner",
)
"""The three public pages: 05, 06 and 09 as the navigation exposes them."""

STAMP_PATH = "/app/static/build_info.json"
"""Static file the app writes at start-up (see ``islandos_core.build_info``).

Repeated here rather than imported: this script is the verifier, so it must not
take the writer's constants on trust. If the app moves the path, the check fails
and someone updates both — which is the point."""

STAMP_SCHEMA_VERSION = 1
"""The stamp schema this checker understands, pinned for the same reason."""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
"""A browser-looking UA: Streamlit Cloud treats obvious bots differently."""

AUTH_MARKER = "share.streamlit.io/-/auth/app"
"""Redirect target for an app that is private, or for a request without a cookie."""

SHELL_MARKERS: tuple[str, ...] = ("/-/build/", "_stcore", "static/js/index")
"""Streamlit front-end markers: Community Cloud serves ``/-/build/...`` assets,
a self-hosted server serves ``./static/js/index...`` and ``/_stcore/``."""

SHELL_DOCTYPE_WINDOW = 5_000
"""How far into the body to look for ``<!doctype html``.

A self-hosted server puts a long copyright comment before the doctype, so the
opening characters of the body are not enough; every shell measured so far is
well under this window."""

MAX_BODY_BYTES = 2_000_000
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHORT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7}$")
RESOLVED_FROM_VALUES = ("git", "environment", "none")

BUILD_LINE_PATTERN = re.compile(r"build ([0-9a-f]{7}|unknown)(?: \((git|environment|none)\))?")
"""The sidebar caption: ``build 1a2b3c4 (git)``, optionally ``· dirty tree``."""


@dataclass
class Probe:
    """One HTTP response, reduced to what the verdict needs."""

    url: str
    status: int | None = None
    content_type: str = ""
    final_url: str = ""
    body: str = ""
    kind: str = "unreachable"
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type,
            "final_url": self.final_url,
            "kind": self.kind,
            "detail": self.detail,
            "response_bytes": len(self.body.encode("utf-8")) if self.body else 0,
        }


def build_opener() -> urllib.request.OpenerDirector:
    """An opener that keeps cookies and follows redirects, like a browser."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept", "text/html,*/*")]
    return opener


def classify(probe: Probe) -> Probe:
    """Name what the response is, using the body rather than the status code.

    Status is not a discriminator here: the hosted app answers ``200`` for
    existing pages, missing pages and the health endpoint alike.
    """
    if probe.status is None:
        probe.kind = "unreachable"
        return probe
    if AUTH_MARKER in probe.final_url or AUTH_MARKER in probe.body:
        probe.kind = "requires_authentication"
        probe.detail = "redirected to Streamlit Cloud sign-in"
        return probe
    if probe.body.lstrip().startswith("{"):
        probe.kind = "json_document"
        return probe
    head = probe.body[:SHELL_DOCTYPE_WINDOW].lower()
    if probe.status == 200 and "<!doctype html" in head and any(
        marker in probe.body for marker in SHELL_MARKERS
    ):
        probe.kind = "streamlit_shell"
        return probe
    if probe.status == 404:
        probe.kind = "not_found"
        return probe
    probe.kind = "unexpected_response"
    probe.detail = f"status {probe.status}, {probe.content_type or 'no content-type'}"
    return probe


def fetch(opener: urllib.request.OpenerDirector, url: str, timeout: float) -> Probe:
    """GET ``url`` and classify the result; transport errors are results, not exceptions."""
    probe = Probe(url=url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout) as response:
            probe.status = response.status
            probe.content_type = response.headers.get("Content-Type", "")
            probe.final_url = response.geturl()
            probe.body = response.read(MAX_BODY_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        probe.status = error.code
        probe.content_type = error.headers.get("Content-Type", "") if error.headers else ""
        probe.final_url = error.geturl() if hasattr(error, "geturl") else url
        try:
            probe.body = error.read(MAX_BODY_BYTES).decode("utf-8", "replace")
        except OSError:
            probe.body = ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        probe.status = None
        probe.detail = f"{type(error).__name__}: {str(error)[:200]}"
    return classify(probe)


def validate_stamp(document: object) -> tuple[dict | None, str]:
    """Return ``(stamp, reason)``; ``stamp`` is ``None`` when the document is unusable."""
    if not isinstance(document, dict):
        return None, "stamp is not a JSON object"
    if document.get("schema_version") != STAMP_SCHEMA_VERSION:
        return None, f"unsupported schema_version {document.get('schema_version')!r}"
    commit = document.get("source_commit")
    if commit is not None and not (isinstance(commit, str) and SHA_PATTERN.match(commit)):
        return None, "source_commit is not a 40-character lower-case SHA"
    if document.get("resolved_from") not in RESOLVED_FROM_VALUES:
        return None, f"unexpected resolved_from {document.get('resolved_from')!r}"
    if commit is not None and document.get("resolved_from") == "none":
        return None, "a commit is published but resolved_from says none"
    # The rest is internal consistency: the sidebar line is compared against
    # source_commit_short, so a stamp whose short form disagrees with its full
    # commit would prove a narrower fact than it appears to.
    short = document.get("source_commit_short")
    if short is not None and not (isinstance(short, str) and SHORT_SHA_PATTERN.match(short)):
        return None, "source_commit_short is not a 7-character lower-case SHA"
    if commit is not None and short != commit[:7]:
        return None, "source_commit_short does not match source_commit"
    if not isinstance(document.get("working_tree_dirty"), (bool, type(None))):
        return None, "working_tree_dirty is not a boolean or null"
    if not isinstance(document.get("captured_at_utc"), str):
        return None, "captured_at_utc is not a string"
    return document, ""


def read_stamp(probe: Probe) -> dict:
    """Turn the stamp response into ``{"state": ..., "stamp": ..., "reason": ...}``."""
    if probe.kind == "requires_authentication":
        return {"state": "unreadable", "stamp": None, "reason": "authentication-required"}
    if probe.kind == "streamlit_shell":
        return {
            "state": "not_served",
            "stamp": None,
            "reason": (
                "the stamp path returned the front-end shell: static file serving is "
                "disabled, or the file was not written"
            ),
        }
    if probe.kind != "json_document":
        return {"state": "unreadable", "stamp": None, "reason": probe.detail or probe.kind}
    try:
        document = json.loads(probe.body)
    except json.JSONDecodeError as error:
        return {"state": "unreadable", "stamp": None, "reason": f"invalid JSON: {error}"}
    stamp, reason = validate_stamp(document)
    if stamp is None:
        return {"state": "unreadable", "stamp": None, "reason": reason}
    return {"state": "published", "stamp": stamp, "reason": ""}


def compare_commit(stamp: Mapping[str, object] | None, expected: str | None) -> dict:
    """Decide whether the published commit can be compared, and whether it matches."""
    expected = (expected or "").strip().lower()
    if not expected:
        return {"assertion": "not-requested", "expected": None, "reported": None, "detail": ""}
    if not SHA_PATTERN.match(expected):
        return {
            "assertion": "invalid-expectation",
            "expected": expected,
            "reported": None,
            "detail": "--expect-commit is not a 40-character lower-case SHA",
        }
    if not stamp:
        return {
            "assertion": "unavailable",
            "expected": expected,
            "reported": None,
            "detail": "no stamp to compare against",
        }
    reported = stamp.get("source_commit")
    if not reported:
        return {
            "assertion": "unavailable",
            "expected": expected,
            "reported": None,
            "detail": f"the deployment publishes no commit ({stamp.get('unresolved_reason')})",
        }
    if stamp.get("resolved_from") != "git":
        return {
            "assertion": "unassertable",
            "expected": expected,
            "reported": reported,
            "detail": (
                "the published commit is self-declared "
                f"({stamp.get('resolved_from')}), not read from the deployment's checkout"
            ),
        }
    if reported == expected:
        return {"assertion": "match", "expected": expected, "reported": reported, "detail": ""}
    return {
        "assertion": "mismatch",
        "expected": expected,
        "reported": reported,
        "detail": "the deployment is running a different commit than the one expected",
    }


def parse_build_line(text: str) -> str | None:
    """Return the sidebar line that starts ``build …``, or ``None``."""
    for line in text.splitlines():
        if BUILD_LINE_PATTERN.search(line):
            return line.strip()
    return None


def app_frame(session: object, timeout: float):
    """Return the frame that holds the app, or ``None`` if no frame shows it.

    Community Cloud does not render the app into the page it serves: ``/`` returns
    a wrapper whose body holds an ``<iframe src="…/~/+/">`` plus a status embed,
    so the page's own text is 72 characters and its DOM has no test ids. A
    self-hosted Streamlit server renders in the page itself. Searching every
    frame for the app container covers both without guessing at a URL shape.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for frame in session.frames:
            try:
                if frame.locator('[data-testid="stAppViewContainer"]').count():
                    return frame
            except Exception:  # noqa: BLE001 - a frame can be replaced mid-scan
                continue
        time.sleep(0.5)
    return None


def _poll_sidebar(frame: object, timeout: float) -> tuple[str, str | None, bool]:
    """Read the sidebar until the build line appears, the app raises, or time runs out.

    The app container exists before the page has finished: the caption is written
    after the page script returns, so one read races the render and finds the
    navigation menu without it.
    """
    deadline = time.monotonic() + timeout
    text = ""
    while True:
        try:
            text = frame.locator('[data-testid="stSidebar"]').inner_text(timeout=5000)
        except Exception:  # noqa: BLE001 - a redrawing sidebar can fail mid-read
            text = ""
        line = parse_build_line(text)
        raised = frame.locator('[data-testid="stException"]').count() > 0
        if line or raised or time.monotonic() >= deadline:
            return text, line, raised
        time.sleep(0.5)


def warm_page(base_url: str, page: str = "/", timeout: float = 90.0) -> dict:
    """Open the app in a headless browser and read the sidebar's build line.

    A Streamlit script runs only when a session connects, so this is also what
    writes the stamp on a container that has just restarted. The same load
    proves the page renders without an exception.

    Every branch returns the same keys, so a report never has to explain a shape.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "state": "playwright-missing",
            "build_line": None,
            "exception": None,
            "detail": "pip install playwright && playwright install chromium",
            "page": page,
            "frame_url": None,
            "sidebar_text": "",
        }
    result: dict = {
        "state": "failed",
        "build_line": None,
        "exception": None,
        "detail": "",
        "page": page,
        "frame_url": None,
        "sidebar_text": "",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            session = browser.new_page()
            session.goto(base_url + page, wait_until="domcontentloaded", timeout=timeout * 1000)
            frame = app_frame(session, timeout)
            if frame is None:
                result["detail"] = (
                    'no frame exposed [data-testid="stAppViewContainer"] within '
                    f"{timeout:g}s"
                )
                return result
            sidebar_text, build_line, exception = _poll_sidebar(frame, timeout)
            result.update(
                state="ok",
                build_line=build_line,
                exception=exception,
                sidebar_text=sidebar_text[:400],
                frame_url=frame.url,
            )
        except Exception as error:  # noqa: BLE001 - Playwright raises many types
            result["detail"] = f"{type(error).__name__}: {str(error)[:300]}"
        finally:
            browser.close()
    return result


def check_build_line(render: Mapping[str, object], stamp: Mapping[str, object] | None) -> dict:
    """Does the sidebar line name the commit the stamp publishes?"""
    line = render.get("build_line")
    if render.get("state") != "ok":
        return {"matches": False, "reason": "the app was not rendered"}
    if not line:
        return {"matches": False, "reason": "no build line in the sidebar"}
    short = (stamp or {}).get("source_commit_short")
    source = (stamp or {}).get("resolved_from")
    if short:
        named = str(short) in str(line)
        attributed = not source or f"({source})" in str(line)
        if named and attributed:
            return {"matches": True, "reason": ""}
        return {
            "matches": False,
            "reason": f"sidebar says {line!r}, stamp says {short} ({source})",
        }
    named_unknown = "unknown" in str(line)
    return {
        "matches": named_unknown,
        "reason": "" if named_unknown else f"sidebar says {line!r} but the stamp has no commit",
    }


NOT_PROVED: tuple[str, ...] = (
    "everything the rendered page shows beyond the build line: the shell is the "
    "same for every route, and only the elements this check reads are inspected",
    "that the running process executes the code of the commit it reports, beyond "
    "the checkout the stamp is read from",
    "that the installed dependencies equal requirements-runtime.lock",
    "Streamlit Community Cloud's own build identity or provenance",
    "that the stamp cannot be made to lie: a code change could report a constant, "
    "which no external check can detect",
)
"""What the report must keep saying it did not prove; ``APP_INTEGRATION.md`` §6.4
lists the same items."""


def verdict_for(
    pages_ok: bool,
    warm: bool,
    render: Mapping[str, object],
    render_ok: bool,
    stamp_ok: bool,
    line: Mapping[str, object],
    commit: Mapping[str, object],
) -> str:
    """Pick the single verdict the report states; the order is documented in §6.3.

    Pages first (the check is worthless if the routes do not answer), then the
    render, then the stamp, then the two cross-checks that need both, then the
    commit assertion.
    """
    if not pages_ok:
        return "pages_failed"
    if warm and not render_ok:
        return "render_failed"
    if not stamp_ok:
        return "stamp_unavailable"
    if warm and not render.get("build_line"):
        return "build_line_missing"
    if warm and not line["matches"]:
        return "render_mismatch"
    if commit["assertion"] in {"mismatch", "invalid-expectation"}:
        return "commit_mismatch"
    if commit["assertion"] in {"unavailable", "unassertable"}:
        return "commit_unassertable"
    return "ok"


def run_check(
    base_url: str = DEFAULT_BASE_URL,
    pages: Sequence[str] = PAGE_PATHS,
    expect_commit: str | None = None,
    timeout: float = 30.0,
    opener: urllib.request.OpenerDirector | None = None,
    now: datetime | None = None,
    warm: bool = False,
    warm_page_path: str = "/",
    warm_timeout: float = 90.0,
    warm_runner: Callable[..., dict] | None = None,
) -> dict:
    """Probe the deployment and return the report; never raises for a failed probe."""
    base = base_url.rstrip("/")
    opener = opener or build_opener()
    page_probes = [fetch(opener, base + path, timeout) for path in pages]
    render: dict = {"state": "not-requested", "build_line": None, "exception": None, "detail": ""}
    if warm:
        render = (warm_runner or warm_page)(base, warm_page_path, warm_timeout)
    # Read the stamp after the session: a fresh container has no file until one runs.
    stamp_probe = fetch(opener, base + STAMP_PATH, timeout)
    stamp = read_stamp(stamp_probe)
    commit = compare_commit(stamp["stamp"], expect_commit)
    line = check_build_line(render, stamp["stamp"]) if warm else {"matches": False, "reason": ""}

    pages_ok = bool(page_probes) and all(p.kind == "streamlit_shell" for p in page_probes)
    render_ok = warm and render["state"] == "ok" and not render["exception"]
    stamp_ok = stamp["state"] == "published"
    verdict = verdict_for(pages_ok, warm, render, render_ok, stamp_ok, line, commit)

    claims = [
        {
            "claim": "each public page route answers with the Streamlit front-end shell",
            "proved": pages_ok,
            "evidence": [p.as_dict() for p in page_probes],
        },
        {
            "claim": (
                "the deployment publishes a build stamp at "
                f"{STAMP_PATH} that names the checkout it runs from"
            ),
            "proved": stamp_ok,
            "evidence": {
                "response": stamp_probe.as_dict(),
                "stamp": stamp["stamp"],
                "reason": stamp["reason"],
            },
        },
        {
            "claim": "the app renders a page without an exception",
            "proved": render_ok,
            "evidence": render,
        },
        {
            "claim": "the sidebar's build line names the commit the stamp publishes",
            "proved": bool(line["matches"]),
            "evidence": {"build_line": render.get("build_line"), **line},
        },
        {
            "claim": "the published commit equals the expected commit",
            "proved": commit["assertion"] == "match",
            "evidence": commit,
        },
    ]
    not_proved = list(NOT_PROVED)

    return {
        "checked_at_utc": (now or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "base_url": base,
        "stamp_path": STAMP_PATH,
        "pages": [p.as_dict() for p in page_probes],
        "stamp": {
            "state": stamp["state"],
            "reason": stamp["reason"],
            "document": stamp["stamp"],
            "response": stamp_probe.as_dict(),
        },
        "rendered": render,
        "commit": commit,
        "claims": claims,
        "not_proved": not_proved,
        "verdict": verdict,
    }


EXIT_CODES: dict[str, int] = {
    "ok": 0,
    "pages_failed": 1,
    "stamp_unavailable": 2,
    "commit_mismatch": 3,
    "commit_unassertable": 4,
    "render_failed": 5,
    "build_line_missing": 5,
    "render_mismatch": 5,
}
"""The documented mapping; ``APP_INTEGRATION.md`` §6 lists the same codes."""


def exit_code_for(report: Mapping[str, object]) -> int:
    """Map a verdict to the documented exit code.

    A verdict missing from the table is a bug in this script, not a deployment
    failure, so it raises instead of borrowing another verdict's code.
    """
    verdict = str(report.get("verdict"))
    try:
        return EXIT_CODES[verdict]
    except KeyError:
        raise KeyError(
            f"verdict {verdict!r} has no exit code: add it to EXIT_CODES and to "
            "APP_INTEGRATION.md section 6"
        ) from None


def parse_arguments(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--page",
        action="append",
        dest="pages",
        help="page path to probe (repeatable); defaults to the three public pages",
    )
    parser.add_argument(
        "--expect-commit",
        default=None,
        help="40-character SHA the deployment must report; omit to skip the comparison",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", default=None, help="write the JSON report here")
    parser.add_argument(
        "--warm",
        action="store_true",
        help="open the app in a headless browser first: runs one session, writes the "
        "stamp on a fresh container, and compares the sidebar line with the file",
    )
    parser.add_argument("--warm-page", default="/", help="page to open when warming")
    parser.add_argument("--warm-timeout", type=float, default=90.0)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    report = run_check(
        base_url=arguments.base_url,
        pages=tuple(arguments.pages) if arguments.pages else PAGE_PATHS,
        expect_commit=arguments.expect_commit,
        timeout=arguments.timeout,
        warm=arguments.warm,
        warm_page_path=arguments.warm_page,
        warm_timeout=arguments.warm_timeout,
    )
    text = json.dumps(report, indent=2) + "\n"
    if arguments.report:
        Path(arguments.report).write_text(text, encoding="utf-8")
    print(text)
    return exit_code_for(report)


if __name__ == "__main__":
    sys.exit(main())
