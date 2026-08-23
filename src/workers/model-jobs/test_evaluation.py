import unittest

from evaluation import (
    EtaPrediction,
    IsotonicCalibrator,
    PlattCalibrator,
    conformal_absolute_radius,
    conformal_interval,
    evaluate_eta,
    evaluate_seat,
    evaluate_slices,
    quantile_interval,
)


class EvaluationTest(unittest.TestCase):
    def test_eta_metrics_and_interval_coverage(self):
        metrics = evaluate_eta((
            EtaPrediction(100, 90, 80, 110),
            EtaPrediction(200, 230, 210, 250),
            EtaPrediction(300, 300, 280, 320),
        ))
        self.assertEqual(metrics.count, 3)
        self.assertAlmostEqual(metrics.mae_seconds, 40 / 3)
        self.assertEqual(metrics.median_absolute_error_seconds, 10)
        self.assertEqual(metrics.p90_absolute_error_seconds, 30)
        self.assertAlmostEqual(metrics.interval_coverage, 2 / 3)

    def test_conformal_radius_uses_finite_sample_quantile(self):
        radius = conformal_absolute_radius((10, 20, 30, 40), (9, 18, 27, 36), coverage=0.75)
        self.assertEqual(radius, 4)
        self.assertEqual(conformal_interval(2, radius), (0.0, 6))
        self.assertEqual(quantile_interval(10, 20, 30), (10, 20, 30))
        with self.assertRaises(ValueError):
            quantile_interval(30, 20, 10)

    def test_seat_metrics_include_pr_auc_brier_ece_and_reliability(self):
        metrics = evaluate_seat(
            (True, False, True, False), (0.9, 0.8, 0.7, 0.1), bins=2,
        )
        self.assertEqual(metrics.count, 4)
        self.assertEqual(metrics.positives, 2)
        self.assertAlmostEqual(metrics.pr_auc, (1 + 2 / 3) / 2)
        self.assertAlmostEqual(metrics.brier_score, (0.01 + 0.64 + 0.09 + 0.01) / 4)
        self.assertEqual(len(metrics.reliability), 2)
        self.assertTrue(0 <= metrics.ece <= 1)

    def test_platt_and_isotonic_interfaces_preserve_probability_bounds(self):
        platt = PlattCalibrator(1.0, 0.0)
        self.assertAlmostEqual(platt.transform(0.2), 0.2)
        isotonic = IsotonicCalibrator((0.2, 0.5, 1.0), (0.1, 0.4, 0.9))
        self.assertEqual(isotonic.transform(0.3), 0.4)
        self.assertEqual(isotonic.transform(0.2), 0.1)
        self.assertEqual(isotonic.transform(0.5), 0.4)
        with self.assertRaises(ValueError):
            IsotonicCalibrator(
                tuple(index / 1025 for index in range(1025)),
                tuple(index / 1025 for index in range(1025)),
            )

    def test_slice_metrics_are_deterministic_and_minimum_counted(self):
        rows = (("route-b", 1), ("route-a", 2), ("route-a", 4))
        slices = evaluate_slices(
            rows, key=lambda item: item[0], evaluator=lambda items: sum(item[1] for item in items),
            minimum_count=2,
        )
        self.assertEqual(tuple(item.slice_key for item in slices), ("route-a",))
        self.assertEqual(slices[0].metrics, 6)


if __name__ == "__main__":
    unittest.main()
