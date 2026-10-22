import unittest
from pathlib import Path

import yaml


class ManifestTests(unittest.TestCase):
    def test_author_and_name_match_across_manifest_provider_and_events(self):
        manifest = yaml.safe_load(Path("manifest.yaml").read_text())
        provider = yaml.safe_load(Path("provider/photon_trigger.yaml").read_text())
        self.assertEqual(provider["identity"]["name"], manifest["name"])
        self.assertEqual(provider["identity"]["author"], manifest["author"])
        for path in provider["events"]:
            with self.subTest(event=path):
                self.assertEqual(
                    yaml.safe_load(Path(path).read_text())["identity"]["author"], manifest["author"]
                )
