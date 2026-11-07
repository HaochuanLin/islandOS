"""First local Windows desktop shell for IslandOS (PySide6).

Install optional desktop dependencies with:
    python -m pip install -r requirements.txt -r requirements-desktop.txt
Run from the repository root:
    python -m desktop_app.main

This is an early local workflow prototype, not a signed installer or controller.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from islandos_core.application import (
    create_local_project,
    inspect_upload,
    open_local_project,
    register_inspected_import,
)


class IslandOSDesktopWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IslandOS · Energy Decision Support")
        self.resize(1120, 760)
        self.database_path: Path | None = None
        self.project_id: str | None = None
        self.last_inspection: dict | None = None
        self.last_file_name: str | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QLabel("IslandOS")
        header.setStyleSheet("font-size: 26px; font-weight: 700;")
        subtitle = QLabel(
            "Local decision-support prototype · Import → Review → Model readiness → Audit"
        )
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(header)
        layout.addWidget(subtitle)

        project_form = QFormLayout()
        self.workspace_edit = QLineEdit()
        self.workspace_edit.setPlaceholderText("Choose a local .sqlite3 workspace file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_workspace)
        workspace_row = QHBoxLayout()
        open_existing = QPushButton("Open existing…")
        open_existing.clicked.connect(self.open_existing_project)
        workspace_row.addWidget(self.workspace_edit, 1)
        workspace_row.addWidget(browse)
        workspace_row.addWidget(open_existing)
        workspace_widget = QWidget()
        workspace_widget.setLayout(workspace_row)
        project_form.addRow("Workspace", workspace_widget)

        self.project_id_edit = QLineEdit("site-001")
        self.project_name_edit = QLineEdit("New energy site")
        self.actor_edit = QLineEdit("local-user")
        project_form.addRow("Project ID", self.project_id_edit)
        project_form.addRow("Project name", self.project_name_edit)
        project_form.addRow("Local operator ID", self.actor_edit)
        layout.addLayout(project_form)

        self.project_consent = QCheckBox(
            "I consent to storing project metadata in this local workspace."
        )
        layout.addWidget(self.project_consent)
        create_button = QPushButton("Create / initialize local project")
        create_button.clicked.connect(self.create_project)
        layout.addWidget(create_button)

        self.project_status = QLabel("No project selected.")
        self.project_status.setWordWrap(True)
        layout.addWidget(self.project_status)

        layout.addWidget(QLabel("Data onboarding"))
        controls = QHBoxLayout()
        self.task_edit = QLineEdit("exploration")
        self.task_edit.setPlaceholderText("exploration / forecasting / dispatch_optimization")
        inspect_button = QPushButton("Choose file and inspect")
        inspect_button.clicked.connect(self.choose_and_inspect)
        controls.addWidget(self.task_edit, 1)
        controls.addWidget(inspect_button)
        layout.addLayout(controls)

        self.import_consent = QCheckBox(
            "I consent to storing import metadata and file hash locally (the raw file is not stored)."
        )
        layout.addWidget(self.import_consent)
        self.save_import_button = QPushButton("Save import metadata to this project")
        self.save_import_button.setEnabled(False)
        self.save_import_button.clicked.connect(self.save_import_metadata)
        layout.addWidget(self.save_import_button)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "Inspection results, data-quality warnings and task-specific blockers will appear here."
        )
        layout.addWidget(self.output, 1)

        footer = QLabel(
            "Offline only. No device connection, control command, safety certification or guaranteed savings."
        )
        footer.setStyleSheet("color: #9a3412;")
        footer.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(footer)

    def choose_workspace(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose local IslandOS workspace", "islandos_workspace.sqlite3",
            "SQLite database (*.sqlite3 *.db)",
        )
        if path:
            self.workspace_edit.setText(path)

    def open_existing_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open existing IslandOS workspace", "",
            "SQLite database (*.sqlite3 *.db)",
        )
        if not path:
            return
        project_id = self.project_id_edit.text().strip()
        if not project_id:
            QMessageBox.warning(self, "Project ID required", "Enter the project ID to open.")
            return
        try:
            result = open_local_project(path, project_id=project_id)
            self.workspace_edit.setText(path)
            self.database_path = Path(path)
            self.project_id = project_id
            project = result["project"]
            self.project_name_edit.setText(project["display_name"])
            self.project_status.setText(
                f"Opened local project: {project['display_name']} ({project_id}) · "
                f"audit events verified: {result['audit']['event_count']}"
            )
            self.save_import_button.setEnabled(self.last_inspection is not None)
            QMessageBox.information(self, "Workspace opened", "Project found and audit chain verified.")
        except Exception as exc:
            QMessageBox.critical(self, "Could not open workspace", str(exc))

    def create_project(self) -> None:
        path = self.workspace_edit.text().strip()
        project_id = self.project_id_edit.text().strip()
        project_name = self.project_name_edit.text().strip()
        actor = self.actor_edit.text().strip()
        if not all((path, project_id, project_name, actor)):
            QMessageBox.warning(self, "Missing information", "Complete workspace, project and operator fields.")
            return
        if not self.project_consent.isChecked():
            QMessageBox.warning(self, "Consent required", "Confirm local metadata storage before creating the project.")
            return
        try:
            database = Path(path)
            if database.exists():
                QMessageBox.warning(
                    self, "Existing workspace",
                    "This prototype initializes a new workspace. Choose a new database file; "
                    "opening or migrating an existing workspace is not implemented yet.",
                )
                return
            create_local_project(
                database, workspace_id="local-" + project_id,
                project_id=project_id, display_name=project_name,
                actor_id=actor, consent_to_store_metadata=True,
            )
            self.database_path = database
            self.project_id = project_id
            self.project_status.setText(f"Active local project: {project_name} ({project_id})")
            self.save_import_button.setEnabled(self.last_inspection is not None)
            QMessageBox.information(self, "Project created", "Local project metadata workspace created.")
        except Exception as exc:
            QMessageBox.critical(self, "Project creation failed", str(exc))

    def choose_and_inspect(self) -> None:
        path, selected_filter = QFileDialog.getOpenFileName(
            self, "Select energy data", "",
            "Supported data (*.csv *.xlsx);;CSV files (*.csv);;Excel workbooks (*.xlsx)",
        )
        if not path:
            return
        try:
            suffix = Path(path).suffix.lower()
            options = {}
            if suffix == ".xlsx":
                timezone_name, accepted = QInputDialog.getText(
                    self, "Excel timestamp timezone",
                    "If timestamps in this workbook have no timezone, enter the site's IANA timezone "
                    "(for example Asia/Shanghai or Africa/Nairobi). Leave blank only if timestamps "
                    "already contain timezone information.",
                )
                if not accepted:
                    return
                options["timezone_name"] = timezone_name.strip() or None
            raw = Path(path).read_bytes()
            result = inspect_upload(
                raw, file_name=Path(path).name,
                source_type="customer_provided",
                task=self.task_edit.text().strip() or "exploration",
                options=options,
            )
            self.last_inspection = result
            self.last_file_name = Path(path).name
            self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.save_import_button.setEnabled(self.database_path is not None)
        except Exception as exc:
            self.last_inspection = None
            self.last_file_name = None
            self.save_import_button.setEnabled(False)
            QMessageBox.critical(self, "Import inspection failed", str(exc))

    def save_import_metadata(self) -> None:
        if self.database_path is None or self.project_id is None or self.last_inspection is None:
            QMessageBox.warning(self, "No active project", "Create a local project and inspect a file first.")
            return
        if not self.import_consent.isChecked():
            QMessageBox.warning(self, "Consent required", "Confirm local metadata storage before saving.")
            return
        try:
            artifact_id = register_inspected_import(
                self.database_path, project_id=self.project_id,
                file_name=self.last_file_name or "upload",
                inspection_result=self.last_inspection,
                actor_id=self.actor_edit.text().strip(),
                consent_to_store_metadata=True,
            )
            QMessageBox.information(
                self, "Metadata saved",
                f"Import metadata saved. Artifact ID: {artifact_id}\n"
                "The original uploaded file bytes were not copied into the workspace.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not save metadata", str(exc))


def main() -> int:
    app = QApplication(sys.argv)
    window = IslandOSDesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
