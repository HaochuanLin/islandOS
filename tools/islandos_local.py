#!/usr/bin/env python3
"""Cross-platform operator helper for the loopback-only IslandOS demo deployment.

This helper manages the existing local Streamlit demo Compose project only.
It does not configure a public endpoint or deploy the customer API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def _run(command: list[str], root: Path, runner=subprocess.run):
    return runner(command, cwd=str(root), check=True, text=True)


def doctor(root: Path, runner=subprocess.run) -> int:
    result = runner(
        [sys.executable, "tools/deployment_preflight.py", "--json"],
        cwd=str(root), check=False, text=True, capture_output=True,
    )
    if result.stdout:
        try:
            report = json.loads(result.stdout)
            print(json.dumps(report, indent=2))
        except json.JSONDecodeError:
            print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return int(result.returncode)


def wait_for_health(url: str = "http://127.0.0.1:8501/_stcore/health",
                    timeout_seconds: float = 45.0, opener=urlopen,
                    clock=time.monotonic, pause=time.sleep) -> bool:
    deadline = clock() + timeout_seconds
    while clock() <= deadline:
        try:
            with opener(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError):
            pass
        pause(1.0)
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="run the static local-deployment preflight")
    up = sub.add_parser("up", help="build and start the loopback-only demo")
    up.add_argument("--no-build", action="store_true", help="start the previously built image")
    sub.add_parser("status", help="show Compose service status")
    sub.add_parser("down", help="stop the local demo")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "doctor":
        return doctor(root)
    if args.command == "up":
        if doctor(root) != 0:
            print("Preflight failed; startup blocked.", file=sys.stderr)
            return 2
        try:
            _run(["docker", "compose", "config", "--quiet"], root)
            if not args.no_build:
                _run(["docker", "compose", "build"], root)
            _run(["docker", "compose", "up", "-d"], root)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not start IslandOS: {exc}", file=sys.stderr)
            return 2
        if not wait_for_health():
            print("Container started but local health check did not pass. Inspect: docker compose logs --tail=100 islandos-web", file=sys.stderr)
            return 3
        print("IslandOS local demo is healthy at http://127.0.0.1:8501 (loopback only).")
        return 0
    if args.command == "status":
        try:
            _run(["docker", "compose", "ps"], root)
            return 0
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not read Compose status: {exc}", file=sys.stderr)
            return 2
    if args.command == "down":
        try:
            _run(["docker", "compose", "down"], root)
            return 0
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not stop IslandOS: {exc}", file=sys.stderr)
            return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
