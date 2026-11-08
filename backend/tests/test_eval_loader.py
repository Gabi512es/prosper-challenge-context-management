import json
import tempfile
import unittest
from pathlib import Path

from evals import CatalogBlobMismatchError, load_dev_scenarios


BACKEND_DIR = Path(__file__).parents[1]
SCENARIOS_PATH = BACKEND_DIR / "evals" / "dev_scenarios.json"
CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"


class DevScenarioLoaderTest(unittest.TestCase):
    def test_loads_only_pinned_development_cases(self):
        data = load_dev_scenarios(SCENARIOS_PATH, CATALOG_PATH)

        self.assertEqual(data["dataset_role"], "development_only")
        self.assertEqual(len(data["scenarios"]), 12)
        self.assertEqual(
            [item["id"] for item in data["scenarios"][-3:]],
            ["DEV-010", "DEV-011", "DEV-012"],
        )

    def test_fails_loudly_when_catalog_blob_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            changed_catalog = Path(directory) / "catalog.json"
            catalog = json.loads(CATALOG_PATH.read_text())
            catalog["policies"].append("This changes the pinned blob.")
            changed_catalog.write_text(json.dumps(catalog))

            with self.assertRaises(CatalogBlobMismatchError):
                load_dev_scenarios(SCENARIOS_PATH, changed_catalog)
