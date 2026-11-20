import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import build_gallery
import manage


class ImageSyncTests(unittest.TestCase):
    def test_all_catalog_local_images_exist(self):
        photos = build_gallery.load_photos(build_gallery.ROOT)
        missing = [
            photo["image_path"]
            for photo in photos
            if photo.get("image_path")
            and not build_gallery.is_remote_url(photo["image_path"])
            and not (build_gallery.ROOT / photo["image_path"]).is_file()
        ]
        self.assertEqual(missing, [])

    def test_reuses_download_for_duplicate_google_photo_ids(self):
        first_url = "https://lh3.googleusercontent.com/gps-cs/photo-123=s0"
        second_url = "https://lh3.googleusercontent.com/gps-cs/photo-123=w800"
        photos = [
            {
                "id": "first-photo",
                "title": "First photo",
                "category": "Signs and Wonders",
                "image_path": first_url,
            },
            {
                "id": "second-photo",
                "title": "Second photo",
                "category": "Travel Discoveries",
                "image_path": second_url,
            },
        ]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"image bytes"
        urlopen = Mock(return_value=response)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "data" / "photos.yaml"
            catalog.parent.mkdir()
            catalog.write_text(
                f'photos:\n  - image_path: "{first_url}"\n'
                f'  - image_path: "{second_url}"\n',
                encoding="utf-8",
            )
            with (
                patch.object(manage, "ROOT", root),
                patch.object(manage, "DATA_FILE", catalog),
                patch.object(manage, "IMAGES_DIR", root / "images"),
                patch.object(manage.build_gallery, "load_photos", return_value=photos),
                patch("manage.urllib.request.urlopen", urlopen),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                downloaded = manage._download_remote_images()

            content = catalog.read_text(encoding="utf-8")
            self.assertEqual(downloaded, 1)
            urlopen.assert_called_once()
            self.assertNotIn(first_url, content)
            self.assertNotIn(second_url, content)
            self.assertEqual(content.count("images/signs-and-wonders/first-photo.jpg"), 2)

    def test_reuses_existing_local_file_with_matching_photo_id(self):
        photo_url = "https://lh3.googleusercontent.com/gps-cs/photo-123=s0"
        photos = [
            {
                "id": "saved-photo",
                "maps_photo_id": "photo-123",
                "image_path": "images/signs-and-wonders/saved-photo.jpg",
            },
            {
                "id": "new-reference",
                "maps_photo_id": "photo-123",
                "image_path": photo_url,
            },
        ]
        urlopen = Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "data" / "photos.yaml"
            catalog.parent.mkdir()
            catalog.write_text(f'  image_path: "{photo_url}"\n', encoding="utf-8")
            local_image = root / "images" / "signs-and-wonders" / "saved-photo.jpg"
            local_image.parent.mkdir(parents=True)
            local_image.write_bytes(b"already downloaded")
            with (
                patch.object(manage, "ROOT", root),
                patch.object(manage, "DATA_FILE", catalog),
                patch.object(manage, "IMAGES_DIR", root / "images"),
                patch.object(manage.build_gallery, "load_photos", return_value=photos),
                patch("manage.urllib.request.urlopen", urlopen),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                downloaded = manage._download_remote_images()

            self.assertEqual(downloaded, 0)
            urlopen.assert_not_called()
            self.assertIn("images/signs-and-wonders/saved-photo.jpg", catalog.read_text(encoding="utf-8"))

    def test_upsert_does_not_add_duplicate_photo_from_same_harvest(self):
        photo_url = "https://lh3.googleusercontent.com/gps-cs/photo-123=s0"
        photos = [
            {"title": "First title", "image_path": photo_url},
            {"title": "Updated title", "image_path": photo_url},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "data" / "photos.yaml"
            with (
                patch.object(manage, "ROOT", root),
                patch.object(manage, "DATA_FILE", catalog),
                patch.object(manage.build_gallery, "load_photos", return_value=[]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                manage.upsert_photos(photos)

            self.assertEqual(catalog.read_text(encoding="utf-8").count("  - id:"), 1)


if __name__ == "__main__":
    unittest.main()
