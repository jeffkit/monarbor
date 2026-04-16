"""共用 pytest fixtures。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def bare_repo(tmp_path: Path) -> tuple[Path, str]:
    """创建一个本地 bare git 仓库作为 remote，包含若干提交，便于测试 clone 相关选项。

    返回 (remote_path, default_branch_name)。
    """
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    work = tmp_path / "work"
    work.mkdir()
    _git = lambda *args, **kw: subprocess.run(["git", *args], cwd=work, check=True, capture_output=True, **kw)
    _git("init")
    _git("config", "user.email", "test@test.com")
    _git("config", "user.name", "Test")

    # 写入多个提交，方便测试 --depth 是否真的截断了历史
    for i in range(5):
        (work / f"file{i}.txt").write_text(f"content {i}")
        _git("add", ".")
        _git("commit", "-m", f"commit {i}")

    _git("remote", "add", "origin", str(remote))
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=work, capture_output=True, text=True,
    )
    default_branch = result.stdout.strip()
    _git("push", "-u", "origin", default_branch)
    # 使用 file:// 前缀强制走 pack 协议，使 --depth 等选项生效
    # 本地绝对路径走 hardlink 传输，git 会忽略 --depth
    return "file://" + str(remote), default_branch
