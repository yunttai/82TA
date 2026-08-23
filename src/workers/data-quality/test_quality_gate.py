from datetime import datetime, timedelta, timezone
import unittest

from quality_gate import QualityObservation, QualityPolicy, evaluate_quality


UTC = timezone.utc


class QualityGateTest(unittest.TestCase):
    def row(self, row_id, sequence, *, eta=True, seat=True, lag=1, minute=None):
        observed = datetime(2026, 8, 23, 1, sequence if minute is None else minute, tzinfo=UTC)
        return QualityObservation(
            row_id, "trip", sequence, observed, observed, observed + timedelta(seconds=lag), eta, seat,
        )

    def test_pass_report_is_training_eligible(self):
        report = evaluate_quality((self.row("a", 1), self.row("b", 2)))
        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.training_eligible)

    def test_low_coverage_lag_duplicates_and_sequence_regression_fail_period(self):
        rows = (
            self.row("same", 2, eta=False, seat=False, lag=400, minute=1),
            self.row("same", 1, eta=False, seat=False, minute=2),
        )
        report = evaluate_quality(rows, QualityPolicy())
        self.assertFalse(report.training_eligible)
        self.assertEqual(
            set(report.violations),
            {"DUPLICATE_RATE", "ETA_LABEL_LOW_COVERAGE", "SEAT_LABEL_LOW_COVERAGE", "INGESTION_LAG", "STATION_SEQUENCE_REGRESSION"},
        )


if __name__ == "__main__":
    unittest.main()
