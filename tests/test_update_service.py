import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import update_service

DOWNLOAD_ROOT = "https://github.com/infobus4668/AllN1Downloader/releases/download/v1.0.1"


class ReleaseUpdateTests(unittest.TestCase):
    def test_version_key_accepts_tag_prefix_and_orders_versions(self):
        self.assertEqual(update_service.version_key("v1.2.3"), (1, 2, 3))
        self.assertGreater(update_service.version_key("1.0.10"), update_service.version_key("1.0.9"))
        self.assertIsNone(update_service.version_key("main"))

    def test_release_info_selects_platform_asset_only_for_newer_release(self):
        release = {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/infobus4668/AllN1Downloader/releases/tag/v1.0.1",
            "assets": [
                {"name": "AllN1Downloader-Windows-x64.exe", "browser_download_url": f"{DOWNLOAD_ROOT}/AllN1Downloader-Windows-x64.exe", "digest": "sha256:" + "a" * 64},
                {"name": "AllN1Downloader-Android.apk", "browser_download_url": f"{DOWNLOAD_ROOT}/AllN1Downloader-Android.apk"},
            ],
        }

        windows = update_service.release_info(release, "1.0.0", "windows")
        android = update_service.release_info(release, "1.0.0", "android")
        current = update_service.release_info(release, "1.0.1", "windows")

        self.assertEqual(windows["asset_name"], "AllN1Downloader-Windows-x64.exe")
        self.assertEqual(windows["asset_digest"], "sha256:" + "a" * 64)
        self.assertEqual(android["asset_name"], "AllN1Downloader-Android.apk")
        self.assertFalse(current["available"])
        self.assertEqual(current["status"], "current")

    def test_release_info_selects_signed_apt_package(self):
        release = {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/infobus4668/AllN1Downloader/releases/tag/v1.0.1",
            "assets": [{
                "name": "alln1downloader_1.0.1_amd64.deb",
                "browser_download_url": f"{DOWNLOAD_ROOT}/alln1downloader_1.0.1_amd64.deb",
            }],
        }

        update = update_service.release_info(release, "1.0.0", "linux")

        self.assertTrue(update["available"])
        self.assertEqual(update["asset_name"], "alln1downloader_1.0.1_amd64.deb")

    def test_rejects_wrong_repository_or_missing_windows_digest(self):
        name = "AllN1Downloader-Windows-x64.exe"
        for url, digest in (
            (f"{DOWNLOAD_ROOT.replace('infobus4668', 'other')}/{name}", "sha256:" + "a" * 64),
            (f"{DOWNLOAD_ROOT}/{name}", ""),
        ):
            with self.subTest(url=url, digest=digest):
                release = {"tag_name": "v1.0.1", "assets": [None, {
                    "name": name, "browser_download_url": url, "digest": digest,
                }]}
                update = update_service.release_info(release, "1.0.0", "windows")
                self.assertFalse(update["available"])
                self.assertEqual(update["status"], "invalid_release_asset")

    def test_missing_public_release_is_not_reported_as_current(self):
        error = HTTPError("https://api.github.com/", 404, "Not Found", None, None)
        with patch.object(update_service.urllib.request, "urlopen", side_effect=error):
            update = update_service.fetch_latest_release(update_service.DEFAULT_REPOSITORY, "1.0.0", "android")
        self.assertEqual(update["status"], "no_release")
        self.assertFalse(update["available"])


if __name__ == "__main__":
    unittest.main()
