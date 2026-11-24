"""The local site workspace must be usable, not just renderable.

Streamlit form widgets do not rerun the page until the form is submitted. The
old create-project form disabled its submit button on `not consent`, so ticking
the consent box could never enable the button: the page rendered but no project
could be created. These tests drive the real form through AppTest.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from islandos_core.workspace_store import list_projects

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "08_Site_Workspace.py"


def _app(tmp_path, monkeypatch) -> AppTest:
    monkeypatch.setenv("ISLANDOS_ENABLE_LOCAL_WORKSPACE", "1")
    monkeypatch.setenv("ISLANDOS_WORKSPACE_DB", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("ISLANDOS_SOURCE_STORAGE_DIR", str(tmp_path / "source"))
    return AppTest.from_file(str(PAGE), default_timeout=90).run()


def test_consent_then_create_project_succeeds(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    assert not app.exception
    app.text_input[0].set_value("T7 local project")
    app.checkbox[0].set_value(True)
    app.button[0].click().run()
    assert not app.exception
    projects = list_projects(tmp_path / "workspace.sqlite3")
    assert [item["display_name"] for item in projects] == ["T7 local project"]


def test_submit_without_consent_is_refused(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app.text_input[0].set_value("Unconsented project")
    app.button[0].click().run()
    assert not app.exception
    assert list_projects(tmp_path / "workspace.sqlite3") == []
    assert any("confirm local storage consent" in message.value.lower() for message in app.error)
