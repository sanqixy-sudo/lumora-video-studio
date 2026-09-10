import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.api.admin.routes import toggle_reference_image_form, toggle_risk_rule_form
from app.models.tables import AuditLog, ReferenceImagePreset, RiskControlRule


class AdminRuleToggleTests(unittest.TestCase):
    def test_rules_and_presets_toggle_without_provider_fields(self):
        for handler, model, action in [
            (toggle_risk_rule_form, RiskControlRule, "toggle_risk_rule"),
            (toggle_reference_image_form, ReferenceImagePreset, "update_reference_image_preset"),
        ]:
            for before, after in [("disabled", "active"), ("active", "disabled")]:
                with self.subTest(model=model.__name__, before=before):
                    row = model(id=3, status=before)
                    db = MagicMock()
                    db.query.return_value.filter.return_value.first.return_value = row
                    response = handler(3, SimpleNamespace(id=1), db)
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(row.status, after)
                    db.commit.assert_called_once()
                    audits = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AuditLog)]
                    self.assertEqual(len(audits), 1)
                    self.assertEqual(audits[0].action, action)
                    self.assertEqual(audits[0].detail_json["status"], after)
                    if isinstance(row, RiskControlRule):
                        self.assertEqual(row.operator_user_id, 1)

    def test_missing_record_does_not_write(self):
        for handler in [toggle_reference_image_form, toggle_risk_rule_form]:
            with self.subTest(handler=handler.__name__):
                db = MagicMock()
                db.query.return_value.filter.return_value.first.return_value = None
                with self.assertRaises(HTTPException) as error:
                    handler(999, SimpleNamespace(id=1), db)
                self.assertEqual(error.exception.status_code, 404)
                db.commit.assert_not_called()
                db.add.assert_not_called()
