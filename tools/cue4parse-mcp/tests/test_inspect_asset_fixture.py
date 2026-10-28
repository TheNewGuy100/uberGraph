"""Offline integrity/shape regression test for the captured inspect_asset response."""

import hashlib
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPOSITORY_ROOT / "analysis" / "fixtures" / "BP_Inventory_PlayerBox"
MANIFEST_PATH = FIXTURE_DIR / "BP_Inventory_PlayerBox.manifest.json"


class InspectAssetFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.raw_path = FIXTURE_DIR / cls.manifest["fixtureFile"]
        cls.raw_bytes = cls.raw_path.read_bytes()
        cls.response = json.loads(cls.raw_bytes)

    def test_raw_bytes_match_manifest_hash_and_length(self):
        self.assertEqual(len(self.raw_bytes), self.manifest["response"]["byteLength"])
        self.assertEqual(
            hashlib.sha256(self.raw_bytes).hexdigest(),
            self.manifest["response"]["sha256"],
        )

    def test_package_identity_and_export_counts_match(self):
        package = self.manifest["package"]
        self.assertEqual(self.response["path"], package["packagePath"])
        self.assertEqual(self.response["package"]["packageName"], package["packageName"])
        self.assertEqual(self.response["package"]["packageExportCount"], package["packageExportCount"])
        self.assertEqual(self.response["package"]["packageImportCount"], package["packageImportCount"])
        self.assertEqual(self.response["exportsAttempted"], self.response["exportsReturned"])
        self.assertEqual(len(self.response["properties"]), self.response["exportsReturned"])
        self.assertEqual(self.response["exportsReturned"], self.manifest["response"]["exportsReturned"])

    def test_partial_coverage_is_preserved_not_promoted_to_complete(self):
        coverage = self.manifest["coverage"]
        self.assertEqual(self.response["status"], "partially_parsed")
        self.assertTrue(self.response["exportsTruncated"])
        self.assertFalse(coverage["allPackageExportsAnalyzed"])
        self.assertEqual(
            self.response["package"]["packageExportCount"] - self.response["exportsAttempted"],
            coverage["exportsNotAttempted"],
        )
        self.assertFalse(coverage["importMapEntriesEnumerated"])
        self.assertFalse(coverage["propertyReferencesAreExhaustive"])

    def test_parse_errors_and_property_caps_match_capture(self):
        response = self.response
        self.assertEqual(len(response["failedExports"]), self.manifest["response"]["failedExports"])
        self.assertEqual(len(response["propertyErrors"]), self.manifest["response"]["propertyErrors"])
        truncated = sum(bool(export["propertiesTruncated"]) for export in response["properties"])
        self.assertEqual(truncated, self.manifest["response"]["exportsWithPropertyLimitTruncation"])
        self.assertEqual(len(response["references"]), self.manifest["response"]["propertyReferencesReturned"])


if __name__ == "__main__":
    unittest.main()
