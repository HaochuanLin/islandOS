"""Regression checks for the hosted-deployment evidence script.

Every case here is served by a local HTTP server, so the suite needs no network
and no real deployment. Two tests do talk to the public app; they are skipped
unless ``ISLANDOS_LIVE_DEPLOYMENT=1`` is set, because they cannot pass without
public internet access and a headless Chromium, and the stamp assertion also
needs a deployment that has been rebuilt with the build stamp.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_deployment as check  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"

SHELL = (
    "<!doctype html><html><head><title>Streamlit</title></head><body>"
    "<script type='module' src='/-/build/assets/routes-CSGpNduz.js'></script>"
    "</body></html>"
)
"""What the hosted app really returns for every route, page or not."""

LOGIN = (
    '<!doctype html><html><body>Sign in to Streamlit Community Cloud'
    '<a href="https://share.streamlit.io/-/auth/app?redirect_uri=x">Continue</a>'
    "</body></html>"
)

STAMP = {
    "schema_version": 1,
    "source_commit": SHA,
    "source_commit_short": SHA[:7],
    "resolved_from": "git",
    "unresolved_reason": None,
    "working_tree_dirty": False,
    "captured_at_utc": "2026-11-23T00:00:00+00:00",
}


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, bytes]] = {}

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        status, content_type, body = self.routes.get(
            self.path, (404, "text/plain", b"not found")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test output
        return


class LocalServer:
    """A throwaway HTTP server whose routes a test declares."""

    def __init__(self, routes: dict[str, tuple[int, str, bytes]]):
        handler = type("Handler", (_Handler,), {"routes": routes})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def routes_with_stamp(stamp: object = None, pages: dict | None = None):
    document = json.dumps(stamp if stamp is not None else STAMP).encode()
    routes = {
        "/page-a": (200, "text/html; charset=utf-8", SHELL.encode()),
        "/page-b": (200, "text/html; charset=utf-8", SHELL.encode()),
        check.STAMP_PATH: (200, "application/json", document),
        "/": (200, "text/html; charset=utf-8", SHELL.encode()),
    }
    routes.update(pages or {})
    return routes


class ClassifyTests(unittest.TestCase):
    def test_a_fake_shell_from_an_error_page_is_shell_because_the_status_never_differs(self):
        probe = check.classify(check.Probe(url="u", status=200, body=SHELL, content_type="text/html"))
        self.assertEqual(probe.kind, "streamlit_shell")

    def test_the_login_page_is_recognised_by_its_marker(self):
        probe = check.classify(check.Probe(url="u", status=200, body=LOGIN, final_url="https://x"))
        self.assertEqual(probe.kind, "requires_authentication")

    def test_a_redirect_to_sign_in_is_recognised_even_when_the_body_is_empty(self):
        probe = check.classify(
            check.Probe(url="u", status=200, body="", final_url="https://share.streamlit.io/-/auth/app?x=1")
        )
        self.assertEqual(probe.kind, "requires_authentication")

    def test_json_is_recognised_before_the_html_branch(self):
        probe = check.classify(
            check.Probe(url="u", status=200, body='{"schema_version": 1}', content_type="application/json")
        )
        self.assertEqual(probe.kind, "json_document")

    def test_a_missing_route_is_not_reported_as_a_shell(self):
        probe = check.classify(check.Probe(url="u", status=404, body="not found"))
        self.assertEqual(probe.kind, "not_found")

    def test_a_transport_error_is_a_result_not_an_exception(self):
        probe = check.classify(check.Probe(url="u", status=None, detail="timed out"))
        self.assertEqual(probe.kind, "unreachable")


class StampTests(unittest.TestCase):
    def test_a_deployment_that_reports_no_commit_is_not_called_a_match(self):
        stamp = dict(STAMP, source_commit=None, source_commit_short=None, resolved_from="none")
        result = check.compare_commit(stamp, SHA)
        self.assertEqual(result["assertion"], "unavailable")
        self.assertIsNone(result["reported"])

    def test_a_self_declared_commit_is_never_accepted_as_a_branch_match(self):
        stamp = dict(STAMP, resolved_from="environment")
        result = check.compare_commit(stamp, SHA)
        self.assertEqual(result["assertion"], "unassertable")
        self.assertIn("self-declared", result["detail"])

    def test_a_redirected_stamp_path_is_reported_as_authentication(self):
        probe = check.Probe(url="u", status=200, body=LOGIN)
        check.classify(probe)
        self.assertEqual(check.read_stamp(probe)["state"], "unreadable")

    def test_a_shell_at_the_stamp_path_means_static_serving_is_not_on(self):
        probe = check.classify(check.Probe(url="u", status=200, body=SHELL))
        result = check.read_stamp(probe)
        self.assertEqual(result["state"], "not_served")
        self.assertIn("static file serving", result["reason"])

    def test_an_unsupported_schema_version_is_unreadable(self):
        self.assertEqual(check.validate_stamp(dict(STAMP, schema_version=2))[1], "unsupported schema_version 2")

    def test_a_commit_that_is_not_a_full_sha_is_unreadable(self):
        self.assertIn("40-character", check.validate_stamp(dict(STAMP, source_commit="abc1234"))[1])

    def test_a_commit_with_resolved_from_none_is_contradictory(self):
        self.assertIn("resolved_from", check.validate_stamp(dict(STAMP, resolved_from="none"))[1])

    def test_a_non_object_document_is_unreadable(self):
        self.assertEqual(check.validate_stamp([STAMP])[1], "stamp is not a JSON object")

    def test_a_short_sha_that_disagrees_with_the_commit_is_unreadable(self):
        result = check.validate_stamp(dict(STAMP, source_commit_short=OTHER_SHA[:7]))
        self.assertEqual(result[1], "source_commit_short does not match source_commit")

    def test_a_short_sha_of_the_wrong_shape_is_unreadable(self):
        result = check.validate_stamp(dict(STAMP, source_commit_short="0123456x"))
        self.assertIn("7-character", result[1])

    def test_a_dirty_flag_that_is_not_a_boolean_is_unreadable(self):
        result = check.validate_stamp(dict(STAMP, working_tree_dirty="yes"))
        self.assertIn("working_tree_dirty", result[1])

    def test_a_stamp_without_a_capture_time_is_unreadable(self):
        result = check.validate_stamp(dict(STAMP, captured_at_utc=None))
        self.assertIn("captured_at_utc", result[1])


class RunCheckTests(unittest.TestCase):
    def test_a_healthy_deployment_matches_the_expected_commit(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(base_url=base, pages=("/page-a", "/page-b"), expect_commit=SHA)
        self.assertEqual(report["verdict"], "ok")
        self.assertEqual(check.exit_code_for(report), 0)
        proved = [claim["claim"] for claim in report["claims"] if claim["proved"]]
        self.assertTrue(any("front-end shell" in claim for claim in proved))
        self.assertTrue(any("build stamp" in claim for claim in proved))
        self.assertTrue(any("equals the expected commit" in claim for claim in proved))
        # Without --warm nothing was rendered, so the two render claims stay unproved.
        self.assertFalse(any("renders a page" in claim for claim in proved))
        self.assertIn("Streamlit", " ".join(report["not_proved"]))

    def test_a_different_commit_is_a_mismatch(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=OTHER_SHA)
        self.assertEqual(report["verdict"], "commit_mismatch")
        self.assertEqual(check.exit_code_for(report), 3)
        self.assertEqual(report["commit"]["reported"], SHA)

    def test_no_expectation_means_no_commit_claim(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(base_url=base, pages=("/page-a",))
        self.assertEqual(report["commit"]["assertion"], "not-requested")
        self.assertEqual(report["verdict"], "ok")
        commit_claim = next(c for c in report["claims"] if "equals the expected commit" in c["claim"])
        self.assertFalse(commit_claim["proved"])

    def test_an_http_only_run_against_a_host_without_static_files_reports_no_evidence(self):
        routes = routes_with_stamp()
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=SHA)
        self.assertEqual(report["stamp"]["state"], "not_served")
        self.assertEqual(report["verdict"], "commit_unassertable")
        self.assertEqual(check.exit_code_for(report), 4)
        self.assertEqual(report["commit"]["assertion"], "unavailable")

    def test_an_http_only_run_that_asks_nothing_and_sees_nothing_is_no_evidence(self):
        routes = routes_with_stamp()
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",))
        self.assertEqual(report["verdict"], "no_evidence")
        self.assertEqual(check.exit_code_for(report), 2)

    def test_the_sidebar_carries_the_commit_when_the_host_serves_no_stamp(self):
        routes = routes_with_stamp()
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        warm = lambda base_url, page, timeout: {  # noqa: E731 - one-line stub
            "state": "ok",
            "build_line": f"build {SHA[:7]} (git)",
            "exception": False,
            "detail": "",
        }
        with LocalServer(routes) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), expect_commit=SHA, warm=True, warm_runner=warm
            )
        self.assertEqual(report["verdict"], "ok")
        self.assertEqual(check.exit_code_for(report), 0)
        self.assertEqual(report["commit"]["assertion"], "match")
        self.assertEqual(report["commit"]["basis"], "rendered")
        self.assertEqual(report["commit"]["reported"], SHA[:7])
        self.assertFalse(report["stamp"]["state"] == "published")

    def test_a_sidebar_seven_characters_that_do_not_prefix_the_expectation_mismatch(self):
        routes = routes_with_stamp()
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        warm = lambda base_url, page, timeout: {  # noqa: E731 - one-line stub
            "state": "ok",
            "build_line": f"build {OTHER_SHA[:7]} (git)",
            "exception": False,
            "detail": "",
        }
        with LocalServer(routes) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), expect_commit=SHA, warm=True, warm_runner=warm
            )
        self.assertEqual(report["verdict"], "commit_mismatch")
        self.assertEqual(check.exit_code_for(report), 3)

    def test_a_sidebar_sha_without_a_source_tag_is_not_asserted(self):
        routes = routes_with_stamp()
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        warm = lambda base_url, page, timeout: {  # noqa: E731 - one-line stub
            "state": "ok",
            "build_line": f"build {SHA[:7]}",
            "exception": False,
            "detail": "",
        }
        with LocalServer(routes) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), expect_commit=SHA, warm=True, warm_runner=warm
            )
        self.assertEqual(report["verdict"], "render_mismatch")
        self.assertIn("no source tag", report["claims"][3]["evidence"]["reason"])

    def test_a_missing_page_fails(self):
        routes = routes_with_stamp(pages={"/page-a": (404, "text/plain", b"missing")})
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=SHA)
        self.assertEqual(report["verdict"], "pages_failed")
        self.assertEqual(check.exit_code_for(report), 1)

    def test_a_private_app_is_named_as_such_rather_than_as_a_broken_page(self):
        routes = routes_with_stamp(pages={"/page-a": (200, "text/html", LOGIN.encode())})
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",))
        self.assertEqual(report["pages"][0]["kind"], "requires_authentication")
        self.assertEqual(report["verdict"], "pages_failed")

    def test_a_self_declared_commit_cannot_be_asserted(self):
        with LocalServer(routes_with_stamp(stamp=dict(STAMP, resolved_from="environment"))) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=SHA)
        self.assertEqual(report["verdict"], "commit_unassertable")
        self.assertEqual(check.exit_code_for(report), 4)

    def test_an_invalid_expectation_is_refused_before_any_claim(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit="main")
        self.assertEqual(report["commit"]["assertion"], "invalid-expectation")
        self.assertEqual(report["verdict"], "commit_mismatch")

    def test_the_report_is_json_serialisable_and_names_its_limits(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=SHA)
        text = json.dumps(report)
        self.assertIn("not_proved", report)
        self.assertGreaterEqual(len(report["not_proved"]), 4)
        self.assertEqual(json.loads(text)["base_url"], base)


class BuildLineTests(unittest.TestCase):
    def test_the_real_caption_is_recognised(self):
        self.assertEqual(check.parse_build_line("Menu\nbuild 0123456 (git) · dirty tree\n"), "build 0123456 (git) · dirty tree")

    def test_an_unknown_caption_is_recognised(self):
        self.assertEqual(check.parse_build_line("build unknown (not-a-git-checkout)"), "build unknown (not-a-git-checkout)")

    def test_text_without_a_build_line_is_none(self):
        self.assertIsNone(check.parse_build_line("Energy & resource decision support"))

    def test_a_line_that_names_the_sha_and_its_source_matches_the_stamp(self):
        result = check.check_build_line(
            {"state": "ok", "build_line": f"build {SHA[:7]} (git) · dirty tree"}, STAMP
        )
        self.assertTrue(result["matches"], result["reason"])

    def test_a_line_with_the_right_sha_but_the_wrong_source_does_not_match(self):
        result = check.check_build_line(
            {"state": "ok", "build_line": f"build {SHA[:7]} (environment)"}, STAMP
        )
        self.assertFalse(result["matches"])
        self.assertIn("environment", result["reason"])


class WarmTests(unittest.TestCase):
    def warm(self, **overrides):
        base = {"state": "ok", "build_line": f"build {SHA[:7]} (git)", "exception": False, "detail": ""}
        base.update(overrides)
        return lambda base_url, page, timeout: dict(base)

    def test_a_rendered_page_confirms_the_stamp(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), expect_commit=SHA, warm=True, warm_runner=self.warm()
            )
        self.assertEqual(report["verdict"], "ok")
        self.assertTrue(all(claim["proved"] for claim in report["claims"]))

    def test_a_page_that_raises_is_a_failed_render(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), warm=True,
                warm_runner=self.warm(exception=True),
            )
        self.assertEqual(report["verdict"], "render_failed")
        self.assertEqual(check.exit_code_for(report), 5)

    def test_a_missing_browser_is_reported_rather_than_skipped(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), warm=True,
                warm_runner=self.warm(state="playwright-missing"),
            )
        self.assertEqual(report["verdict"], "render_failed")

    def test_a_page_without_the_caption_fails(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), warm=True,
                warm_runner=self.warm(build_line=None),
            )
        self.assertEqual(report["verdict"], "build_line_missing")

    def test_a_sidebar_that_names_another_commit_fails(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), warm=True,
                warm_runner=self.warm(build_line=f"build {OTHER_SHA[:7]} (git)"),
            )
        self.assertEqual(report["verdict"], "render_mismatch")
        self.assertIn(OTHER_SHA[:7], json.dumps(report["claims"]))

    def test_a_sidebar_that_borrows_the_sha_but_not_its_source_fails(self):
        with LocalServer(routes_with_stamp()) as base:
            report = check.run_check(
                base_url=base, pages=("/page-a",), warm=True,
                warm_runner=self.warm(build_line=f"build {SHA[:7]} (environment)"),
            )
        self.assertEqual(report["verdict"], "render_mismatch")


class VerdictOrderTests(unittest.TestCase):
    def test_a_broken_page_is_named_before_a_missing_stamp(self):
        routes = routes_with_stamp(pages={"/page-a": (404, "text/plain", b"missing")})
        routes[check.STAMP_PATH] = (200, "text/html; charset=utf-8", SHELL.encode())
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",))
        self.assertEqual(report["verdict"], "pages_failed")

    def test_an_unassertable_commit_is_named_after_the_stamp_is_read(self):
        routes = routes_with_stamp(stamp=dict(STAMP, resolved_from="environment"))
        with LocalServer(routes) as base:
            report = check.run_check(base_url=base, pages=("/page-a",), expect_commit=SHA)
        self.assertEqual(report["verdict"], "commit_unassertable")


class ExitCodeTests(unittest.TestCase):
    def test_an_unknown_verdict_raises_instead_of_borrowing_a_code(self):
        with self.assertRaises(KeyError) as raised:
            check.exit_code_for({"verdict": "nonsense"})
        self.assertIn("nonsense", str(raised.exception))

    def test_every_documented_verdict_has_a_code(self):
        self.assertEqual(
            set(check.EXIT_CODES),
            {
                "ok",
                "pages_failed",
                "no_evidence",
                "commit_mismatch",
                "commit_unassertable",
                "render_failed",
                "build_line_missing",
                "render_mismatch",
            },
        )


class MissingBrowserTests(unittest.TestCase):
    def test_the_missing_browser_branch_reports_the_whole_result_shape(self):
        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            result = check.warm_page("http://127.0.0.1:1", "/", timeout=1)
        self.assertEqual(result["state"], "playwright-missing")
        self.assertEqual(
            set(result),
            {"state", "build_line", "exception", "detail", "page", "frame_url", "sidebar_text"},
        )


class CommandLineTests(unittest.TestCase):
    def test_main_writes_the_report_and_returns_the_documented_code(self):
        with LocalServer(routes_with_stamp()) as base, tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            code = check.main(
                ["--base-url", base, "--page", "/page-a", "--expect-commit", SHA, "--report", str(target)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["verdict"], "ok")

    def test_main_returns_three_on_a_mismatch(self):
        with LocalServer(routes_with_stamp()) as base:
            code = check.main(["--base-url", base, "--page", "/page-a", "--expect-commit", OTHER_SHA])
        self.assertEqual(code, 3)


@unittest.skipUnless(
    os.environ.get("ISLANDOS_LIVE_DEPLOYMENT") == "1",
    "talks to the public app; set ISLANDOS_LIVE_DEPLOYMENT=1 to run it",
)
class LiveDeploymentTests(unittest.TestCase):
    def test_the_public_app_serves_three_pages_and_a_stamp(self):
        report = check.run_check(check.DEFAULT_BASE_URL, expect_commit=None)
        self.assertEqual(
            [page["kind"] for page in report["pages"]],
            ["streamlit_shell"] * 3,
            json.dumps(report, indent=2),
        )
        if report["verdict"] == "stamp_unavailable":
            self.skipTest(
                "the deployed app predates the build stamp, so there is nothing to compare yet; "
                "rerun after it is rebuilt (APP_INTEGRATION.md section 7.5)"
            )
        self.assertEqual(report["verdict"], "ok", json.dumps(report, indent=2))

    def test_the_public_app_renders_a_page(self):
        render = check.warm_page(check.DEFAULT_BASE_URL, "/", timeout=150.0)
        if render["state"] == "playwright-missing":
            self.skipTest(render["detail"])
        self.assertEqual(render["state"], "ok", json.dumps(render, indent=2))
        # Community Cloud renders the app inside a wrapper iframe, so the frame that
        # was read has to be named in the evidence; see APP_INTEGRATION.md section 7.1.
        self.assertIn("frame_url", render)


if __name__ == "__main__":
    unittest.main()
