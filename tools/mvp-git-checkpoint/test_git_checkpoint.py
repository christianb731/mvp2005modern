import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_checkpoint import GitCheckpoint


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix="mvp-git-test-")
        self.addCleanup(self.sandbox.cleanup)
        self.root = Path(self.sandbox.name).resolve()
        self.git = Path(shutil.which("git"))
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "user.name", "MVP Test")
        self.run_git("config", "user.email", "mvp-test@example.invalid")
        self.run_git("config", "commit.gpgSign", "false")
        self.write("a.txt", "base\n")
        self.write("b.txt", "base\n")
        self.write(".gitignore", "ignored.log\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "Initial")
        self.worker = GitCheckpoint(self.root, self.git)

    def run_git(self, *args):
        return subprocess.run([str(self.git), "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, path, data):
        (self.root / path).write_text(data, encoding="utf-8")

    def test_staged_commits_the_index_and_preserves_later_worktree_edits(self):
        self.write("a.txt", "staged\n")
        self.run_git("add", "a.txt")
        self.write("a.txt", "later\n")
        index = self.worker.index.read_bytes()
        preview = self.worker.preview_commit()
        self.assertIn("+staged", preview["diff"])
        self.assertNotIn("+later", preview["diff"])
        self.assertEqual(self.worker.index.read_bytes(), index)
        result = self.worker.commit_changes(preview["preview_id"], "Checkpoint staged")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), result["commit"])
        self.assertEqual(self.run_git("show", "HEAD:a.txt"), "staged")
        self.assertEqual(self.run_git("diff", "--name-only"), "a.txt")
        with self.assertRaisesRegex(ValueError, "already used"):
            self.worker.commit_changes(preview["preview_id"], "Duplicate")

    def test_exact_paths_include_new_and_deleted_files_and_preserve_unrelated_index(self):
        self.write("a.txt", "unrelated staged\n")
        self.run_git("add", "a.txt")
        self.write("a.txt", "unrelated worktree\n")
        (self.root / "b.txt").unlink()
        self.write("new file.txt", "new file\n")
        preview = self.worker.preview_commit("paths", ["b.txt", "new file.txt"])
        self.assertNotIn("a.txt", preview["changes"])
        self.worker.commit_changes(preview["preview_id"], "Selected files")
        self.assertEqual(self.run_git("show", "HEAD:new file.txt"), "new file")
        self.assertEqual(self.run_git("ls-tree", "--name-only", "HEAD", "b.txt"), "")
        self.assertEqual(self.run_git("show", ":a.txt"), "unrelated staged")
        self.assertEqual(self.run_git("diff", "--cached", "--name-only"), "a.txt")
        self.assertEqual(self.run_git("diff", "--name-only"), "a.txt")

    def test_all_includes_nonignored_untracked_files(self):
        self.write("a.txt", "all\n")
        self.write("new.txt", "new\n")
        self.write("ignored.log", "ignored\n")
        preview = self.worker.preview_commit("all")
        self.assertNotIn("ignored.log", preview["changes"])
        self.assertEqual(self.run_git("diff", "--cached", "--name-only"), "")
        self.assertEqual(self.run_git("cat-file", "-t", "HEAD^{tree}"), "tree")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_git("cat-file", "-t", preview["tree"])
        self.worker.commit_changes(preview["preview_id"], "All changes")
        self.assertEqual(self.run_git("show", "HEAD:new.txt"), "new")
        self.assertEqual(self.run_git("status", "--porcelain"), "")

    def test_stale_preview_preserves_head_and_index(self):
        self.write("a.txt", "previewed\n")
        preview = self.worker.preview_commit("paths", ["a.txt"])
        self.write("a.txt", "changed after review\n")
        before = self.worker.index.read_bytes()
        with self.assertRaisesRegex(ValueError, "differ from the preview"):
            self.worker.commit_changes(preview["preview_id"], "Stale commit")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), preview["parent"])
        self.assertEqual(self.worker.index.read_bytes(), before)
        self.assertFalse(self.worker.index.with_name("index.lock").exists())

    def test_refuses_escape_and_preserves_an_existing_lock(self):
        with self.assertRaises(ValueError):
            self.worker.preview_commit("paths", ["../outside.txt"])
        self.write("a.txt", "updated\n")
        preview = self.worker.preview_commit("all")
        lock = self.worker.index.with_name("index.lock")
        lock.write_bytes(b"some other Git process")
        with self.assertRaisesRegex(RuntimeError, "already using"):
            self.worker.commit_changes(preview["preview_id"], "Locked")
        self.assertEqual(lock.read_bytes(), b"some other Git process")

    def test_refuses_commit_hooks_instead_of_bypassing_them(self):
        self.write("a.txt", "updated\n")
        preview = self.worker.preview_commit("all")
        (self.worker.git_dir / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "commit hooks"):
            self.worker.commit_changes(preview["preview_id"], "Blocked by hooks")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), preview["parent"])

    def test_filtered_paths_require_staging_with_ordinary_git(self):
        self.write(".gitattributes", "a.txt filter=example\n")
        self.write("a.txt", "filtered\n")
        with self.assertRaisesRegex(ValueError, "Stage filtered files"):
            self.worker.preview_commit("paths", ["a.txt"])
        self.run_git("add", "a.txt")
        preview = self.worker.preview_commit()
        self.worker.commit_changes(preview["preview_id"], "Previously staged blob")
        self.assertEqual(self.run_git("show", "HEAD:a.txt"), "filtered")

    def test_failed_index_install_rolls_back_branch(self):
        self.write("a.txt", "updated\n")
        preview = self.worker.preview_commit("paths", ["a.txt"])
        before = self.worker.index.read_bytes()
        with patch("git_checkpoint.os.replace", side_effect=PermissionError("test failure")):
            with self.assertRaisesRegex(RuntimeError, "branch was restored"):
                self.worker.commit_changes(preview["preview_id"], "Rollback test")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), preview["parent"])
        self.assertEqual(self.worker.index.read_bytes(), before)
        self.assertFalse(self.worker.index.with_name("index.lock").exists())


if __name__ == "__main__":
    unittest.main()
