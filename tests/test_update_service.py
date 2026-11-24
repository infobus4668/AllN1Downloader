import unittest

import update_service


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
                {"name": "AllN1Downloader-Windows-x64.exe", "browser_download_url": "https://github.com/example.exe", "digest": "sha256:abc"},
                {"name": "AllN1Downloader-Android.apk", "browser_download_url": "https://github.com/example.apk"},
            ],
        }

        windows = update_service.release_info(release, "1.0.0", "windows")
        android = update_service.release_info(release, "1.0.0", "android")
        current = update_service.release_info(release, "1.0.1", "windows")

        self.assertEqual(windows["asset_name"], "AllN1Downloader-Windows-x64.exe")
        self.assertEqual(windows["asset_digest"], "sha256:abc")
        self.assertEqual(android["asset_name"], "AllN1Downloader-Android.apk")
        self.assertFalse(current["available"])
        self.assertEqual(current["status"], "current")

    def test_release_info_selects_signed_apt_package(self):
        release = {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/infobus4668/AllN1Downloader/releases/tag/v1.0.1",
            "assets": [{
                "name": "alln1downloader_1.0.1_amd64.deb",
                "browser_download_url": "https://github.com/example.deb",
            }],
        }

        update = update_service.release_info(release, "1.0.0", "linux")

        self.assertTrue(update["available"])
        self.assertEqual(update["asset_name"], "alln1downloader_1.0.1_amd64.deb")


if __name__ == "__main__":
    unittest.main()
