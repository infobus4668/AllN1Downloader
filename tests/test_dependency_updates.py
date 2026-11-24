import tempfile
import unittest
from pathlib import Path

from scripts import update_android_sdk_pins


class AndroidSdkUpdateTests(unittest.TestCase):
    def test_finds_latest_stable_package_versions(self):
        sdkmanager_output = """
Available Packages:
  build-tools;36.0.0 | 36.0.0 | Android SDK Build-Tools 36
  build-tools;37.0.0-rc1 | 37.0.0-rc1 | Android SDK Build-Tools 37 RC
  ndk;28.2.13676358 | 28.2.13676358 | NDK 28.2
  ndk;29.0.14206865 | 29.0.14206865 | NDK 29.0
"""

        self.assertEqual(update_android_sdk_pins.latest_sdk_version(sdkmanager_output, "build-tools"), "36.0.0")
        self.assertEqual(update_android_sdk_pins.latest_sdk_version(sdkmanager_output, "ndk"), "29.0.14206865")

    def test_updates_only_to_newer_pins(self):
        sdkmanager_output = """
  build-tools;36.0.0 | 36.0.0 | Android SDK Build-Tools 36
  build-tools;37.0.0 | 37.0.0 | Android SDK Build-Tools 37
  ndk;28.2.13676358 | 28.2.13676358 | NDK 28.2
  ndk;29.0.14206865 | 29.0.14206865 | NDK 29.0
"""
        original_pins = update_android_sdk_pins.PIN_FILES
        with tempfile.TemporaryDirectory() as directory:
            build_tools = Path(directory) / "build-tools-version.txt"
            ndk = Path(directory) / "ndk-version.txt"
            build_tools.write_text("36.0.0\n", encoding="utf-8")
            ndk.write_text("29.0.14206865\n", encoding="utf-8")
            update_android_sdk_pins.PIN_FILES = {"build-tools": build_tools, "ndk": ndk}
            try:
                changes = update_android_sdk_pins.update_pins(sdkmanager_output)
            finally:
                update_android_sdk_pins.PIN_FILES = original_pins

            self.assertEqual(changes, [("build-tools", "36.0.0", "37.0.0")])
            self.assertEqual(build_tools.read_text(encoding="utf-8"), "37.0.0\n")
            self.assertEqual(ndk.read_text(encoding="utf-8"), "29.0.14206865\n")


if __name__ == "__main__":
    unittest.main()
