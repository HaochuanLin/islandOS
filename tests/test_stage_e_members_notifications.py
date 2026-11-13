from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

from islandos_service_api import IslandOSStore


class TestStageEMemberAndNotificationLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = IslandOSStore(str(Path(self.tmp.name) / "service.sqlite3"))
        self.owner = self.principal("owner@example.test", "Customer A")

    def tearDown(self):
        self.tmp.cleanup()

    def principal(self, email, tenant):
        self.store.register(email, "correct-horse-battery-staple", tenant)
        login = self.store.login(email, "correct-horse-battery-staple")
        return self.store.authenticate(login["access_token"])

    def test_invitation_acceptance_role_update_and_member_removal(self):
        invitation = self.store.create_invitation(
            self.owner, "analyst@example.test", role="analyst",
        )
        self.assertFalse(invitation["email_delivery_performed"])
        self.assertEqual(invitation["role"], "analyst")

        accepted = self.store.accept_invitation(
            invitation["invitation_token"], "another-correct-horse-password",
        )
        self.assertEqual(accepted["tenant_id"], self.owner["tenant_id"])
        self.assertEqual(accepted["role"], "analyst")
        with self.assertRaises(PermissionError):
            self.store.accept_invitation(
                invitation["invitation_token"], "another-correct-horse-password",
            )

        analyst_login = self.store.login(
            "analyst@example.test", "another-correct-horse-password",
        )
        analyst = self.store.authenticate(analyst_login["access_token"])
        self.assertEqual(len(self.store.list_members(self.owner)), 2)
        self.assertEqual(
            self.store.update_member_role(self.owner, analyst["user_id"], "viewer")["role"],
            "viewer",
        )
        self.assertTrue(self.store.remove_member(self.owner, analyst["user_id"])["removed"])
        self.assertEqual(len(self.store.list_members(self.owner)), 1)
        with self.assertRaises(PermissionError):
            self.store.authenticate(analyst_login["access_token"])

    def test_invitation_is_tenant_scoped_and_owner_only(self):
        other = self.principal("other@example.test", "Customer B")
        with self.assertRaises(PermissionError):
            self.store.create_invitation(other, "new@example.test")
        invitation = self.store.create_invitation(self.owner, "new@example.test")
        with self.assertRaises(ValueError):
            self.store.create_invitation(self.owner, "new@example.test")
        with self.assertRaises(PermissionError):
            self.store.accept_invitation("invalid-token-value-that-is-long-enough", "valid-password-123")

        with sqlite3.connect(self.store.path) as db:
            db.execute(
                "UPDATE invitations SET expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00Z", invitation["invitation_id"]),
            )
        with self.assertRaises(PermissionError):
            self.store.accept_invitation(
                invitation["invitation_token"], "another-correct-horse-password",
            )

    def test_notification_inbox_is_tenant_and_user_scoped(self):
        site = self.store.create_site(self.owner, "North site", "UTC")
        member_invite = self.store.create_invitation(
            self.owner, "viewer@example.test", role="viewer",
        )
        accepted = self.store.accept_invitation(
            member_invite["invitation_token"], "a-different-correct-password",
        )
        viewer_login = self.store.login(
            "viewer@example.test", "a-different-correct-password",
        )
        viewer = self.store.authenticate(viewer_login["access_token"])

        targeted = self.store.create_notification(
            self.owner, title="Review forecast", message="A new forecast is ready.",
            category="decision", severity="warning", site_id=site["id"],
            user_id=viewer["user_id"], payload={"run_id": "run-001"},
        )
        broadcast = self.store.create_notification(
            self.owner, title="System update", message="A new version is available.",
            category="system", severity="info",
        )
        self.assertEqual(
            [item["id"] for item in self.store.list_notifications(viewer)],
            [broadcast["id"], targeted["id"]],
        )
        self.assertEqual(
            [item["id"] for item in self.store.list_notifications(self.owner)],
            [broadcast["id"]],
        )
        self.store.mark_notification_read(viewer, targeted["id"])
        self.assertEqual(
            [item["id"] for item in self.store.list_notifications(viewer, unread_only=True)],
            [broadcast["id"]],
        )
        self.assertEqual(accepted["role"], "viewer")
        with self.assertRaises(PermissionError):
            self.store.create_notification(
                viewer, title="Not allowed", message="Viewer cannot create events.",
            )

    def test_notification_rejects_cross_tenant_targets_and_non_finite_payload(self):
        other = self.principal("second-owner@example.test", "Customer C")
        other_site = self.store.create_site(other, "Remote", "UTC")
        with self.assertRaises(LookupError):
            self.store.create_notification(
                self.owner, title="Wrong site", message="Must not cross tenants.",
                site_id=other_site["id"],
            )
        with self.assertRaises(ValueError):
            self.store.create_notification(
                self.owner, title="Bad payload", message="NaN is not JSON.",
                payload={"bad": float("nan")},
            )


if __name__ == "__main__":
    unittest.main()
