"""Executable fail-closed checks for the deployed legacy contract guard."""

import copy
import hashlib
import json
import unittest
from pathlib import Path
from check_legacy import canonical_bytes, check_legacy


FIXTURE = Path(__file__).parents[2] / "src/api/tests/mcp_integration/fixtures/legacy-canary-20261004.json"


def sign(snapshot):
    snapshot["contract_sha256"] = hashlib.sha256(canonical_bytes(snapshot["contract"])).hexdigest()
    return snapshot


class LegacyContractTest(unittest.TestCase):
    def test_captured_artifacts_match_provenance_manifest(self):
        manifest = json.loads(FIXTURE.with_name("legacy-canary-20261004-manifest.json").read_text())
        for filename, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256(FIXTURE.with_name(filename).read_bytes()).hexdigest(), digest)

    def setUp(self):
        self.baseline = json.loads(FIXTURE.read_text())
        self.current = copy.deepcopy(self.baseline)

    def test_baseline_integrity_and_additive_tools(self):
        self.assertEqual(check_legacy(self.baseline, self.current), [])
        tool = copy.deepcopy(self.current["contract"]["tools"][0])
        tool["name"] = "vnext_additive_tool"
        self.current["contract"]["tools"].append(tool)
        self.assertEqual(check_legacy(self.baseline, sign(self.current)), [])

    def test_removed_tool_or_changed_schema_fails(self):
        self.current["contract"]["tools"].pop()
        self.assertTrue(any("removed legacy tool" in item for item in check_legacy(self.baseline, sign(self.current))))
        self.current = copy.deepcopy(self.baseline)
        self.current["contract"]["tools"][0]["input_schema"] = {"type": "null"}
        self.assertTrue(any("input_schema" in item for item in check_legacy(self.baseline, sign(self.current))))

    def test_group_owner_activation_and_grants_cannot_drift(self):
        for field, value in (("owner", "other-owner"), ("active", False), ("tools", [])):
            self.current = copy.deepcopy(self.baseline)
            group = next(group for group in self.current["contract"]["tool_groups"] if group["active"])
            group[field] = value
            self.assertTrue(any("tool group" in item for item in check_legacy(self.baseline, sign(self.current))))

    def test_corruption_duplicates_and_registry_mismatch_fail(self):
        self.current["contract_sha256"] = "invalid"
        self.assertTrue(any("digest" in item for item in check_legacy(self.baseline, self.current)))
        self.current = copy.deepcopy(self.baseline)
        self.current["contract"]["tools"].append(self.current["contract"]["tools"][0])
        self.current["contract"]["registered_runtime_mismatches"] = ["hidden_tool"]
        errors = check_legacy(self.baseline, sign(self.current))
        self.assertTrue(any("duplicate" in item for item in errors))
        self.assertTrue(any("registry/runtime" in item for item in errors))
        self.current = copy.deepcopy(self.baseline)
        self.current["contract"]["tool_groups"].append(self.current["contract"]["tool_groups"][0])
        self.assertTrue(any("duplicate tool group" in item for item in check_legacy(self.baseline, sign(self.current))))


if __name__ == "__main__":
    unittest.main()
