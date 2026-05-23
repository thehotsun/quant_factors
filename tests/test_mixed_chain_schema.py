import unittest

from core.chain_config import build_chain_definitions
from core.price_schema import collect_price_dependencies


class MixedChainSchemaTest(unittest.TestCase):
    def test_chain_definition_preserves_trade_asset_and_driver_groups(self):
        chains = {
            "mixed": {
                "category": "cross",
                "asset": "legacy asset",
                "trade_asset": "养殖ETF(159865)",
                "drivers": {
                    "spot": ["pork_spot"],
                    "futures": ["pork_futures"],
                    "equity": ["breeding_etf"],
                },
                "data_deps": ["pork_futures"],
            }
        }
        d = build_chain_definitions(chains)["mixed"]
        self.assertEqual(d.trade_asset, "养殖ETF(159865)")
        self.assertEqual(d.drivers["spot"], ["pork_spot"])
        self.assertEqual(d.drivers["futures"], ["pork_futures"])
        self.assertEqual(d.drivers["equity"], ["breeding_etf"])

    def test_driver_dependencies_are_audited_as_price_dependencies(self):
        chains = {
            "mixed": {
                "drivers": {
                    "spot": ["chicken_spot"],
                    "futures": ["pork_futures"],
                    "equity": ["breeding_etf"],
                },
                "data_deps": [],
            }
        }
        self.assertEqual(collect_price_dependencies(chains), ["breeding_etf", "chicken_spot", "pork_futures"])


if __name__ == "__main__":
    unittest.main()
