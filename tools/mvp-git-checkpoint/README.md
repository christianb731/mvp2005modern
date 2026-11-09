# MVP Git checkpoint worker

`mvp-git-checkpoint` gives the main Codex chat a local preview-and-commit workflow for one configured Git working tree. Use it when the user asks for a Git commit. The Ollama analysis worker stays read-only.

## Commit scopes

- `staged` uses the existing Git index. This is the default and preserves unstaged edits to partially staged files.
- `all` uses the current worktree, including tracked changes, deletions, and non-ignored new files. Inspect the file list before approving this scope.
- `paths` uses the current worktree for 1 to 100 exact repository-relative filenames. Include both names for a rename. Unrelated staged and unstaged changes are preserved.

Call `preview_commit` with the scope and, for `paths`, a filename list. Review the returned branch, change list, and diff. If the diff is truncated, inspect the remaining changes before committing or preview a narrower scope. Call `commit_changes` with that preview ID and a commit message. The ID expires after 15 minutes, and the worker requires a fresh preview if the branch, parent commit, or selected content changes. The result includes the local commit hash.

Use ordinary Git for merge or rebase operations, repositories with commit hooks or required signing, and sparse or split indexes. Stage files that use external Git filters through ordinary Git and then use the `staged` scope.

## Codex setup

Install an audited copy of `git_checkpoint.py` in a local directory outside the working tree so that switching branches cannot replace the write-capable server. Use Python 3.11 or newer with the v1 MCP SDK. The Python environment already installed for `mvp-ollama` can supply that dependency.

```toml
[mcp_servers.mvp-git-checkpoint]
command = "C:/AI/mvp-ollama-worker/.venv/Scripts/python.exe"
args = ["-B", "C:/AI/mvp-git-checkpoint/git_checkpoint.py"]
cwd = "C:/AI/mvp-git-checkpoint"
enabled_tools = ["preview_commit", "commit_changes"]
startup_timeout_sec = 30
tool_timeout_sec = 180

[mcp_servers.mvp-git-checkpoint.env]
MVP_GIT_REPO_ROOT = "C:/Gamings/Mvp baseball backup/mvp2005modern-main"
MVP_GIT_EXE = "C:/Program Files/Git/cmd/git.exe"

[mcp_servers.mvp-git-checkpoint.tools.preview_commit]
approval_mode = "approve"

[mcp_servers.mvp-git-checkpoint.tools.commit_changes]
approval_mode = "prompt"
```

Restart Codex to load the server. The main chat can then ask it to preview staged changes or commit an exact list of files. Update the installed copy when this source changes.
