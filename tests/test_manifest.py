import unittest
from pathlib import Path

import yaml


class ManifestTests(unittest.TestCase):
    def test_author_and_name_match_across_manifest_provider_and_tools(self):
        manifest = yaml.safe_load(Path("manifest.yaml").read_text())
        provider = yaml.safe_load(Path("provider/photon.yaml").read_text())
        self.assertEqual(provider["identity"]["name"], manifest["name"])
        self.assertEqual(provider["identity"]["author"], manifest["author"])
        for path in provider["tools"]:
            with self.subTest(tool=path):
                self.assertEqual(
                    yaml.safe_load(Path(path).read_text())["identity"]["author"], manifest["author"]
                )
