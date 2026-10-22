from pathlib import Path
import unittest

from data_quality import REQUIRED_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "tools" / "site_data_entry.html"
GUIDE = ROOT / "docs" / "STAFF_DATA_ENTRY.md"


class StaffDataEntryFormTests(unittest.TestCase):
    def test_form_exists_and_contains_the_quality_gate_schema(self):
        html = FORM.read_text(encoding="utf-8")
        for column in REQUIRED_COLUMNS:
            with self.subTest(column=column):
                self.assertIn(column, html)

    def test_form_explains_units_validation_and_provenance(self):
        html = FORM.read_text(encoding="utf-8")
        for phrase in ("kW", "m³", "source", "检查数据", "保存草稿 JSON", "下载 CSV"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)

    def test_form_does_not_implement_remote_upload_or_network_calls(self):
        html = FORM.read_text(encoding="utf-8")
        for network_api in ("fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon"):
            with self.subTest(network_api=network_api):
                self.assertNotIn(network_api, html)

    def test_documentation_describes_offline_and_non_operational_scope(self):
        guide = GUIDE.read_text(encoding="utf-8")
        self.assertIn("does not", guide)
        self.assertIn("not automatically uploaded", guide.lower())
        self.assertIn("not a complete staff operations console", guide)


if __name__ == "__main__":
    unittest.main()
