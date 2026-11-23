#!/usr/bin/env python3
"""Check what the hosted deployment can, and cannot, prove about itself.

Run against the public Streamlit app:

    python scripts/check_deployment.py --base-url https://islandos.streamlit.app

Three page routes must answer with the Streamlit front-end shell, and the
deployment must name the checkout it runs from. Three sources can carry that
name: ``/app/static/build_info.json`` when the host serves static files, the
sidebar's ``build <sha>`` download button — the same document, through a route
that needs no static serving — and, when neither is available, the rendered
``build <sha>`` line. When ``--expect-commit`` is given, the named commit must
equal it; on any other value the report says why the comparison cannot be made,
and never turns "could not check" into "checked and passed".

Measured facts this script is built on (2026-11-23, islandos.streamlit.app):

* every route — a page, ``/_stcore/health``, even a path that does not exist —
  answers ``200`` with one identical 9,782-byte front-end shell, so HTTP status
  alone proves nothing and no page title or button label is present in the
  HTML (Streamlit draws all of that in the browser);
* an unauthenticated request is redirected through
  ``share.streamlit.io/-/auth/app`` and needs a cookie jar to reach the shell;
* the only app-specific bytes that could be served over HTTP would come from
  ``./static`` at ``/app/static/<name>``, but Community Cloud does not serve
  that route: after the app was restarted on this commit,
  ``/app/static/build_info.json`` still answered ``200`` with the same shell,
  while the rendered sidebar named the commit (measured 2026-11-23). The stamp
  is therefore read when the host serves it — self-hosted, or a future Cloud
  build that enables the route — and otherwise taken from the sidebar's
  download button, which hands over the same document without static serving.
  The rendered ``build`` line remains the last resort.

Exit codes: 0 all checks passed, 1 a page route is not the app shell, 2 the
deployment names no commit through any source, 3 the named commit differs
from ``--expect-commit``, 4 a commit was expected but the deployment does not
name one it can be compared against, 5 the rendered app did not confirm the
commit it names.

``--warm`` opens the app once in a headless browser. That is not a convenience:
a Streamlit script only runs when a browser session connects, so a container
that has just restarted has nothing on disk yet, and an HTTP-only probe would
report a missing stamp for an app that is perfectly healthy — or, on Cloud,
never see the commit at all. The same page load also proves the app renders
without an exception, and exposes the sidebar's ``build`` line.
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

STAMP_DOWNLOAD_LABEL = "Download build stamp (JSON)"
"""The sidebar button that hands the same bytes to a reader.

Community Cloud serves files that are in the repository, not files a session writes,
so ``STAMP_PATH`` answers with the front-end shell there. The download is the route
that works on both a self-hosted server and Community Cloud; it is read through the
same headless session that warms the app."""

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

BASIS_STAMP = "stamp"
BASIS_RENDERED = "rendered"
"""Where the commit a deployment names was read from."""


def build_line_commit(line: object) -> tuple[str | None, str | None]:
    """Split a sidebar caption into ``(sha, source)``.

    ``build 1a2b3c4 (git)`` yields ``("1a2b3c4", "git")``. ``build unknown
    (<reason>)`` yields ``(None, None)`` — no commit and no source tag — while a
    line with a sha and no tag yields ``(sha, None)``, which the caller must
    treat as unattributed rather than assume it came from git.
    """
    if not line:
        return None, None
    match = BUILD_LINE_PATTERN.search(str(line))
    if match is None:
        return None, None
    sha, source = match.group(1), match.group(2)
    return (None if sha == "unknown" else sha), source


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


def reported_commit(
    stamp: Mapping[str, object] | None, render: Mapping[str, object] | None
) -> tuple[dict | None, str]:
    """Return the commit the deployment names, and where that name was read.

    The stamp carries a full 40-character SHA. The sidebar carries seven
    characters, which is enough to compare against the first seven of an
    expected commit, but not enough to reconstruct one.
    """
    if stamp and stamp.get("source_commit"):
        return {
            "commit": stamp.get("source_commit"),
            "short": stamp.get("source_commit_short"),
            "resolved_from": stamp.get("resolved_from"),
            "basis": BASIS_STAMP,
        }, BASIS_STAMP
    sha, source = build_line_commit((render or {}).get("build_line"))
    if sha:
        return {
            "commit": None,
            "short": sha,
            "resolved_from": source,
            "basis": BASIS_RENDERED,
        }, BASIS_RENDERED
    return None, ""


def compare_commit(
    stamp: Mapping[str, object] | None,
    expected: str | None,
    render: Mapping[str, object] | None = None,
) -> dict:
    """Decide whether the named commit can be compared, and whether it matches."""
    expected = (expected or "").strip().lower()
    if not expected:
        return {
            "assertion": "not-requested",
            "expected": None,
            "reported": None,
            "detail": "",
            "basis": None,
        }
    if not SHA_PATTERN.match(expected):
        return {
            "assertion": "invalid-expectation",
            "expected": expected,
            "reported": None,
            "detail": "--expect-commit is not a 40-character lower-case SHA",
            "basis": None,
        }
    named, basis = reported_commit(stamp, render)
    if named is None:
        return {
            "assertion": "unavailable",
            "expected": expected,
            "reported": None,
            "detail": "neither the stamp nor the sidebar names a commit",
            "basis": None,
        }
    if basis == BASIS_RENDERED:
        source = named.get("resolved_from")
        if source != "git":
            return {
                "assertion": "unassertable",
                "expected": expected,
                "reported": named.get("short"),
                "detail": (
                    "the sidebar names a commit it does not attribute to git"
                    + (f" ({source})" if source else ", with no source tag")
                ),
                "basis": BASIS_RENDERED,
            }
        if expected.startswith(str(named.get("short"))):
            return {
                "assertion": "match",
                "expected": expected,
                "reported": named.get("short"),
                "detail": (
                    "the sidebar shows seven characters; they are the first seven "
                    "of the expected commit, and the rest was not displayed"
                ),
                "basis": BASIS_RENDERED,
            }
        return {
            "assertion": "mismatch",
            "expected": expected,
            "reported": named.get("short"),
            "detail": "the sidebar names a different commit than the one expected",
            "basis": BASIS_RENDERED,
        }
    reported = stamp.get("source_commit")
    if not reported:
        return {
            "assertion": "unavailable",
            "expected": expected,
            "reported": None,
            "detail": f"the deployment publishes no commit ({stamp.get('unresolved_reason')})",
            "basis": BASIS_STAMP,
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
            "basis": BASIS_STAMP,
        }
    if reported == expected:
        return {
            "assertion": "match",
            "expected": expected,
            "reported": reported,
            "detail": "",
            "basis": BASIS_STAMP,
        }
    return {
        "assertion": "mismatch",
        "expected": expected,
        "reported": reported,
        "detail": "the deployment is running a different commit than the one expected",
        "basis": BASIS_STAMP,
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


def find_stamp_button(frame: object, timeout: float = 10.0, interval: float = 0.25) -> object | None:
    """Wait for the sidebar's download button, which mounts after its caption.

    Streamlit renders the build line before the button beside it, and a read taken
    between the two sees no button at all. Polling keeps that race from downgrading
    a byte-level stamp to the seven characters in the sidebar text.
    """
    deadline = time.monotonic() + timeout
    while True:
        button = frame.get_by_role("button", name=STAMP_DOWNLOAD_LABEL).first
        if button.count():
            return button
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def capture_stamp_download(frame: object, session: object, timeout: float = 20.0) -> dict:
    """Click the sidebar's download button and read the bytes it hands over.

    This is the stamp route that does not depend on static file serving, so it is
    the one that can carry a Community Cloud deployment's full commit. The document
    is validated with the same rules as the static file: a download is a transport,
    not a weaker kind of evidence.
    """
    result: dict = {
        "state": "not-found",
        "reason": "no button labelled " + repr(STAMP_DOWNLOAD_LABEL),
        "file_name": None,
        "bytes": None,
        "document": None,
    }
    try:
        button = find_stamp_button(frame, timeout=min(10.0, timeout))
        if button is None:
            result["reason"] = (
                "no button labelled "
                + repr(STAMP_DOWNLOAD_LABEL)
                + f" within {min(10.0, timeout):g}s"
            )
            return result
        with session.expect_download(timeout=timeout * 1000) as download_info:
            button.click()
        download = download_info.value
        path = download.path()
        data = Path(path).read_bytes() if path else b""
        result.update(file_name=download.suggested_filename, bytes=len(data))
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            result.update(state="unreadable", reason=f"{type(error).__name__}: {error}")
            return result
        stamp, reason = validate_stamp(document)
        if stamp is None:
            result.update(state="unreadable", reason=reason)
            return result
        result.update(state="captured", reason="", document=stamp)
    except Exception as error:  # noqa: BLE001 - Playwright raises many types
        result.update(state="failed", reason=f"{type(error).__name__}: {str(error)[:300]}")
    return result


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
            "download": {"state": "not-attempted", "reason": "playwright is not installed"},
        }
    result: dict = {
        "state": "failed",
        "build_line": None,
        "exception": None,
        "detail": "",
        "page": page,
        "frame_url": None,
        "sidebar_text": "",
        "download": {"state": "not-attempted", "reason": "the app was not rendered"},
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
            # The download is the stamp route that works where static serving does
            # not; it is read in this session because it cannot be reached without one.
            result["download"] = capture_stamp_download(
                frame, session, timeout=min(20.0, timeout)
            )
        except Exception as error:  # noqa: BLE001 - Playwright raises many types
            result["detail"] = f"{type(error).__name__}: {str(error)[:300]}"
        finally:
            browser.close()
    return result


def check_build_line(render: Mapping[str, object], stamp: Mapping[str, object] | None) -> dict:
    """Does the sidebar line agree with the stamp, or — with no stamp — stand on its own?"""
    line = render.get("build_line")
    if render.get("state") != "ok":
        return {"matches": False, "reason": "the app was not rendered"}
    if not line:
        return {"matches": False, "reason": "no build line in the sidebar"}
    sha, source = build_line_commit(line)
    short = (stamp or {}).get("source_commit_short")
    if short:
        stamp_source = stamp.get("resolved_from")
        named = str(short) in str(line)
        attributed = source is None or source == stamp_source
        if named and attributed:
            return {"matches": True, "reason": ""}
        return {
            "matches": False,
            "reason": f"sidebar says {line!r}, stamp says {short} ({stamp_source})",
        }
    if sha:
        if source == "git":
            return {"matches": True, "reason": ""}
        return {
            "matches": False,
            "reason": (
                f"sidebar says {line!r}, which does not attribute the sha to git"
                + (f" ({source})" if source else " (no source tag)")
            ),
        }
    named_unknown = "unknown" in str(line)
    return {
        "matches": named_unknown,
        "reason": "" if named_unknown else f"sidebar says {line!r} but names no commit",
    }


NOT_PROVED: tuple[str, ...] = (
    "everything the rendered page shows beyond the build line: the shell is the "
    "same for every route, and only the elements this check reads are inspected",
    "that the running process executes the code of the commit it reports, beyond "
    "the checkout it reads git from",
    "that the host serves the static stamp: Community Cloud answered "
    "/app/static/build_info.json with the front-end shell after a restart on "
    "2026-11-23, so on Cloud the stamp is read from the sidebar download, and the "
    "static file and the download are never compared byte for byte",
    "that the installed dependencies equal requirements-runtime.lock",
    "Streamlit Community Cloud's own build identity or provenance",
    "that the stamp cannot be made to lie: a code change could report a constant, "
    "which no external check can detect",
)
"""What the report must keep saying it did not prove; ``APP_INTEGRATION.md`` §7.4
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
    """Pick the single verdict the report states; the order is documented in §7.3.

    Pages first (the check is worthless if the routes do not answer), then the
    render, then the build line, the cross-check with a stamp if one is served,
    then the commit assertion. ``no_evidence`` is the last resort: nothing asked
    and nothing named, which an HTTP-only run against Cloud produces every time.
    """
    if not pages_ok:
        return "pages_failed"
    if warm and not render_ok:
        return "render_failed"
    if warm and not render.get("build_line"):
        return "build_line_missing"
    if warm and not line["matches"]:
        return "render_mismatch"
    if commit["assertion"] in {"mismatch", "invalid-expectation"}:
        return "commit_mismatch"
    if commit["assertion"] in {"unavailable", "unassertable"}:
        return "commit_unassertable"
    if not warm and not stamp_ok:
        return "no_evidence"
    return "ok"


def resolve_stamp(
    static: Mapping[str, object], render: Mapping[str, object], warm: bool
) -> dict:
    """Pick the stamp the report should use, and say which route it came from.

    The static file is preferred: it is the route a plain HTTP reader can fetch. When
    it answers with the front-end shell, the sidebar download is the same document
    through a transport that works on Community Cloud. Neither route is trusted more
    than the other — both are validated by :func:`validate_stamp`.
    """
    download = render.get("download") if isinstance(render, Mapping) else None
    download = download if isinstance(download, Mapping) else {}
    if static.get("state") == "published":
        return {
            "state": "published",
            "source": "static",
            "document": static.get("stamp"),
            "reason": "",
        }
    if warm and download.get("state") == "captured":
        return {
            "state": "published",
            "source": "download",
            "document": download.get("document"),
            "reason": "",
        }
    reason = str(static.get("reason") or "")
    if warm:
        download_reason = str(download.get("reason") or download.get("state") or "")
        reason = (
            f"{reason}; download: {download_reason}" if reason else f"download: {download_reason}"
        )
    return {
        "state": str(static.get("state")),
        "source": None,
        "document": None,
        "reason": reason,
    }


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
    render: dict = {
        "state": "not-requested",
        "build_line": None,
        "exception": None,
        "detail": "",
        "download": {"state": "not-attempted", "reason": "--warm was not requested"},
    }
    if warm:
        render = (warm_runner or warm_page)(base, warm_page_path, warm_timeout)
    # Read the stamp after the session: a fresh container has no file until one runs.
    stamp_probe = fetch(opener, base + STAMP_PATH, timeout)
    static_stamp = read_stamp(stamp_probe)
    stamp = resolve_stamp(static_stamp, render, warm)
    line = (
        check_build_line(render, stamp["document"]) if warm else {"matches": False, "reason": ""}
    )
    commit = compare_commit(stamp["document"], expect_commit, render)

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
                "the deployment publishes a build stamp that names the checkout it runs "
                "from (a static file, or the sidebar download, which is the route "
                "available where static serving is not)"
            ),
            "proved": stamp_ok,
            "evidence": {
                "source": stamp["source"],
                "response": stamp_probe.as_dict(),
                "static": {"state": static_stamp["state"], "reason": static_stamp["reason"]},
                "download": render.get("download"),
                "stamp": stamp["document"],
                "reason": stamp["reason"],
            },
        },
        {
            "claim": "the app renders a page without an exception",
            "proved": render_ok,
            "evidence": render,
        },
        {
            "claim": (
                "the sidebar's build line names a commit, and agrees with the "
                "stamp when the host serves one"
            ),
            "proved": bool(line["matches"]),
            "evidence": {"build_line": render.get("build_line"), **line},
        },
        {
            "claim": "the commit the deployment names equals the expected commit",
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
            "source": stamp["source"],
            "reason": stamp["reason"],
            "document": stamp["document"],
            "static": {
                "state": static_stamp["state"],
                "reason": static_stamp["reason"],
                "response": stamp_probe.as_dict(),
            },
            "download": render.get("download"),
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
    "no_evidence": 2,
    "commit_mismatch": 3,
    "commit_unassertable": 4,
    "render_failed": 5,
    "build_line_missing": 5,
    "render_mismatch": 5,
}
"""The documented mapping; ``APP_INTEGRATION.md`` §7 lists the same codes."""


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
            "APP_INTEGRATION.md section 7"
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
