import importlib
import unittest
from pathlib import Path

import yaml

from core.data_bus import DataBus
from core.factor_runner import collect_factor_modules
from core.factor_registry import FactorRegistry

ROOT = Path(__file__).resolve().parents[1]


def load_chains():
    with open(ROOT / "config" / "chains.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["chains"]


class ChainIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chains = load_chains()

    def test_collect_factor_modules_from_chains_config(self):
        modules = collect_factor_modules(self.chains)
        self.assertTrue(modules)
        self.assertEqual(len(modules), len(set(modules)))
        configured_modules = {
            cfg["factor_module"]
            for cfg in self.chains.values()
            if cfg.get("factor_module")
        }
        self.assertEqual(set(modules), configured_modules)

    def test_all_factor_modules_import_and_classes_exist(self):
        for chain_name, cfg in self.chains.items():
            if cfg.get("category") == "composite":
                continue
            with self.subTest(chain=chain_name):
                module = importlib.import_module(cfg["factor_module"])
                self.assertTrue(hasattr(module, cfg["factor_class"]))

    def test_all_non_composite_chains_instantiate(self):
        for chain_name, cfg in self.chains.items():
            if cfg.get("category") == "composite":
                continue
            with self.subTest(chain=chain_name):
                DataBus.reset()
                module = importlib.import_module(cfg["factor_module"])
                cls = getattr(module, cfg["factor_class"])
                kwargs = {"data_dir": str(ROOT / "data")}
                for key in ("symbol", "far_symbol"):
                    if key in cfg:
                        kwargs[key] = cfg[key]
                instance = cls(**kwargs)
                self.assertIsNotNone(instance)

    def test_composite_sub_chains_exist(self):
        for chain_name, cfg in self.chains.items():
            if cfg.get("category") != "composite":
                continue
            with self.subTest(chain=chain_name):
                self.assertTrue(cfg.get("sub_chains"))
                for sub_chain in cfg["sub_chains"]:
                    self.assertIn(sub_chain, self.chains)
                    self.assertNotEqual(self.chains[sub_chain].get("category"), "composite")

    def test_registry_populated_by_configured_modules(self):
        for module_name in collect_factor_modules(self.chains):
            importlib.import_module(module_name)
        FactorRegistry.sync_from_chains(self.chains)
        registered = FactorRegistry.list_all()
        self.assertGreaterEqual(len(registered), 1)

    def test_registry_metadata_matches_chains_after_sync(self):
        for module_name in collect_factor_modules(self.chains):
            importlib.import_module(module_name)
        FactorRegistry.sync_from_chains(self.chains)
        for chain_name, cfg in self.chains.items():
            if cfg.get("category") == "composite":
                continue
            info = FactorRegistry.info(chain_name)
            self.assertIsNotNone(info)
            self.assertEqual(info["category"], cfg.get("category", ""))
            self.assertEqual(info["description"], cfg.get("description", ""))
            self.assertEqual(info["asset"], cfg.get("asset", ""))
            self.assertEqual(info["data_deps"], cfg.get("data_deps", []))


if __name__ == "__main__":
    unittest.main()
