import unittest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.admin.routes import _cost_month_data
from app.core.timezone import to_shanghai_date
from app.models.tables import JobCost, JobCostRevision, JobEvent, ProviderKey
from app.services import cost_accounting as costs


def source_log(request_id, task_id, quota, log_type=2):
    return {
        "request_id": request_id,
        "created_at": 1791878883,
        "type": log_type,
        "quota": quota,
        "model_name": "grok-imagine-video-1.5-preview",
        "other": '{"task_id":"' + task_id + '","usage_facts":{"seconds":15,"resolution":"720p"}}',
    }


class CostAccountingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (ProviderKey.__table__, JobEvent.__table__, JobCost.__table__, JobCostRevision.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        with self.Session() as db:
            db.add(ProviderKey(id=1, name="New API", provider_name="oaire_grok", key_masked="***", key_encrypted="dummy"))
            db.add(JobCost(
                id=1, source_job_id=101, source_user_id=7, username="test-user", provider_key_id=1,
                api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id="task-101",
                model="grok-imagine-video-1.5-preview", seconds=15, resolution="720p", state="pending",
                next_check_at=datetime.now(UTC),
            ))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def reconcile(self, status, current_logs):
        _net, matched = costs.matching_billing_logs(current_logs, "task-101")
        snapshot = (status, {"completed_at": int(datetime.now(UTC).timestamp())}, _net, 500000, matched)
        with (
            patch.object(costs, "SessionLocal", self.Session),
            patch.object(costs, "decrypt_secret", return_value="test-key"),
            patch.object(costs, "get_proxy_url", return_value=""),
            patch.object(costs, "_fetch_snapshot", return_value=snapshot),
        ):
            costs.reconcile_job_cost(101)

    def test_exact_task_id_and_refund(self):
        logs = [source_log("a", "task-101", 1950000), source_log("b", "task-other", 500000), source_log("c", "task-101", 225000, 6)]
        net, matched = costs.matching_billing_logs(logs, "task-101")
        self.assertEqual(net, 1725000)
        self.assertEqual(len(matched), 2)
        self.assertEqual(matched[0]["usage_facts"], {"seconds": 15, "resolution": "720p"})

    def test_precharge_survives_recent_log_window_and_revisions_are_idempotent(self):
        charge = source_log("a", "task-101", 1950000)
        self.reconcile("processing", [charge])
        with self.Session() as db:
            row = db.query(JobCost).one()
            self.assertEqual(row.state, "pending")
            self.assertIsNone(row.amount)
            self.assertEqual(len(row.source_logs), 1)

        self.reconcile("completed", [])
        self.reconcile("completed", [charge])
        with self.Session() as db:
            row = db.query(JobCost).one()
            self.assertEqual(row.amount, Decimal("3.900000"))
            self.assertEqual(row.usage_date, to_shanghai_date(datetime.now(UTC)))
            self.assertEqual(db.query(JobCostRevision).count(), 1)
            report = _cost_month_data(db, row.usage_date.year, row.usage_date.month)
            self.assertEqual(report["total"], "3.90")
            self.assertEqual(report["count"], 1)

        self.reconcile("completed", [charge, source_log("refund", "task-101", 225000, 6)])
        with self.Session() as db:
            row = db.query(JobCost).one()
            self.assertEqual(row.amount, Decimal("3.450000"))
            self.assertEqual(row.net_quota, 1725000)
            self.assertEqual(db.query(JobCostRevision).count(), 2)

    def test_failed_video_is_excluded_even_if_precharged(self):
        self.reconcile("failed", [source_log("a", "task-101", 1950000)])
        with self.Session() as db:
            row = db.query(JobCost).one()
            self.assertEqual(row.state, "excluded")
            self.assertIsNone(row.amount)
            self.assertIsNone(row.next_check_at)
            self.assertEqual(_cost_month_data(db, 2026, 10)["total"], "0.00")

    def test_daily_report_sums_historical_amounts_after_price_change(self):
        usage_date = to_shanghai_date(datetime.now(UTC))
        with self.Session() as db:
            first = db.query(JobCost).one()
            first.state = "settled"
            first.amount = Decimal("1.200000")
            first.usage_date = usage_date
            db.add(JobCost(
                id=2, source_job_id=102, source_user_id=7, username="test-user", provider_key_id=1,
                api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id="task-102",
                model="grok-imagine-video", seconds=10, resolution="720p", state="settled",
                amount=Decimal("0.800000"), usage_date=usage_date,
            ))
            db.commit()
            report = _cost_month_data(db, usage_date.year, usage_date.month)
            self.assertEqual(report["total"], "2.00")
            self.assertEqual(report["count"], 2)
            self.assertEqual(report["rows"][0]["monthly_amount"], "2.00")


if __name__ == "__main__":
    unittest.main()
