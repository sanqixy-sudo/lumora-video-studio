import unittest
from types import SimpleNamespace
from app.api.admin.routes import _month_nav
from scripts.preview_usage import build_usage_preview

class UsageCalendarTests(unittest.TestCase):
    def test_actual_calendar_lengths(self):
        for year,month,days in [(2026,1,31),(2026,4,30),(2026,2,28),(2024,2,29),(1900,2,28),(2000,2,29)]:
            with self.subTest(year=year,month=month):
                self.assertEqual(_month_nav(year,month)['days'],list(range(1,days+1)))

    def test_cross_year_navigation(self):
        self.assertEqual(_month_nav(2026,1)['prev_month'],'2025-12')
        self.assertEqual(_month_nav(2026,12)['next_month'],'2027-01')

    def test_preview_days_and_aggregates_match_selected_month(self):
        for month in ['2026-01','2026-04','2026-02','2024-02']:
            year,number=map(int,month.split('-'))
            report=build_usage_preview(SimpleNamespace(),month)
            self.assertEqual(report['days'],_month_nav(year,number)['days'])
            self.assertEqual(len(report['daily_totals']),len(report['days']))
            self.assertEqual(report['display_total'],sum(d['display'] for d in report['daily_totals']))
            for row in report['rows']:
                self.assertEqual(len(row.daily),len(report['days']))
                self.assertEqual(row.daily[-1]['date'],f"{month}-{report['days'][-1]:02d}")
