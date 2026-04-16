"""CLI 回归测试：monarbor clone 新增参数的端到端行为。

通过 Click CliRunner 模拟用户输入，验证：
- 各参数能被 CLI 正确解析
- 参数值被正确传递给底层 git 命令（通过 mock 拦截）
- 实际 clone 场景（本地 bare repo）在新参数下正常工作
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from monarbor.cli import main


# ── fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def monorepo(tmp_path: Path, bare_repo: tuple) -> tuple[Path, str]:
    """在 tmp_path 创建一个最小可用的 mona.yaml 大仓，注册 bare_repo 为子仓库。

    返回 (root, default_branch)。
    """
    remote, branch = bare_repo
    root = tmp_path / "monorepo"
    root.mkdir()

    config = {
        "name": "test-monorepo",
        "description": "CLI 测试用大仓",
        "owner": "test",
        "repos": [
            {
                "path": "sub/repo-a",
                "name": "Repo A",
                "repo_url": str(remote),
                "branches": {"dev": branch, "test": branch, "prod": branch},
            }
        ],
    }
    (root / "mona.yaml").write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return root, branch


@pytest.fixture()
def multi_repo_monorepo(tmp_path: Path, bare_repo: tuple) -> tuple[Path, str]:
    """注册 3 个子仓库，用于并行 clone 测试。"""
    remote, branch = bare_repo
    root = tmp_path / "monorepo"
    root.mkdir()

    repos = [
        {
            "path": f"sub/repo-{i}",
            "name": f"Repo {i}",
            "repo_url": str(remote),
            "branches": {"dev": branch, "test": branch, "prod": branch},
        }
        for i in range(3)
    ]
    config = {
        "name": "multi-repo",
        "description": "并行 clone 测试",
        "owner": "test",
        "repos": repos,
    }
    (root / "mona.yaml").write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return root, branch


# ── 帮助信息回归 ────────────────────────────────────────────────


class TestCloneHelp:
    """验证新参数出现在帮助文本中。"""

    def test_help_contains_shallow(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert result.exit_code == 0
        assert "--shallow" in result.output

    def test_help_contains_depth(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--depth" in result.output

    def test_help_contains_git_filter(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--git-filter" in result.output

    def test_help_contains_single_branch(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--single-branch" in result.output

    def test_help_contains_no_tags(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--no-tags" in result.output

    def test_help_contains_jobs(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--jobs" in result.output

    def test_help_contains_timeout(self):
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--help"])
        assert "--timeout" in result.output


# ── 参数解析：mock 拦截 git 调用 ────────────────────────────────


class TestCloneArgParsing:
    """验证 CLI 参数被正确解析并传递给 git clone。"""

    def _run_with_mock(self, monorepo: tuple, monkeypatch, *extra_args: str):
        """在 monorepo 根目录调用 monarbor clone，拦截所有 subprocess.run 调用。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()

        captured_calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            captured_calls.append(args)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("monarbor.git_ops.subprocess.run", side_effect=fake_run):
            result = runner.invoke(main, ["clone", *extra_args], catch_exceptions=False)

        return result, captured_calls

    def _git_clone_args(self, calls: list[list[str]]) -> list[str]:
        """从所有调用中找出 git clone 那一次的参数。"""
        for args in calls:
            if len(args) >= 2 and args[0] == "git" and args[1] == "clone":
                return args
        return []

    def test_shallow_flag_becomes_depth_1(self, monorepo: tuple, monkeypatch):
        """--shallow 应在 git clone 命令中生成 --depth 1。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--shallow")
        clone_args = self._git_clone_args(calls)
        assert clone_args, "应有 git clone 调用"
        assert "--depth" in clone_args
        assert clone_args[clone_args.index("--depth") + 1] == "1"

    def test_depth_option_forwarded(self, monorepo: tuple, monkeypatch):
        """--depth 50 应在 git clone 命令中生成 --depth 50。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--depth", "50")
        clone_args = self._git_clone_args(calls)
        assert "--depth" in clone_args
        assert clone_args[clone_args.index("--depth") + 1] == "50"

    def test_git_filter_forwarded(self, monorepo: tuple, monkeypatch):
        """--git-filter blob:none 应在 git clone 命令中生成 --filter=blob:none。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--git-filter", "blob:none")
        clone_args = self._git_clone_args(calls)
        assert "--filter=blob:none" in clone_args

    def test_single_branch_forwarded(self, monorepo: tuple, monkeypatch):
        """--single-branch 应出现在 git clone 参数中。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--single-branch")
        clone_args = self._git_clone_args(calls)
        assert "--single-branch" in clone_args

    def test_no_tags_forwarded(self, monorepo: tuple, monkeypatch):
        """--no-tags 应出现在 git clone 参数中。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--no-tags")
        clone_args = self._git_clone_args(calls)
        assert "--no-tags" in clone_args

    def test_no_extra_args_by_default(self, monorepo: tuple, monkeypatch):
        """无额外选项时，git clone 不应含 --depth / --single-branch / --no-tags。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch)
        clone_args = self._git_clone_args(calls)
        assert "--depth" not in clone_args
        assert "--single-branch" not in clone_args
        assert "--no-tags" not in clone_args

    def test_shallow_and_single_branch_combined(self, monorepo: tuple, monkeypatch):
        """--shallow + --single-branch 可同时生效。"""
        _, calls = self._run_with_mock(monorepo, monkeypatch, "--shallow", "--single-branch")
        clone_args = self._git_clone_args(calls)
        assert "--depth" in clone_args
        assert "--single-branch" in clone_args

    def test_invalid_jobs_value(self, monorepo: tuple, monkeypatch):
        """--jobs 传非整数应报错。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--jobs", "abc"])
        assert result.exit_code != 0

    def test_invalid_depth_value(self, monorepo: tuple, monkeypatch):
        """--depth 传非整数应报错。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--depth", "notanumber"])
        assert result.exit_code != 0


# ── 集成回归：真实本地 clone ────────────────────────────────────


class TestCloneCliIntegration:
    """使用本地 bare repo 跑真实 clone，验证新参数的端到端行为。"""

    def test_shallow_clone_via_cli(self, monorepo: tuple, monkeypatch):
        """通过 CLI --shallow 实际 clone 后，历史应只有 1 个 commit。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--shallow"], catch_exceptions=False)

        assert result.exit_code == 0, f"CLI 失败:\n{result.output}"
        target = root / "sub" / "repo-a"
        assert (target / ".git").exists()
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=target, capture_output=True, text=True
        )
        assert len(log.stdout.strip().splitlines()) == 1

    def test_full_clone_via_cli(self, monorepo: tuple, monkeypatch):
        """无 --shallow 时，完整历史（5 个 commit）应全部拉取。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone"], catch_exceptions=False)

        assert result.exit_code == 0, f"CLI 失败:\n{result.output}"
        target = root / "sub" / "repo-a"
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=target, capture_output=True, text=True
        )
        assert len(log.stdout.strip().splitlines()) == 5

    def test_depth_2_via_cli(self, monorepo: tuple, monkeypatch):
        """--depth 2 应只有 2 个 commit。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--depth", "2"], catch_exceptions=False)

        assert result.exit_code == 0
        target = root / "sub" / "repo-a"
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=target, capture_output=True, text=True
        )
        assert len(log.stdout.strip().splitlines()) == 2

    def test_parallel_clone_jobs_4(self, multi_repo_monorepo: tuple, monkeypatch):
        """--jobs 4 应能并行 clone 3 个仓库，全部成功。"""
        root, _ = multi_repo_monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--jobs", "4"], catch_exceptions=False)

        assert result.exit_code == 0, f"并行 clone 失败:\n{result.output}"
        for i in range(3):
            target = root / "sub" / f"repo-{i}"
            assert (target / ".git").exists(), f"repo-{i} 应已被 clone"

    def test_parallel_shallow_clone(self, multi_repo_monorepo: tuple, monkeypatch):
        """--shallow --jobs 4 组合：并行浅克隆所有仓库。"""
        root, _ = multi_repo_monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--shallow", "--jobs", "4"], catch_exceptions=False)

        assert result.exit_code == 0
        for i in range(3):
            target = root / "sub" / f"repo-{i}"
            assert (target / ".git").exists()
            log = subprocess.run(
                ["git", "log", "--oneline"], cwd=target, capture_output=True, text=True
            )
            assert len(log.stdout.strip().splitlines()) == 1, f"repo-{i} 应只有 1 个 commit"

    def test_skip_already_cloned_repos(self, monorepo: tuple, monkeypatch):
        """已存在的仓库应被跳过（即使加了 --shallow）。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()

        runner.invoke(main, ["clone"], catch_exceptions=False)
        target = root / "sub" / "repo-a"
        assert (target / ".git").exists()

        result = runner.invoke(main, ["clone", "--shallow"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "跳过" in result.output

    def test_output_contains_depth_hint(self, monorepo: tuple, monkeypatch):
        """使用 --depth 时，输出应显示 depth 提示信息。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--depth", "1"], catch_exceptions=False)
        assert "depth=1" in result.output

    def test_output_contains_filter_hint(self, monorepo: tuple, monkeypatch):
        """使用 --git-filter 时，输出应显示 filter 提示信息。"""
        root, _ = monorepo
        monkeypatch.chdir(root)
        runner = CliRunner()
        result = runner.invoke(main, ["clone", "--git-filter", "blob:none"], catch_exceptions=False)
        assert "filter=blob:none" in result.output
