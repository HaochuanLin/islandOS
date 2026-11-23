"""Regression checks for the deployment build stamp.

The stamp exists so that "which commit is the hosted app running?" stops being
unanswerable. These tests pin the two properties that make it worth reading:
the commit comes from the checkout (never a constant in this repository), and
an unknown deployment says ``unknown`` instead of inventing a value.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from islandos_core import build_info  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr="")


class Runner:
    """A stand-in for ``subprocess.run`` that answers the two git calls by order."""

    def __init__(self, rev_parse: object, status: object = None):
        self.rev_parse = rev_parse
        self.status = completed("") if status is None else status
        self.calls: list[list[str]] = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(list(arguments))
        answer = self.rev_parse if len(self.calls) == 1 else self.status
        if isinstance(answer, Exception):
            raise answer
        return answer


class CommitNormalisationTests(unittest.TestCase):
    def test_accepts_lower_case_full_sha(self):
        self.assertEqual(build_info.normalise_commit(SHA), SHA)
        self.assertEqual(build_info.normalise_commit(f"  {SHA.upper()}  "), SHA)

    def test_rejects_everything_that_is_not_a_full_sha(self):
        for value in ("", "unknown", None, 123, SHA[:7], SHA[:-1], SHA + "0", "g" * 40, SHA.replace("0", "x")):
            with self.subTest(value=value):
                self.assertIsNone(build_info.normalise_commit(value))

    def test_short_form_is_seven_characters(self):
        self.assertEqual(build_info.short_commit(SHA), SHA[:7])
        self.assertIsNone(build_info.short_commit("unknown"))


class BuildStampTests(unittest.TestCase):
    def test_clean_checkout_names_its_head_commit(self):
        stamp = build_info.build_stamp(runner=Runner(completed(SHA + "\n")), environ={})
        self.assertEqual(stamp["source_commit"], SHA)
        self.assertEqual(stamp["source_commit_short"], SHA[:7])
        self.assertEqual(stamp["resolved_from"], build_info.RESOLVED_FROM_GIT)
        self.assertFalse(stamp["working_tree_dirty"])
        self.assertIsNone(stamp["unresolved_reason"])
        self.assertEqual(stamp["schema_version"], build_info.SCHEMA_VERSION)

    def test_modified_checkout_is_reported_as_dirty(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed(SHA + "\n"), completed(" M app.py\n")), environ={}
        )
        self.assertTrue(stamp["working_tree_dirty"])

    def test_no_git_metadata_reports_unknown_not_a_placeholder(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed("", returncode=128)), environ={}
        )
        self.assertIsNone(stamp["source_commit"])
        self.assertIsNone(stamp["source_commit_short"])
        self.assertEqual(stamp["resolved_from"], build_info.RESOLVED_FROM_NONE)
        self.assertEqual(stamp["unresolved_reason"], "not-a-git-checkout")

    def test_missing_git_binary_reports_unknown(self):
        stamp = build_info.build_stamp(
            runner=Runner(FileNotFoundError("git")), environ={}
        )
        self.assertEqual(stamp["resolved_from"], build_info.RESOLVED_FROM_NONE)
        self.assertEqual(stamp["unresolved_reason"], "git-not-runnable")

    def test_declared_commit_is_reported_as_environment_not_git(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed("", returncode=128)),
            environ={build_info.ENVIRONMENT_VARIABLE: SHA.upper()},
        )
        self.assertEqual(stamp["source_commit"], SHA)
        self.assertEqual(stamp["resolved_from"], build_info.RESOLVED_FROM_ENVIRONMENT)

    def test_a_declared_value_that_is_not_a_sha_is_ignored(self):
        for declared in ("unknown", "main", SHA[:7], "0" * 40 + "\n?"):
            with self.subTest(declared=declared):
                stamp = build_info.build_stamp(
                    runner=Runner(completed("", returncode=128)),
                    environ={build_info.ENVIRONMENT_VARIABLE: declared},
                )
                self.assertIsNone(stamp["source_commit"])
                self.assertEqual(stamp["resolved_from"], build_info.RESOLVED_FROM_NONE)

    def test_a_declared_commit_does_not_claim_a_dirty_state(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed("", returncode=128)),
            environ={build_info.ENVIRONMENT_VARIABLE: SHA},
        )
        self.assertIsNone(stamp["working_tree_dirty"])
        self.assertIsNone(stamp["unresolved_reason"])

    def test_a_failing_status_leaves_dirtiness_unknown_rather_than_clean(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed(SHA + "\n"), completed("", returncode=128)), environ={}
        )
        self.assertEqual(stamp["source_commit"], SHA)
        self.assertIsNone(stamp["working_tree_dirty"])

    def test_the_document_always_carries_every_key(self):
        for runner in (Runner(FileNotFoundError("git")), Runner(completed(SHA + "\n"))):
            with self.subTest(runner=runner.rev_parse):
                stamp = build_info.build_stamp(runner=runner, environ={})
                self.assertEqual(
                    set(stamp),
                    {
                        "schema_version",
                        "source_commit",
                        "source_commit_short",
                        "resolved_from",
                        "unresolved_reason",
                        "working_tree_dirty",
                        "captured_at_utc",
                    },
                )

    def test_capture_time_is_utc_and_injectable(self):
        stamp = build_info.build_stamp(
            runner=Runner(completed(SHA + "\n")),
            environ={},
            now=datetime(2026, 11, 23, 12, 0, 0, 123456, tzinfo=timezone.utc),
        )
        self.assertEqual(stamp["captured_at_utc"], "2026-11-23T12:00:00+00:00")

    def test_git_is_asked_about_head_and_only_tracked_changes(self):
        runner = Runner(completed(SHA + "\n"))
        build_info.build_stamp(runner=runner, environ={})
        self.assertEqual(runner.calls[0][1:3], ["rev-parse", "HEAD"])
        self.assertIn("--untracked-files=no", runner.calls[1])


class StampPublishingTests(unittest.TestCase):
    def test_write_is_atomic_and_json_round_trips(self):
        stamp = build_info.build_stamp(runner=Runner(completed(SHA + "\n")), environ={})
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "static" / build_info.STAMP_FILENAME
            written = build_info.write_stamp(stamp, target)
            self.assertEqual(written, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), stamp)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_stamp_path_and_url_agree(self):
        self.assertEqual(build_info.stamp_path(ROOT), ROOT / "static" / "build_info.json")
        self.assertEqual(build_info.STAMP_URL_PATH, "/app/static/build_info.json")


class CaptionTests(unittest.TestCase):
    def test_a_known_commit_shows_the_short_sha_and_source(self):
        self.assertEqual(
            build_info.caption({"source_commit_short": "abc1234", "resolved_from": "git"}),
            "build abc1234 (git)",
        )

    def test_a_dirty_tree_is_flagged(self):
        self.assertIn(
            "dirty tree",
            build_info.caption(
                {"source_commit_short": "abc1234", "resolved_from": "git", "working_tree_dirty": True}
            ),
        )

    def test_an_unknown_deployment_says_so_with_the_reason(self):
        self.assertEqual(
            build_info.caption(
                {
                    "source_commit_short": None,
                    "resolved_from": "none",
                    "unresolved_reason": "not-a-git-checkout",
                }
            ),
            "build unknown (not-a-git-checkout)",
        )


class NoFakeStampTests(unittest.TestCase):
    def test_module_never_contains_a_literal_commit(self):
        source = (ROOT / "islandos_core" / "build_info.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"[0-9a-f]{40}", source), [])

    def test_module_is_streamlit_free(self):
        source = (ROOT / "islandos_core" / "build_info.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", source)
        self.assertNotIn("from streamlit", source)

    def test_app_publishes_the_stamp_and_renders_it(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("build_info.build_stamp()", source)
        self.assertIn("build_info.write_stamp(stamp)", source)
        self.assertIn("build_info.caption(deployment_stamp())", source)


class SidebarTests(unittest.TestCase):
    def test_the_sidebar_ends_with_the_published_build_line(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
        self.assertFalse(app.exception)
        captions = [element.value for element in app.sidebar.caption]
        self.assertTrue(captions, "the sidebar rendered no captions")
        self.assertTrue(captions[-1].startswith("build "), captions)

        published = json.loads(
            (ROOT / "static" / build_info.STAMP_FILENAME).read_text(encoding="utf-8")
        )
        expected = published["source_commit_short"] or "unknown"
        self.assertIn(expected, captions[-1])
        self.assertIn(published["resolved_from"], captions[-1])


if __name__ == "__main__":
    unittest.main()
