from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_onboarding_page_uses_shared_application_service():
    source = (ROOT / "pages" / "3_Data_Onboarding_Lab.py").read_text(encoding="utf-8")
    assert "from islandos_core.application import" in source
    assert "inspect_upload as inspect_upload_service" in source
    assert "from islandos_core.onboarding import" in source
    assert "inspect_csv_bytes" not in source
    assert "inspect_excel_bytes" not in source


def test_optional_desktop_shell_uses_shared_core_and_has_no_streamlit_dependency():
    source = (ROOT / "desktop_app" / "main.py").read_text(encoding="utf-8")
    assert "from islandos_core.application import" in source
    assert "inspect_upload" in source
    assert "register_inspected_import" in source
    assert "import streamlit" not in source
    assert "control_command" not in source


def test_desktop_dependency_is_optional_and_separate():
    desktop_requirements = (ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
    base_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "PySide6" in desktop_requirements
    assert "PySide6" not in base_requirements
