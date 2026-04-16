"""测试 clone -r 对已 clone 的嵌套大仓能递归处理其内部子仓库（场景 2）。

构造本地 bare repo 作为 remote，模拟：
  root mona.yaml 注册了 platform（有 repo_url）
  platform 自身也有 mona.yaml，注册了 svc-a（有 repo_url）
  先 clone platform，再执行 clone -r，验证 svc-a 也被 clone。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from click.testing import CliRunner

from monarbor.cli import main


def _make_bare_repo(path: Path, files: dict[str, str] | None = None) -> str:
    """创建一个本地 bare git 仓库，返回其路径字符串。"""
    bare = path / "bare.git"
    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

    work = path / "work"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=work, check=True, capture_output=True)

    for name, content in (files or {"README.md": "init"}).items():
        f = work / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=work, check=True, capture_output=True)

    result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=work, capture_output=True, text=True)
    branch = result.stdout.strip()
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=work, check=True, capture_output=True)

    return str(bare), branch


def test_clone_r_recurses_into_already_cloned_repo(tmp_path: Path, monkeypatch):
    """clone -r 应对已 clone 的嵌套大仓递归处理其内部子仓库。

    对应场景 2：clone -r（已 clone）跳过后不递归。"""

    # 构造两个 bare repo 作为 remote
    svc_a_remote, branch = _make_bare_repo(tmp_path / "remotes" / "svc-a")
    platform_mona = yaml.dump({
        "name": "Platform",
        "owner": "test",
        "repos": [{"path": "svc-a", "name": "SvcA", "repo_url": svc_a_remote,
                    "branches": {"dev": branch}}],
    }, allow_unicode=True)
    platform_remote, branch = _make_bare_repo(
        tmp_path / "remotes" / "platform",
        files={"README.md": "platform", "mona.yaml": platform_mona},
    )

    # 构造逻辑大仓根目录
    root = tmp_path / "monorepo"
    root.mkdir()
    root_mona = {
        "name": "Root",
        "owner": "test",
        "repos": [{"path": "platform", "name": "Platform", "repo_url": platform_remote,
                    "branches": {"dev": branch}}],
    }
    (root / "mona.yaml").write_text(yaml.dump(root_mona, allow_unicode=True))

    runner = CliRunner()
    monkeypatch.chdir(root)

    # 第一次 clone：拉下 platform
    result = runner.invoke(main, ["clone"])
    assert result.exit_code == 0
    assert (root / "platform" / ".git").exists(), "platform 应已 clone"
    assert not (root / "platform" / "svc-a" / ".git").exists(), "svc-a 尚未 clone"

    # 第二次 clone -r：platform 已存在，应递归进入 clone svc-a
    result = runner.invoke(main, ["clone", "-r"])
    assert result.exit_code == 0
    assert (root / "platform" / "svc-a" / ".git").exists(), \
        "clone -r 应递归进入已 clone 的 platform，clone 其直接注册子仓 svc-a"
