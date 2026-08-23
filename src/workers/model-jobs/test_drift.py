import unittest

from drift import delayed_label_coverage, numeric_mean_drift


class DriftTest(unittest.TestCase):
    def test_small_samples_never_claim_drift_safety(self):
        result = numeric_mean_drift("eta", (1, 2), (10, 20), reference_scale=2)
        self.assertEqual(result.severity, "INSUFFICIENT_DATA")

    def test_drift_thresholds_and_delayed_null_labels(self):
        result = numeric_mean_drift(
            "eta", range(20), range(20, 40), reference_scale=20,
            warning_threshold=0.25, critical_threshold=0.75,
        )
        self.assertEqual(result.severity, "CRITICAL")
        coverage = delayed_label_coverage(
            ("a", "b", "c"), {"a": 0, "b": None}, minimum_coverage=0.5,
        )
        self.assertEqual(coverage.observed_labels, 1)
        self.assertEqual(coverage.status, "LOW_COVERAGE")


if __name__ == "__main__":
    unittest.main()
