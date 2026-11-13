from pathlib import Path
from unittest.mock import Mock

from tools.islandos_local import _run, doctor, wait_for_health


def test_compose_helper_runs_from_explicit_project_root():
    runner = Mock()
    root = Path("/tmp/islandos-project")
    _run(["docker", "compose", "ps"], root, runner=runner)
    runner.assert_called_once_with(
        ["docker", "compose", "ps"], cwd=str(root), check=True, text=True
    )


def test_doctor_returns_preflight_exit_code_and_prints_json(capsys, tmp_path):
    report = '{"scope":"local demo","production_authorized":false,"failed":0}'
    runner = Mock(return_value=Mock(returncode=0, stdout=report, stderr=""))
    assert doctor(tmp_path, runner=runner) == 0
    assert '"production_authorized": false' in capsys.readouterr().out


def test_health_check_accepts_only_http_200():
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    assert wait_for_health(opener=lambda *_a, **_k: Response(),
                           timeout_seconds=0, clock=lambda: 0, pause=lambda _s: None)


def test_health_check_fails_closed_when_endpoint_is_unavailable():
    from urllib.error import URLError
    assert not wait_for_health(opener=lambda *_a, **_k: (_ for _ in ()).throw(URLError("offline")),
                               timeout_seconds=0, clock=lambda: 0, pause=lambda _s: None)
