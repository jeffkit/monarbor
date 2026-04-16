"""Unit + integration 测试：CloneOptions 参数正确翻译到 git 命令。

单元层：mock subprocess.run，断言 git 命令行参数组装正确。
集成层：使用本地 bare repo，跑真实 clone，验证行为符合预期。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from monarbor.git_ops import CloneOptions, clone, clone_into_existing


# ── 单元测试：验证参数拼装 ──────────────────────────────────────


class TestCloneOptionsArgAssembly:
    """验证 CloneOptions 的各字段被正确翻译成 git clone 参数。"""

    def _captured_args(self, mock_run: MagicMock) -> list[str]:
        """从 mock 调用中提取传给 git 的参数列表。"""
        return mock_run.call_args_list[0][0][0]

    @patch("monarbor.git_ops.subprocess.run")
    def test_no_options_baseline(self, mock_run: MagicMock, tmp_path: Path):
        """无额外选项时，只有 git clone <url> <target>。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst")
        args = self._captured_args(mock_run)
        assert args == ["git", "clone", "git@example.com/repo.git", str(tmp_path / "dst")]

    @patch("monarbor.git_ops.subprocess.run")
    def test_depth_option(self, mock_run: MagicMock, tmp_path: Path):
        """--depth N 应出现在 git clone 参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions(depth=1))
        args = self._captured_args(mock_run)
        assert "--depth" in args
        assert args[args.index("--depth") + 1] == "1"

    @patch("monarbor.git_ops.subprocess.run")
    def test_filter_option(self, mock_run: MagicMock, tmp_path: Path):
        """--filter=blob:none 应出现在 git clone 参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions(filter="blob:none"))
        args = self._captured_args(mock_run)
        assert "--filter=blob:none" in args

    @patch("monarbor.git_ops.subprocess.run")
    def test_single_branch_option(self, mock_run: MagicMock, tmp_path: Path):
        """--single-branch 应出现在 git clone 参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions(single_branch=True))
        args = self._captured_args(mock_run)
        assert "--single-branch" in args

    @patch("monarbor.git_ops.subprocess.run")
    def test_no_tags_option(self, mock_run: MagicMock, tmp_path: Path):
        """--no-tags 应出现在 git clone 参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions(no_tags=True))
        args = self._captured_args(mock_run)
        assert "--no-tags" in args

    @patch("monarbor.git_ops.subprocess.run")
    def test_combined_options(self, mock_run: MagicMock, tmp_path: Path):
        """多个选项可以同时生效。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        opts = CloneOptions(depth=1, single_branch=True, no_tags=True)
        clone("git@example.com/repo.git", tmp_path / "dst", branch="main", options=opts)
        args = self._captured_args(mock_run)
        assert "-b" in args and args[args.index("-b") + 1] == "main"
        assert "--depth" in args
        assert "--single-branch" in args
        assert "--no-tags" in args

    @patch("monarbor.git_ops.subprocess.run")
    def test_timeout_is_forwarded(self, mock_run: MagicMock, tmp_path: Path):
        """自定义 timeout 应传递给 subprocess.run。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions(timeout=600))
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 600

    @patch("monarbor.git_ops.subprocess.run")
    def test_default_timeout_is_300(self, mock_run: MagicMock, tmp_path: Path):
        """不传 options 时，默认超时应为 300s。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst")
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 300

    @patch("monarbor.git_ops.subprocess.run")
    def test_false_flags_not_in_args(self, mock_run: MagicMock, tmp_path: Path):
        """默认关闭的 flag 不应出现在命令行参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        clone("git@example.com/repo.git", tmp_path / "dst", options=CloneOptions())
        args = self._captured_args(mock_run)
        assert "--single-branch" not in args
        assert "--no-tags" not in args
        assert "--depth" not in args


# ── clone_into_existing 单元测试 ────────────────────────────────


class TestCloneIntoExistingOptionsArgAssembly:
    """验证 clone_into_existing 的 CloneOptions 正确传递给 git fetch。"""

    def _fetch_call_args(self, mock_run: MagicMock) -> list[str]:
        """找到所有 git fetch 调用中的参数列表。"""
        for c in mock_run.call_args_list:
            args = c[0][0]
            if len(args) > 1 and args[1] == "fetch":
                return args
        return []

    @patch("monarbor.git_ops.subprocess.run")
    def test_depth_in_fetch(self, mock_run: MagicMock, tmp_path: Path):
        """--depth 应出现在 git fetch 参数中（而不是 init/checkout）。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="main", stderr="")
        target = tmp_path / "dst"
        target.mkdir()
        clone_into_existing("git@example.com/repo.git", target, branch="main", options=CloneOptions(depth=3))
        fetch_args = self._fetch_call_args(mock_run)
        assert "--depth" in fetch_args
        assert fetch_args[fetch_args.index("--depth") + 1] == "3"

    @patch("monarbor.git_ops.subprocess.run")
    def test_no_tags_in_fetch(self, mock_run: MagicMock, tmp_path: Path):
        """--no-tags 应出现在 git fetch 参数中。"""
        mock_run.return_value = MagicMock(returncode=0, stdout="main", stderr="")
        target = tmp_path / "dst"
        target.mkdir()
        clone_into_existing("git@example.com/repo.git", target, options=CloneOptions(no_tags=True))
        fetch_args = self._fetch_call_args(mock_run)
        assert "--no-tags" in fetch_args


# ── 集成测试：使用本地 bare repo ───────────────────────────────


class TestCloneIntegration:
    """使用真实本地 git 仓库验证 CloneOptions 的行为。"""

    def test_shallow_clone_depth_1(self, bare_repo: tuple, tmp_path: Path):
        """--depth 1 应只有 1 个提交，而非全量历史（5 个提交）。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch, options=CloneOptions(depth=1))

        assert result.ok, f"shallow clone 失败: {result.error}"
        assert (target / ".git").exists()
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target, capture_output=True, text=True,
        )
        commit_count = len(log.stdout.strip().splitlines())
        assert commit_count == 1, f"depth=1 应只有 1 个 commit，实际有 {commit_count} 个"

    def test_shallow_clone_depth_3(self, bare_repo: tuple, tmp_path: Path):
        """--depth 3 应有不超过 3 个提交。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch, options=CloneOptions(depth=3))

        assert result.ok, f"shallow clone 失败: {result.error}"
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target, capture_output=True, text=True,
        )
        commit_count = len(log.stdout.strip().splitlines())
        assert commit_count <= 3, f"depth=3 应最多 3 个 commit，实际有 {commit_count} 个"

    def test_full_clone_has_all_commits(self, bare_repo: tuple, tmp_path: Path):
        """无 --depth 时应拉取完整历史（5 个提交）。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch)

        assert result.ok, f"full clone 失败: {result.error}"
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target, capture_output=True, text=True,
        )
        commit_count = len(log.stdout.strip().splitlines())
        assert commit_count == 5, f"full clone 应有 5 个 commit，实际有 {commit_count} 个"

    def test_single_branch_clone(self, bare_repo: tuple, tmp_path: Path):
        """--single-branch clone 后仓库应包含文件且 clone 成功。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch, options=CloneOptions(single_branch=True))

        assert result.ok, f"single-branch clone 失败: {result.error}"
        assert (target / "file0.txt").exists()

    def test_no_tags_clone_has_no_tags(self, bare_repo: tuple, tmp_path: Path):
        """--no-tags clone 后仓库不应包含 tag（bare repo 本无 tag，确保不会额外引入）。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch, options=CloneOptions(no_tags=True))

        assert result.ok, f"no-tags clone 失败: {result.error}"
        tags = subprocess.run(
            ["git", "tag"],
            cwd=target, capture_output=True, text=True,
        )
        assert tags.stdout.strip() == "", "no-tags clone 后不应有 tag"

    def test_clone_into_existing_with_shallow(self, bare_repo: tuple, tmp_path: Path):
        """clone_into_existing 支持 --depth 1 浅克隆。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"
        target.mkdir()
        (target / "mona.yaml").write_text("name: test\n")

        result = clone_into_existing(str(remote), target, branch=branch, options=CloneOptions(depth=1))

        assert result.ok, f"shallow clone_into_existing 失败: {result.error}"
        assert (target / "mona.yaml").exists(), "原有文件应被保留"
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target, capture_output=True, text=True,
        )
        commit_count = len(log.stdout.strip().splitlines())
        assert commit_count == 1, f"depth=1 应只有 1 个 commit，实际有 {commit_count} 个"

    def test_timeout_respected_on_fast_clone(self, bare_repo: tuple, tmp_path: Path):
        """使用一个大 timeout 值，本地快速 clone 应正常完成而不超时。"""
        remote, branch = bare_repo
        target = tmp_path / "dst"

        result = clone(str(remote), target, branch=branch, options=CloneOptions(timeout=120))

        assert result.ok, f"clone 超时或失败: {result.error}"

    def test_clone_options_default_is_none(self):
        """CloneOptions 默认值：depth/filter 为 None，flag 为 False，timeout 为 300。"""
        opts = CloneOptions()
        assert opts.depth is None
        assert opts.filter is None
        assert opts.single_branch is False
        assert opts.no_tags is False
        assert opts.timeout == 300
