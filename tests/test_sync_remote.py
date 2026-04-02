"""测试 clone 命令的 remote URL 同步功能。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from monarbor.git_ops import get_remote_url, set_remote_url


@pytest.fixture()
def local_repo(tmp_path: Path) -> Path:
    """创建一个本地 git 仓库，origin 指向一个假地址。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:old/repo.git"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


def test_get_remote_url(local_repo: Path):
    url = get_remote_url(local_repo)
    assert url == "git@github.com:old/repo.git"


def test_get_remote_url_nonexistent(local_repo: Path):
    url = get_remote_url(local_repo, remote="upstream")
    assert url is None


def test_set_remote_url(local_repo: Path):
    new_url = "git@git.woa.com:clawstudio/repo.git"
    result = set_remote_url(local_repo, new_url)
    assert result.ok

    url = get_remote_url(local_repo)
    assert url == new_url


def test_set_remote_url_preserves_other_remotes(local_repo: Path):
    subprocess.run(
        ["git", "remote", "add", "upstream", "git@github.com:upstream/repo.git"],
        cwd=local_repo, check=True, capture_output=True,
    )

    set_remote_url(local_repo, "git@git.woa.com:new/repo.git")

    assert get_remote_url(local_repo, "upstream") == "git@github.com:upstream/repo.git"
    assert get_remote_url(local_repo) == "git@git.woa.com:new/repo.git"
