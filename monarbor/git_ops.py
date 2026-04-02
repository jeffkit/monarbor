"""Git 操作封装。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    ok: bool
    output: str
    error: str = ""


def run_git(args: list[str], cwd: Path | None = None) -> GitResult:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return GitResult(
            ok=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        return GitResult(ok=False, output="", error="操作超时 (300s)")
    except FileNotFoundError:
        return GitResult(ok=False, output="", error="未找到 git 命令，请确认已安装 git")


def clone(repo_url: str, target: Path, branch: str | None = None) -> GitResult:
    args = ["clone"]
    if branch:
        args.extend(["-b", branch])
    args.extend([repo_url, str(target)])
    return run_git(args)


def clone_into_existing(repo_url: str, target: Path, branch: str | None = None) -> GitResult:
    """Clone into a non-empty directory (e.g. containing mona.yaml) via init+remote+fetch+checkout."""
    result = run_git(["init"], cwd=target)
    if not result.ok:
        return result
    result = run_git(["remote", "add", "origin", repo_url], cwd=target)
    if not result.ok:
        return result
    fetch_args = ["fetch", "origin"]
    if branch:
        fetch_args.append(branch)
    result = run_git(fetch_args, cwd=target)
    if not result.ok:
        return result
    ref = branch or "HEAD"
    result = run_git(["checkout", "-b", ref, f"origin/{ref}"], cwd=target)
    if not result.ok:
        # branch may already exist, try plain checkout
        result = run_git(["checkout", ref], cwd=target)
    return result


def get_remote_url(repo_path: Path, remote: str = "origin") -> str | None:
    """获取指定 remote 的 URL，不存在则返回 None。"""
    result = run_git(["remote", "get-url", remote], cwd=repo_path)
    return result.output if result.ok else None


def set_remote_url(repo_path: Path, url: str, remote: str = "origin") -> GitResult:
    """原地更新指定 remote 的 URL。"""
    return run_git(["remote", "set-url", remote, url], cwd=repo_path)


def pull(repo_path: Path) -> GitResult:
    return run_git(["pull"], cwd=repo_path)


def current_branch(repo_path: Path) -> str:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return result.output if result.ok else "(unknown)"


def is_dirty(repo_path: Path) -> bool:
    result = run_git(["status", "--porcelain"], cwd=repo_path)
    return bool(result.output)


def checkout(repo_path: Path, branch: str) -> GitResult:
    return run_git(["checkout", branch], cwd=repo_path)


def fetch(repo_path: Path) -> GitResult:
    return run_git(["fetch", "--all", "--prune"], cwd=repo_path)


def ahead_behind(repo_path: Path) -> tuple[int, int]:
    """返回 (ahead, behind) 相对于上游的提交数。"""
    result = run_git(
        ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        cwd=repo_path,
    )
    if not result.ok:
        return (0, 0)
    parts = result.output.split()
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (0, 0)


def list_worktrees(repo_path: Path) -> list[dict[str, str]]:
    """列出仓库的所有 worktree，返回 [{path, branch, bare?}]。"""
    result = run_git(["worktree", "list", "--porcelain"], cwd=repo_path)
    if not result.ok:
        return []
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.output.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch refs/heads/"):]
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["branch"] = "(detached)"
    if current:
        worktrees.append(current)
    return worktrees


def run_in_repo(repo_path: Path, command: str) -> GitResult:
    """在仓库目录下执行任意 shell 命令。"""
    try:
        result = subprocess.run(
            command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
            shell=True,
        )
        return GitResult(
            ok=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        return GitResult(ok=False, output="", error="命令超时 (120s)")
