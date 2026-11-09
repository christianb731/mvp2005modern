"""Local Git checkpoints for one configured MVP repository."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Scope = Literal["staged", "all", "paths"]
PREVIEW_LIFETIME = 15 * 60
PATCH_LIMIT = 24_000
COMMIT_HOOKS = (
    "pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "reference-transaction",
    "post-index-change",
)
IN_PROGRESS = (
    "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-apply", "rebase-merge",
    "sequencer", "BISECT_START",
)


@dataclass(frozen=True)
class Preview:
    scope: Scope
    paths: tuple[str, ...]
    branch: str
    head: str
    tree: str
    created_at: float


class GitCheckpoint:
    def __init__(self, root: Path, git: Path):
        self.root = root.resolve(strict=True)
        self.git = git.resolve(strict=True)
        if Path(self.run("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise ValueError("MVP_GIT_REPO_ROOT must be the root of the intended Git working tree.")
        self.git_dir = Path(self.run("rev-parse", "--absolute-git-dir")).resolve()
        self.index = self.git_dir / "index"
        self.objects = Path(self.run("rev-parse", "--path-format=absolute", "--git-path", "objects")).resolve()
        self.previews: dict[str, Preview] = {}
        self.preview_lock = threading.Lock()

    def run(
        self, *args: str, index: Path | None = None, hooks: Path | None = None,
        objects: Path | None = None, data: bytes | None = None, limit: int | None = None,
        missing_ok: bool = False,
    ) -> str:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1", GIT_OPTIONAL_LOCKS="0")
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        if objects is not None:
            env["GIT_OBJECT_DIRECTORY"] = str(objects)
            env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(self.objects)
        command = [str(self.git), "-c", f"safe.directory={self.root.as_posix()}",
                   "-c", "core.fsmonitor=false", "--literal-pathspecs", "-C", str(self.root)]
        if hooks is not None:
            command.extend(["-c", f"core.hooksPath={hooks.as_posix()}"])
        with tempfile.TemporaryFile() as stdout:
            result = subprocess.run(
                command + list(args), input=data if data is not None else b"", stdout=stdout,
                stderr=subprocess.PIPE, env=env, timeout=None if args[0] == "update-ref" else 45,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                if missing_ok and result.returncode == 1:
                    return ""
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"git {args[0]} failed: {error or result.returncode}")
            stdout.seek(0)
            output = stdout.read() if limit is None else stdout.read(limit + 1)
        if limit is not None and len(output) > limit:
            return output[:limit].decode("utf-8", errors="replace") + "\n[Preview truncated.]"
        return output.decode("utf-8", errors="replace").rstrip("\n")

    def branch_head(self) -> tuple[str, str]:
        try:
            branch = self.run("symbolic-ref", "--quiet", "HEAD")
            head = self.run("rev-parse", "--verify", "HEAD^{commit}")
        except RuntimeError as exc:
            raise ValueError("Checkpoints require a checked-out branch with an existing commit.") from exc
        if not branch.startswith("refs/heads/"):
            raise ValueError("HEAD must refer to a local branch.")
        return branch, head

    def check_ready(self) -> None:
        if not self.index.is_file() or self.index.is_symlink():
            raise ValueError("Prepare a regular working-tree index with ordinary Git first.")
        if any((self.git_dir / marker).exists() for marker in IN_PROGRESS) or self.run("ls-files", "--unmerged"):
            raise ValueError("Finish the current Git operation or resolve conflicts before creating a checkpoint.")
        split_index = self.run("rev-parse", "--shared-index-path")
        sparse = self.run("config", "--bool", "--get", "core.sparseCheckout", missing_ok=True)
        if split_index or sparse == "true":
            raise ValueError("Use ordinary Git for split indexes or sparse checkouts.")
        if self.run("config", "--bool", "--get", "commit.gpgSign", missing_ok=True) == "true":
            raise ValueError("Use ordinary Git for repositories that require signed commits.")
        configured = self.run("config", "--path", "--get", "core.hooksPath", missing_ok=True)
        hooks = (self.root / configured) if configured else Path(self.run(
            "rev-parse", "--path-format=absolute", "--git-path", "hooks"
        ))
        if any((hooks / name).is_file() for name in COMMIT_HOOKS):
            raise ValueError("Use ordinary Git to run this repository's configured commit hooks.")

    def paths_for(self, scope: Scope, paths: list[str] | None) -> tuple[str, ...]:
        if scope not in {"staged", "all", "paths"}:
            raise ValueError("Choose staged, all, or paths.")
        if scope != "paths":
            if paths:
                raise ValueError("Only the paths scope accepts filenames.")
            return ()
        if not paths or len(paths) > 100:
            raise ValueError("The paths scope requires 1 to 100 exact repository-relative filenames.")
        normalized = []
        for raw in paths:
            path = raw.replace("\\", "/")
            parts = path.split("/")
            if ":" in path or any(ord(c) < 32 for c in path) or any(
                part in {"", ".", ".."} or part.rstrip(" .").casefold() == ".git" for part in parts
            ):
                raise ValueError(f"Invalid repository-relative filename: {raw!r}")
            candidate = self.root / path
            parent = candidate.parent.resolve()
            if not parent.is_relative_to(self.root) or parent.is_relative_to(self.git_dir) or candidate.is_dir():
                raise ValueError(f"Choose an exact file inside the repository: {raw!r}")
            normalized.append(path)
        return tuple(dict.fromkeys(normalized))

    def make_tree(
        self, scope: Scope, paths: tuple[str, ...], head: str, directory: Path, *, preview: bool,
    ) -> tuple[str, Path, Path]:
        index = directory / "candidate.index"
        hooks = directory / "hooks"
        hooks.mkdir()
        objects = directory / "objects" if preview else None
        if objects is not None:
            objects.mkdir()
        options = {"index": index, "hooks": hooks, "objects": objects}
        if scope == "paths":
            self.run("read-tree", head, **options)
        else:
            shutil.copyfile(self.index, index)
        if scope != "staged":
            # Git can execute configured clean filters during add. A checkpoint
            # should not run those programs or stage differently from normal Git.
            filenames = ("\0".join(paths) + "\0") if paths else self.run(
                "ls-files", "-z", "--cached", "--others", "--exclude-standard", **options
            )
            attributes = self.run("check-attr", "-z", "--stdin", "filter",
                                  data=filenames.encode("utf-8"), **options).split("\0")
            for name, value in zip(attributes[::3], attributes[2::3]):
                if value not in {"unspecified", "unset", "set"}:
                    raise ValueError(f"Stage filtered files with ordinary Git first: {name!r}")
            self.run("add", "-A", "--", *paths, **options)
        tree = self.run("write-tree", **options)
        return tree, index, hooks

    def preview_commit(self, scope: Scope = "staged", paths: list[str] | None = None) -> dict:
        selected = self.paths_for(scope, paths)
        self.check_ready()
        branch, head = self.branch_head()
        with tempfile.TemporaryDirectory(prefix="mvp-git-preview-") as temp:
            directory = Path(temp)
            tree, _, _ = self.make_tree(scope, selected, head, directory, preview=True)
            if tree == self.run("rev-parse", f"{head}^{{tree}}"):
                raise ValueError("No changes in the selected scope.")
            args = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames")
            summary = self.run(*args, "--name-status", head, tree, objects=directory / "objects", limit=PATCH_LIMIT)
            patch = self.run(*args, "--patch", head, tree, objects=directory / "objects", limit=PATCH_LIMIT)
        if self.branch_head() != (branch, head):
            raise ValueError("The branch changed during preview. Preview it again.")
        token = secrets.token_urlsafe(24)
        with self.preview_lock:
            if len(self.previews) == 16:
                del self.previews[next(iter(self.previews))]
            self.previews[token] = Preview(scope, selected, branch, head, tree, time.monotonic())
        return {"preview_id": token, "repository": str(self.root), "scope": scope, "paths": selected,
                "branch": branch.removeprefix("refs/heads/"), "parent": head, "tree": tree,
                "changes": summary, "diff": patch,
                "truncated": summary.endswith("[Preview truncated.]") or patch.endswith("[Preview truncated.]")}

    def commit_changes(self, preview_id: str, message: str) -> dict:
        message = message.strip()
        if not message or "\x00" in message or len(message.encode("utf-8")) > 8192:
            raise ValueError("Provide a commit message of 1 to 8192 UTF-8 bytes.")
        with self.preview_lock:
            preview = self.previews.pop(preview_id, None)
        if preview is None or time.monotonic() - preview.created_at > PREVIEW_LIFETIME:
            raise ValueError("Preview missing, expired, or already used. Create a fresh preview.")

        lock = self.index.with_name("index.lock")
        try:
            locked = lock.open("xb")
        except FileExistsError as exc:
            raise RuntimeError("Git is already using the index. Wait, then create a fresh preview.") from exc
        owns_lock = True
        try:
            with locked, tempfile.TemporaryDirectory(prefix="mvp-git-commit-") as temp:
                self.check_ready()
                if self.branch_head() != (preview.branch, preview.head):
                    raise ValueError("The branch or HEAD changed. Create a fresh preview.")
                directory = Path(temp)
                tree, candidate, hooks = self.make_tree(
                    preview.scope, preview.paths, preview.head, directory, preview=False
                )
                if tree != preview.tree:
                    raise ValueError("The selected changes differ from the preview. Review a fresh preview.")

                if preview.scope != "staged":
                    next_index = candidate
                    if preview.scope == "paths":
                        next_index = directory / "reconciled.index"
                        shutil.copyfile(self.index, next_index)
                        self.run("reset", "--quiet", tree, "--", *preview.paths, index=next_index, hooks=hooks)
                    locked.write(next_index.read_bytes())
                    locked.flush()
                    os.fsync(locked.fileno())

                commit = self.run("commit-tree", tree, "-p", preview.head, "-F", "-",
                                  data=(message + "\n").encode("utf-8"), hooks=hooks)
                self.run("update-ref", "-m", "MVP Git checkpoint", preview.branch, commit, preview.head, hooks=hooks)
                if preview.scope != "staged":
                    locked.close()
                    try:
                        os.replace(lock, self.index)
                        owns_lock = False
                    except OSError as exc:
                        try:
                            self.run("update-ref", "-m", "MVP Git checkpoint rollback", preview.branch,
                                     preview.head, commit, hooks=hooks)
                        except RuntimeError as rollback:
                            raise RuntimeError(f"Created {commit}, but index update and branch rollback failed. Inspect Git status. {rollback}") from exc
                        raise RuntimeError("Index update failed. The branch was restored to its previous commit.") from exc
        finally:
            if owns_lock:
                lock.unlink()
        return {"commit": commit, "branch": preview.branch.removeprefix("refs/heads/"),
                "parent": preview.head, "tree": preview.tree, "scope": preview.scope,
                "message": message}


def serve() -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    worker = GitCheckpoint(Path(os.environ["MVP_GIT_REPO_ROOT"]), Path(os.environ["MVP_GIT_EXE"]))
    server = FastMCP("mvp-git-checkpoint")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def preview_commit(scope: Scope = "staged", paths: list[str] | None = None) -> dict:
        """Preview staged changes, all non-ignored changes, or exact working-tree paths."""
        return worker.preview_commit(scope, paths)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
    def commit_changes(preview_id: str, message: str) -> dict:
        """Create the reviewed local Git commit using a fresh, single-use preview ID."""
        return worker.commit_changes(preview_id, message)

    server.run(transport="stdio")


if __name__ == "__main__":
    serve()
