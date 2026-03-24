"""回归测试：clone_into_existing 能将代码克隆到已有非空目录（如含 mona.yaml 的占位目录）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from monarbor.git_ops import clone_into_existing


@pytest.fixture()
def bare_repo(tmp_path: Path) -> Path:
    """创建一个本地 bare git 仓库作为 remote，包含一个初始提交。"""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    # 创建一个工作仓库，提交一个文件，推送到 bare remote
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=work, check=True, capture_output=True)
    (work / "hello.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True, capture_output=True)
    # 获取当前默认分支名（main 或 master）
    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=work, capture_output=True, text=True)
    default_branch = result.stdout.strip()
    subprocess.run(["git", "push", "-u", "origin", default_branch], cwd=work, check=True, capture_output=True)
    return remote, default_branch


def test_clone_into_existing_with_preplaced_file(bare_repo: tuple, tmp_path: Path):
    """目标目录已存在且含有文件（模拟 mona.yaml 占位），clone_into_existing 应成功。"""
    remote, branch = bare_repo
    target = tmp_path / "target"
    target.mkdir()
    (target / "mona.yaml").write_text("name: test\n")  # 模拟已有占位文件

    result = clone_into_existing(str(remote), target, branch=branch)

    assert result.ok, f"clone_into_existing 失败: {result.error}"
    assert (target / ".git").exists(), "clone 后应存在 .git 目录"
    assert (target / "hello.txt").exists(), "clone 后应包含仓库文件"
    assert (target / "mona.yaml").exists(), "原有的 mona.yaml 应被保留"


def test_clone_into_empty_dir(bare_repo: tuple, tmp_path: Path):
    """目标目录为空时，clone_into_existing 也应正常工作。"""
    remote, branch = bare_repo
    target = tmp_path / "empty_target"
    target.mkdir()

    result = clone_into_existing(str(remote), target, branch=branch)

    assert result.ok, f"clone_into_existing 失败: {result.error}"
    assert (target / ".git").exists()
    assert (target / "hello.txt").exists()
