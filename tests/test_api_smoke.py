import unittest

from server import app, CHAINS_CONFIG


class ApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("status"), "ok")

    def test_chains_endpoint(self):
        resp = self.client.get("/chains")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("total"), len(CHAINS_CONFIG))
        self.assertEqual(len(data.get("chains", [])), len(CHAINS_CONFIG))

    def test_all_analyze_endpoints_return_success(self):
        for chain_name in CHAINS_CONFIG:
            with self.subTest(chain=chain_name):
                resp = self.client.get(f"/analyze/{chain_name}")
                self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
                data = resp.get_json()
                self.assertEqual(data.get("chain"), chain_name)

    def test_composite_response_schema(self):
        composite_chains = [
            name for name, cfg in CHAINS_CONFIG.items()
            if cfg.get("category") == "composite"
        ]
        self.assertTrue(composite_chains)
        expected_keys = {
            "chain",
            "description",
            "active_signals",
            "signal_count",
            "aggregated_signal",
            "all_results",
            "all_sub_chains_failed",
            "error",
            "timestamp",
        }
        for chain_name in composite_chains:
            with self.subTest(chain=chain_name):
                resp = self.client.get(f"/analyze/{chain_name}")
                self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
                data = resp.get_json()
                self.assertTrue(expected_keys.issubset(data.keys()))
                self.assertIsInstance(data["active_signals"], list)
                self.assertIsInstance(data["all_results"], dict)


if __name__ == "__main__":
    unittest.main()
