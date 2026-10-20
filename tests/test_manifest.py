import tomllib
import unittest
from pathlib import Path

import yaml


class ManifestVersionTests(unittest.TestCase):
    def test_manifest_versions_match_project_version(self):
        manifest = yaml.safe_load(Path("manifest.yaml").read_text())
        source_project = Path(__file__).resolve().parents[1] / "pyproject.toml"
        version = tomllib.loads(source_project.read_text())["project"]["version"]
        self.assertEqual(manifest["version"], version)
        self.assertEqual(manifest["meta"]["version"], version)

    def test_author_and_name_match_across_manifest_provider_and_tools(self):
        manifest = yaml.safe_load(Path("manifest.yaml").read_text())
        provider = yaml.safe_load(Path("provider/photon.yaml").read_text())
        self.assertEqual(provider["identity"]["name"], manifest["name"])
        self.assertEqual(provider["identity"]["author"], manifest["author"])
        for path in provider["tools"]:
            with self.subTest(tool=path):
                self.assertEqual(yaml.safe_load(Path(path).read_text())["identity"]["author"], manifest["author"])
