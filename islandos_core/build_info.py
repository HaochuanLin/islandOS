"""Build identity for a running deployment.

The hosted Streamlit app cannot be asked "which commit are you?" through its
UI: Streamlit renders text in the browser, and the HTML the server returns is
the same generic shell for every route (measured: ``/``, a page route,
``/_stcore/health`` and an unknown path all return one identical shell). What
*can* be read over HTTP is a file the app writes into ``static/`` at start-up,
served at ``/app/static/build_info.json`` when static file serving is enabled.

The commit comes from the deployment's own checkout (``git rev-parse HEAD``) —
never from a constant in this repository. A hard-coded SHA would assert a fact
nobody verified, and a CI-written file cannot contain the SHA of the commit that
adds it (a commit cannot name itself), so it would only ever describe its parent.
When the deployment carries no git metadata the stamp says ``unknown`` and no
commit is claimed; the same goes for a dirty working tree, which is reported as
such because the commit then names the checkout's base, not its content.

This module imports nothing from Streamlit on purpose: the transport, the pages
and the tests must all be able to read the same stamp.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

SCHEMA_VERSION = 1
"""Version of the stamp document. Bump it only if a consumer must change."""

UNKNOWN = "unknown"
"""Literal used when no commit can be established. Never a placeholder SHA."""

STAMP_FILENAME = "build_info.json"
STAMP_RELATIVE_PATH = Path("static") / STAMP_FILENAME
STAMP_URL_PATH = "/app/static/" + STAMP_FILENAME
"""Where Streamlit serves the file: ``./static/<name>`` -> ``/app/static/<name>``."""

ENVIRONMENT_VARIABLE = "ISLANDOS_BUILD_COMMIT"
"""Optional self-declared commit, for deployments without a git checkout.

It is reported as ``environment`` rather than ``git`` because the value is not
read from the code being run; only ``git`` stamps can be compared to a branch.
"""

RESOLVED_FROM_GIT = "git"
RESOLVED_FROM_ENVIRONMENT = "environment"
RESOLVED_FROM_NONE = "none"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHORT_LENGTH = 7

REPO_ROOT = Path(__file__).resolve().parents[1]

_WRITE_LOCK = threading.Lock()
"""Serialise the rename, not the write: Windows refuses a replace while another
thread is renaming the same target. The lock is per process, which is the unit
that runs one Streamlit app; a second process still has its own temporary."""


def normalise_commit(value: object) -> str | None:
    """Return a lower-case 40-hex commit, or ``None`` if ``value`` is not one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if _SHA.match(candidate) else None


def short_commit(commit: str | None) -> str | None:
    """Return the seven-character form Git prints, or ``None``."""
    commit = normalise_commit(commit)
    return commit[:_SHORT_LENGTH] if commit else None


def _git(
    arguments: Sequence[str],
    repo_root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> subprocess.CompletedProcess | None:
    """Run one git command, or return ``None`` when git cannot be run at all."""
    try:
        return runner(
            ["git", *arguments],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def read_git_checkout(
    repo_root: Path | str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """Describe the git checkout at ``repo_root``.

    Returns ``{"commit", "dirty", "reason"}``. ``reason`` is ``git`` when a commit
    was read, otherwise the tag explaining why it could not be, so the caller can
    publish the same reason it used. Untracked files are ignored when deciding
    "dirty": the app writes its own stamp into ``static/`` at start-up, and that
    write must not make every deployment look modified.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    head = _git(["rev-parse", "HEAD"], root, runner)
    if head is None:
        return {"commit": None, "dirty": None, "reason": "git-not-runnable"}
    if head.returncode != 0:
        return {"commit": None, "dirty": None, "reason": "not-a-git-checkout"}
    commit = normalise_commit(head.stdout)
    if commit is None:
        return {"commit": None, "dirty": None, "reason": "unexpected-rev-parse-output"}
    status = _git(["status", "--porcelain", "--untracked-files=no"], root, runner)
    dirty = None if status is None or status.returncode != 0 else bool(status.stdout.strip())
    return {"commit": commit, "dirty": dirty, "reason": RESOLVED_FROM_GIT}


def _resolve(
    checkout: Mapping[str, object], environ: Mapping[str, str]
) -> tuple[str | None, str, str | None, bool | None]:
    """Return ``(commit, resolved_from, reason, dirty)`` in resolution order."""
    commit = checkout.get("commit")
    if isinstance(commit, str) and commit:
        dirty = checkout.get("dirty")
        return (
            commit,
            RESOLVED_FROM_GIT,
            str(checkout.get("reason") or RESOLVED_FROM_GIT),
            dirty if isinstance(dirty, bool) else None,
        )
    declared = normalise_commit(environ.get(ENVIRONMENT_VARIABLE, ""))
    if declared:
        return declared, RESOLVED_FROM_ENVIRONMENT, "environment-variable", None
    return None, RESOLVED_FROM_NONE, str(checkout.get("reason") or UNKNOWN), None


def build_stamp(
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """Build the stamp document for this deployment.

    Resolution order is git checkout, then ``ISLANDOS_BUILD_COMMIT``, then
    unknown.  The document always carries every key, so a consumer never has to
    guess whether a missing value means "absent" or "not reported".
    """
    environ = os.environ if environ is None else environ
    checkout = read_git_checkout(repo_root, runner=runner)
    commit, resolved_from, reason, dirty = _resolve(checkout, environ)
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_commit": commit,
        "source_commit_short": short_commit(commit),
        "resolved_from": resolved_from,
        "unresolved_reason": None if commit else reason,
        "working_tree_dirty": dirty,
        "captured_at_utc": captured.replace(microsecond=0).isoformat(),
    }


def stamp_path(repo_root: Path | str | None = None) -> Path:
    """Absolute path of the file the app serves as ``/app/static/build_info.json``."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    return root / STAMP_RELATIVE_PATH


def serialise_stamp(stamp: Mapping[str, object]) -> bytes:
    """The exact bytes of the published stamp.

    One place decides the bytes: the static file, the sidebar's download button and
    the check that reads either of them must agree, or a reader gets two documents
    claiming to be the same record.
    """
    return (json.dumps(dict(stamp), indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_stamp(stamp: Mapping[str, object], path: Path | str | None = None) -> Path:
    """Write ``stamp`` atomically and return the path written.

    The caller decides whether a failure is fatal: a read-only deployment must
    still render the page, so ``app.py`` swallows :class:`OSError` and shows the
    build line from memory.
    """
    target = Path(path) if path is not None else stamp_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # A fixed ".tmp" name lets two writers truncate each other's buffer before
    # either renames it, so each write gets its own temporary in the same
    # directory: ``os.replace`` is atomic only when the source is private.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialise_stamp(stamp))
        with _WRITE_LOCK:
            for attempt in range(5):
                try:
                    os.replace(temporary_name, target)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.01)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return target


def caption(stamp: Mapping[str, object]) -> str:
    """One-line human label: ``build 1a2b3c4 (git)`` or ``build unknown (<reason>)``."""
    commit = stamp.get("source_commit_short")
    resolved_from = stamp.get("resolved_from", RESOLVED_FROM_NONE)
    if commit:
        suffix = " · dirty tree" if stamp.get("working_tree_dirty") else ""
        return f"build {commit} ({resolved_from}){suffix}"
    reason = stamp.get("unresolved_reason") or UNKNOWN
    return f"build {UNKNOWN} ({reason})"
