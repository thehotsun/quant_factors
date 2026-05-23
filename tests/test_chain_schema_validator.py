"""Tests for scripts/validate_chain_schema.py."""
import unittest
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_chain_schema.py"


class ValidatorTest(unittest.TestCase):
    def test_validator_passes_on_current_chains(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, f"Validator failed:\n{result.stdout}\n{result.stderr}")
        self.assertIn("errors: 0", result.stdout)

    def test_validator_rejects_invalid_driver_group(self):
        import tempfile, yaml
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({"chains": {
                "bad": {
                    "category": "mixed",
                    "factor_module": "x",
                    "factor_class": "Y",
                    "drivers": {"invalid_group": ["dep1"]},
                    "data_deps": ["dep1"],
                }
            }}, f)
            tmp_path = f.name

        from scripts.validate_chain_schema import validate_chain
        chains = {
            "bad": {
                "category": "mixed",
                "factor_module": "x",
                "factor_class": "Y",
                "drivers": {"invalid_group": ["dep1"]},
                "data_deps": ["dep1"],
            }
        }
        errors, warnings = validate_chain("bad", chains["bad"])
        self.assertTrue(any("invalid driver group" in e for e in errors))

    def test_validator_rejects_invalid_trade_asset_type(self):
        from scripts.validate_chain_schema import validate_chain
        errors, _ = validate_chain("bad", {
            "category": "mixed",
            "factor_module": "x",
            "factor_class": "Y",
            "trade_asset_type": "crypto",
            "data_deps": ["dep1"],
        })
        self.assertTrue(any("invalid trade_asset_type" in e for e in errors))

    def test_validator_warns_on_driver_data_deps_inconsistency(self):
        from scripts.validate_chain_schema import validate_chain
        _, warnings = validate_chain("warn", {
            "category": "mixed",
            "factor_module": "x",
            "factor_class": "Y",
            "drivers": {"futures": ["f1"], "spot": ["s1"]},
            "data_deps": ["f1"],
        })
        self.assertTrue(any("s1" in w for w in warnings))

    def test_validator_rejects_composite_without_subchains(self):
        from scripts.validate_chain_schema import validate_chain
        errors, _ = validate_chain("bad_comp", {
            "category": "composite",
        })
        self.assertTrue(any("no sub_chains" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
