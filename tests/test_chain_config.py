"""Tests for core.chain_config unified chain definitions."""
import unittest
from core.chain_config import (
    ChainDefinition, build_chain_definitions, check_metadata_consistency, MetadataDiff,
)
from core.factor_registry import FactorRegistry


class ChainDefinitionTest(unittest.TestCase):
    def test_basic_construction(self):
        d = ChainDefinition(name="test", category="meat", asset="ETF", data_deps=("pork_futures",))
        self.assertEqual(d.name, "test")
        self.assertFalse(d.is_composite)
        self.assertFalse(d.has_factor)
        self.assertEqual(d.trade_asset, "")
        self.assertEqual(d.trade_asset_type, "")
        self.assertEqual(d.execution_asset, "")
        self.assertEqual(d.signal_target, "")
        self.assertEqual(d.drivers, {})

    def test_composite_detection(self):
        d = ChainDefinition(name="full", category="composite", sub_chains=("a", "b"))
        self.assertTrue(d.is_composite)

    def test_has_factor(self):
        d = ChainDefinition(name="x", factor_module="factors.meat.pork", factor_class="PorkFactor")
        self.assertTrue(d.has_factor)

    def test_immutable(self):
        d = ChainDefinition(name="x")
        with self.assertRaises(AttributeError):
            d.name = "y"


class BuildChainDefinitionsTest(unittest.TestCase):
    def test_builds_from_yaml(self):
        chains = {
            "pork_etf": {
                "category": "meat",
                "description": "desc",
                "asset": "ETF",
                "trade_asset": "养殖ETF(159865)",
                "trade_asset_type": "etf",
                "execution_asset": "159865",
                "signal_target": "breeding_profit",
                "data_deps": ["pork_futures"],
                "drivers": {"futures": ["pork_futures"], "spot": ["pork_spot"]},
                "factor_module": "factors.meat.pork",
                "factor_class": "PorkFactor",
            }
        }
        defs = build_chain_definitions(chains)
        self.assertIn("pork_etf", defs)
        d = defs["pork_etf"]
        self.assertEqual(d.category, "meat")
        self.assertEqual(d.data_deps, ("pork_futures",))
        self.assertEqual(d.trade_asset, "养殖ETF(159865)")
        self.assertEqual(d.trade_asset_type, "etf")
        self.assertEqual(d.execution_asset, "159865")
        self.assertEqual(d.signal_target, "breeding_profit")
        self.assertEqual(d.drivers["futures"], ["pork_futures"])
        self.assertTrue(d.has_factor)

    def test_registry_fills_missing_metadata(self):
        chains = {
            "x": {"factor_module": "m", "factor_class": "C"},
        }
        reg = {"name": "x", "category": "cross", "description": "from_reg", "asset": "A", "data_deps": ["d1"]}
        defs = build_chain_definitions(chains, registry_info_fn=lambda n: reg if n == "x" else None)
        d = defs["x"]
        self.assertEqual(d.category, "cross")
        self.assertEqual(d.description, "from_reg")
        self.assertEqual(d.data_deps, ("d1",))

    def test_yaml_overrides_registry_for_runtime_fields(self):
        chains = {
            "x": {
                "category": "yaml_cat",
                "factor_module": "yaml_mod",
                "symbol": "SYM",
            }
        }
        reg = {"name": "x", "category": "reg_cat", "factor_module": "reg_mod"}
        defs = build_chain_definitions(chains, registry_info_fn=lambda n: reg if n == "x" else None)
        d = defs["x"]
        self.assertEqual(d.category, "yaml_cat")
        self.assertEqual(d.factor_module, "yaml_mod")
        self.assertEqual(d.symbol, "SYM")


class MetadataConsistencyTest(unittest.TestCase):
    def test_no_diff_when_aligned(self):
        chains = {"a": {"category": "meat", "description": "d", "asset": "A", "data_deps": ["x"]}}
        reg = {"name": "a", "category": "meat", "description": "d", "asset": "A", "data_deps": ["x"]}
        diffs = check_metadata_consistency(chains, lambda n: reg if n == "a" else None)
        self.assertEqual(diffs, [])

    def test_detects_drift(self):
        chains = {"a": {"category": "meat", "description": "yaml_desc", "data_deps": ["x"]}}
        reg = {"name": "a", "category": "cross", "description": "reg_desc", "data_deps": ["y"]}
        diffs = check_metadata_consistency(chains, lambda n: reg if n == "a" else None)
        self.assertEqual(len(diffs), 3)
        fields = {d.field for d in diffs}
        self.assertEqual(fields, {"category", "description", "data_deps"})

    def test_skips_unknown_chain(self):
        chains = {"a": {"category": "meat"}}
        diffs = check_metadata_consistency(chains, lambda n: None)
        self.assertEqual(diffs, [])


if __name__ == "__main__":
    unittest.main()
