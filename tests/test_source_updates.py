import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import update_source


class SourceUpdateTests(unittest.TestCase):
    def test_source_archive_without_git_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(update_source, "ROOT", Path(directory)), patch.object(update_source.shutil, "which", return_value="git"):
                self.assertIn("No Git checkout", update_source.update_checkout())

    def test_dirty_checkout_is_not_overwritten(self):
        branch = subprocess.CompletedProcess([], 0, "main\n", "")
        upstream = subprocess.CompletedProcess([], 0, "origin/main\n", "")
        dirty = subprocess.CompletedProcess([], 0, " M app.py\n", "")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".git").mkdir()
            with patch.dict(os.environ, {"ALLN1_AUTO_UPDATE": "1"}), \
                 patch.object(update_source, "ROOT", Path(directory)), \
                 patch.object(update_source.shutil, "which", return_value="git"), \
                 patch.object(update_source, "run_git", side_effect=[branch, upstream, dirty]) as git:
                self.assertIn("Local source changes", update_source.update_checkout())
                self.assertEqual(git.call_count, 3)

    def test_clean_checkout_fast_forwards_to_origin(self):
        clean = subprocess.CompletedProcess([], 0, "", "")
        branch = subprocess.CompletedProcess([], 0, "main\n", "")
        upstream = subprocess.CompletedProcess([], 0, "origin/main\n", "")
        fetched = subprocess.CompletedProcess([], 0, "", "")
        before = subprocess.CompletedProcess([], 0, "old-commit\n", "")
        pulled = subprocess.CompletedProcess([], 0, "", "")
        after = subprocess.CompletedProcess([], 0, "new-commit\n", "")
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".git").mkdir()
            with patch.dict(os.environ, {"ALLN1_AUTO_UPDATE": "1"}), \
                 patch.object(update_source, "ROOT", Path(directory)), \
                 patch.object(update_source.shutil, "which", return_value="git"), \
                 patch.object(update_source, "run_git", side_effect=[branch, upstream, clean, fetched, before, pulled, after]):
                self.assertIn("updated to the latest", update_source.update_checkout())


if __name__ == "__main__":
    unittest.main()
