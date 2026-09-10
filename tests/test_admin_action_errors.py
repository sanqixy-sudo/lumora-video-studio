import unittest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.admin.routes import router, _parse_optional_int, _parse_positive_int, delete_user_form
from app.deps import get_db, require_super_admin
from app.models.tables import User, QuotaWallet, RiskControlRule, ReferenceImagePreset, QuotaPlan, UserQuotaPlanAssignment, ProviderKey


class AdminActionErrorTests(unittest.TestCase):
    def setUp(self):
        self.admin = User(id=1, username="test_admin", role="admin", status="active")
        self.db = MagicMock()
        self.queries = {}
        def query(*models):
            return self.queries.setdefault(models, MagicMock())
        self.db.query.side_effect = query
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[require_super_admin] = lambda: self.admin
        self.client = TestClient(app)

    def row(self, model, value):
        self.db.query(model).filter.return_value.first.return_value = value

    def test_insufficient_quota_returns_actionable_400_on_both_endpoints(self):
        self.row(User, User(id=7, username="test_user"))
        wallet = QuotaWallet(remaining_quota=3, reserved_quota=2)
        self.db.query(QuotaWallet).filter.return_value.with_for_update.return_value.first.return_value = wallet
        for suffix in ["", "/form"]:
            kwargs = {"data" if suffix else "json": {"amount": 2}}
            response = self.client.post("/admin/users/7/deduct-quota" + suffix, **kwargs)
            self.assertEqual(response.status_code, 400)
            self.assertIn("可用额度不足", response.json()["detail"])
        self.assertEqual(wallet.remaining_quota, 3)
        self.db.commit.assert_not_called()

    def test_quota_forms_reject_nonpositive_amounts_before_write(self):
        for action in ["grant-quota", "deduct-quota"]:
            for amount in [0, -1]:
                response = self.client.post(f"/admin/users/7/{action}/form", data={"amount": amount})
                self.assertEqual(response.status_code, 422)
        self.db.commit.assert_not_called()
        self.db.add.assert_not_called()

    def test_invalid_custom_quota_returns_400_not_500(self):
        self.db.query(UserQuotaPlanAssignment, QuotaPlan).join.return_value.filter.return_value.first.return_value = (UserQuotaPlanAssignment(id=2), QuotaPlan(id=3))
        for amount in ["abc", "1.5", "-1", "999999999999999999999"]:
            response = self.client.post("/admin/users/7/quota-plans/2/custom/form", data={"custom_quota_amount": amount})
            self.assertEqual(response.status_code, 400)
        self.db.commit.assert_not_called()

    def test_valid_custom_quota_keeps_zero_and_reset_semantics(self):
        self.assertEqual(_parse_optional_int("0"), 0)
        self.assertEqual(_parse_optional_int(0), 0)
        self.assertIsNone(_parse_optional_int(""))
        self.assertEqual(_parse_positive_int("", 100), 100)
        self.assertEqual(_parse_positive_int("7", 100), 7)

    def test_bad_key_limits_do_not_silently_save_default(self):
        self.row(ProviderKey, ProviderKey(id=2, provider_name="sora_api", status="active"))
        for field, value in [("weight", "abc"), ("daily_limit", "abc"), ("concurrent_limit", "-1")]:
            data = {"name": "test_key", field: value}
            response = self.client.post("/admin/provider-keys/2/update/form", data=data)
            self.assertEqual(response.status_code, 400)
        self.db.commit.assert_not_called()

    def test_toggle_actions_return_redirect_and_commit_real_model_changes(self):
        for model, path in [(RiskControlRule, "risk-control/3/toggle"), (ReferenceImagePreset, "reference-images/3/toggle"), (QuotaPlan, "quota-plans/3/toggle"), (ProviderKey, "provider-keys/3/toggle-status"), (User, "users/3/toggle-status")]:
            row = model(id=3, status="disabled")
            if model is ProviderKey:
                row.provider_name = "sora_api"
            self.row(model, row)
            before = self.db.commit.call_count
            response = self.client.post(f"/admin/{path}/form", follow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(row.status, "active", path)
            self.assertEqual(self.db.commit.call_count, before + 1)

    def test_showcase_and_report_flags_really_toggle(self):
        user = User(id=7, showcase_enabled=True, hidden_from_subadmin_reports=False)
        self.row(User, user)
        response = self.client.post("/admin/users/7/toggle-showcase/form", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertFalse(user.showcase_enabled)
        self.assertIn("notice=showcase_off", response.headers["location"])
        response = self.client.post("/admin/users/7/toggle-report-hidden/form", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(user.hidden_from_subadmin_reports)

    def test_delete_user_detaches_risk_rule_operator(self):
        self.row(User, User(id=7, username="test_user", role="user"))
        self.db.query.return_value = MagicMock()
        for q in self.queries.values():
            q.filter.return_value.all.return_value = []
        with patch("app.api.admin.routes._delete_job"):
            response = delete_user_form(7, "test_user", self.admin, self.db)
        self.assertEqual(response.status_code, 303)
        self.db.query(RiskControlRule).filter.return_value.update.assert_called_once_with({RiskControlRule.operator_user_id: None}, synchronize_session=False)
