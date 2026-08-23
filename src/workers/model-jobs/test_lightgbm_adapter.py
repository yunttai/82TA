import unittest

from lightgbm_adapter import LightGbmUnavailable, capability, train_to_native_text


class LightGbmAdapterTest(unittest.TestCase):
    def test_dependency_presence_never_claims_production_ready(self):
        state = capability(training_enabled=False)
        self.assertFalse(state.training_enabled)
        self.assertFalse(state.production_ready)

    def test_training_is_explicitly_disabled_without_data_or_opt_in(self):
        with self.assertRaises(LightGbmUnavailable):
            train_to_native_text(
                rows=(), labels=(), feature_names=("x",), output_path=__import__("pathlib").Path("model.txt"),
                parameters={}, training_enabled=False,
            )


if __name__ == "__main__":
    unittest.main()
