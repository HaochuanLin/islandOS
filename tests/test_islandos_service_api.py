"""Security and isolation tests for the versioned Stage E reference service."""
from datetime import datetime, timezone
import tempfile
import unittest
import pytest
from pathlib import Path

from islandos_service_api import IslandOSStore


class TestTenantScopedServiceStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = IslandOSStore(str(Path(self.tmp.name) / "service.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def principal(self, email, tenant):
        self.store.register(email, "correct-horse-battery-staple", tenant)
        login = self.store.login(email, "correct-horse-battery-staple")
        return self.store.authenticate(login["access_token"])

    def test_tenant_scoped_site_and_telemetry_access(self):
        alice = self.principal("alice@example.test", "Alpha")
        bob = self.principal("bob@example.test", "Beta")
        site = self.store.create_site(alice, "North site", "UTC")
        self.assertEqual(len(self.store.list_sites(alice)), 1)
        self.assertEqual(self.store.list_sites(bob), [])
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "renewable_surplus_kw": 12.0,
            "water_demand_m3": 1.2,
            "cooling_demand_kw_th": 3.4,
        }
        accepted = self.store.ingest_telemetry(alice, site["id"], payload, "unit-test")
        self.assertTrue(accepted["accepted"])
        self.assertFalse(accepted["physical_write_performed"])
        with self.assertRaises(LookupError):
            self.store.latest_telemetry(bob, site["id"])
        latest = self.store.latest_telemetry(alice, site["id"])
        self.assertEqual(latest["values"]["renewable_surplus_kw"], 12.0)
        self.assertFalse(latest["physical_write_performed"])

    def test_expired_or_unknown_session_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.store.authenticate("not-a-valid-session")

    def test_invalid_and_duplicate_telemetry_fail_closed(self):
        alice = self.principal("carol@example.test", "Gamma")
        site = self.store.create_site(alice, "Plant", "UTC")
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "renewable_surplus_kw": -1,
            "water_demand_m3": 1,
            "cooling_demand_kw_th": 1,
        }
        with self.assertRaises(ValueError):
            self.store.ingest_telemetry(alice, site["id"], payload, "unit-test")
        payload["renewable_surplus_kw"] = 2
        self.store.ingest_telemetry(alice, site["id"], payload, "unit-test")
        with self.assertRaises(ValueError):
            self.store.ingest_telemetry(alice, site["id"], payload, "unit-test")

    def test_site_deletion_cascades_telemetry(self):
        alice = self.principal("dana@example.test", "Delta")
        site = self.store.create_site(alice, "Remote site", "UTC")
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "renewable_surplus_kw": 2,
            "water_demand_m3": 1,
            "cooling_demand_kw_th": 1,
        }
        self.store.ingest_telemetry(alice, site["id"], payload, "unit-test")
        self.assertTrue(self.store.delete_site(alice, site["id"])["deleted"])
        with self.assertRaises(LookupError):
            self.store.latest_telemetry(alice, site["id"])


if __name__ == "__main__":
    unittest.main()



def test_logout_revokes_only_the_current_authenticated_session():
    store = IslandOSStore(":memory:")
    store.register("logout@example.test", "a-correct-long-password", "Logout tenant")
    first = store.login("logout@example.test", "a-correct-long-password")
    second = store.login("logout@example.test", "a-correct-long-password")
    principal = store.authenticate(first["access_token"])

    assert store.revoke_session(first["access_token"], principal) == {"revoked": True}
    with pytest.raises(PermissionError, match="invalid or expired"):
        store.authenticate(first["access_token"])

    # Revoking one browser session must not sign out the user's other session.
    assert store.authenticate(second["access_token"])["user_id"] == principal["user_id"]
