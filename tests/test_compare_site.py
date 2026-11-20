import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import compare_site


class CompareSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.baseline = self.root / "baseline"
        self.generated = self.root / "generated"
        for folder in (self.baseline, self.generated):
            (folder / "images").mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_site_file(self, root, path, content):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def test_exact_site_match_has_no_differences(self):
        for root in (self.baseline, self.generated):
            self.write_site_file(root, "index.html", b"<h1>Gallery</h1>")
            self.write_site_file(root, "styles.css", b"body{}")
            self.write_site_file(root, "images/photo.jpg", b"photo")

        self.assertEqual(compare_site.compare(self.baseline, self.generated), ([], [], []))

    def test_reports_added_removed_and_updated_site_assets(self):
        self.write_site_file(self.baseline, "index.html", b"<h1>Old</h1>")
        self.write_site_file(self.baseline, "styles.css", b"body{}")
        self.write_site_file(self.baseline, "images/removed.jpg", b"old photo")
        self.write_site_file(self.generated, "index.html", b"<h1>New</h1>")
        self.write_site_file(self.generated, "styles.css", b"body{}")
        self.write_site_file(self.generated, "images/added.jpg", b"new photo")

        added, removed, changed = compare_site.compare(self.baseline, self.generated)

        self.assertEqual(added, ["images/added.jpg"])
        self.assertEqual(removed, ["images/removed.jpg"])
        self.assertEqual(changed, ["index.html"])

    def test_exact_match_summary_marks_deploy_as_unchanged(self):
        self.write_site_file(self.baseline, "index.html", b"<h1>Gallery</h1>")
        self.write_site_file(self.generated, "index.html", b"<h1>Gallery</h1>")
        summary = self.root / "summary.md"
        output = self.root / "output.txt"

        with patch.dict(os.environ, {
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(output),
        }):
            compare_site.write_summary(self.baseline, self.generated)

        self.assertIn("exactly matches", summary.read_text(encoding="utf-8"))
        self.assertIn("changed=false", output.read_text(encoding="utf-8"))

    def test_site_changes_are_reported_and_marked_for_review(self):
        self.write_site_file(self.baseline, "index.html", b"<h1>Old</h1>")
        self.write_site_file(self.generated, "index.html", b"<h1>New</h1>")
        summary = self.root / "summary.md"
        output = self.root / "output.txt"

        with patch.dict(os.environ, {
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(output),
        }):
            compare_site.write_summary(self.baseline, self.generated)

        self.assertIn("do not fail validation", summary.read_text(encoding="utf-8"))
        self.assertIn("generated-gallery-preview", summary.read_text(encoding="utf-8"))
        self.assertIn("changed=true", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
