"""嵌套大仓扫描安全性回归（对应 docs/MONARBOR_NOTES.md §3 / §6.2）。

守护两类缺陷：
  缺陷 A — find_nested_monorepos 不剪枝、跟随软链、无深度上限，撞上软链环时
           以 ``OSError [Errno 63] File name too long`` 崩溃；
  缺陷 B — list_repos 漏传 exclude_paths，无条件递归进入已注册子仓。

⚠️ 软链环必须用**长段名**构造（``node_modules/@scope/some-long-package-name``）。
短段名会在路径长度撞上 PATH_MAX 之前先撞 ELOOP（~32 次软链解析）而自然收敛，
修复前也照样通过，是「假守卫」——见 MONARBOR_NOTES §3.1。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from monarbor.cli import main
from monarbor.config import MAX_SCAN_DEPTH, SKIP_SCAN_DIRS, find_nested_monorepos, walk_monorepos

# 长段名：每层路径增长约 109 字符（21 + 段名长度）。
# 实测校准（macOS，PATH_MAX=1024，ELOOP 约 16 次软链解析）：
#   `some-long-package-name`（23 字符，增长 ~44）修复前也**不崩** ——
#   ELOOP 先在路径长度 755 处收敛，是「假守卫」；
#   本段名（88 字符，增长 ~109）修复前必崩 `OSError [Errno 63]`，
#   且增长 >102 足以在 Linux（PATH_MAX=4096、ELOOP=40）上同样先撞 PATH_MAX。
LONG_SEGMENT = "some-extremely-long-package-name-to-force-path-max-before-eloop-in-scan-regression-tests"


def _write_mona(path: Path, name: str, repos: list | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "owner": "test", "repos": repos or []}
    (path / "mona.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _make_long_name_loop(base: Path) -> None:
    """构造长段名二元软链环：loop-a 的 node_modules 软链到 loop-b，反之亦然。"""
    loop_a = base / "loop-a"
    loop_b = base / "loop-b"
    for holder, other in ((loop_a, loop_b), (loop_b, loop_a)):
        link_dir = holder / "node_modules" / "@scope"
        link_dir.mkdir(parents=True, exist_ok=True)
        (link_dir / LONG_SEGMENT).symlink_to(other, target_is_directory=True)


def _fake_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir(exist_ok=True)


# 1 ── 长段名软链环不得崩溃（修复前 bring down 扫描）


def test_long_name_symlink_loop_does_not_crash(tmp_path: Path):
    _make_long_name_loop(tmp_path)
    # 修复前：跟随软链 → 无限递归 → OSError [Errno 63]
    assert find_nested_monorepos(tmp_path) == []


# 2 ── 已注册子仓内含软链环时 list 不得崩溃（缺陷 B 的最小复现）


def test_list_does_not_crash_when_registered_repo_has_symlink_loop(tmp_path: Path, monkeypatch):
    _write_mona(tmp_path, "Root", repos=[
        {"path": "deepseek-harness", "name": "DSH", "repo_url": "git@example.com:dsh.git"},
    ])
    repo = tmp_path / "deepseek-harness"
    _fake_git(repo)
    _make_long_name_loop(repo)

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["list"])

    assert result.exit_code == 0, result.output
    assert "DSH" in result.output


# 3 ── walk_monorepos -r 同样不得崩溃


def test_walk_monorepos_recursive_does_not_crash_on_symlink_loop(tmp_path: Path):
    _write_mona(tmp_path, "Root", repos=[
        {"path": "nested-hub", "name": "NestedHub", "repo_url": "git@example.com:hub.git"},
    ])
    nested = tmp_path / "nested-hub"
    _fake_git(nested)
    _write_mona(nested, "Nested Monorepo")
    _make_long_name_loop(nested)

    configs = list(walk_monorepos(tmp_path, recursive=True))
    names = [c.name for c in configs]
    assert names == ["Root", "Nested Monorepo"]


# 4 ── 依赖目录 / vendor 被剪枝


def test_dependency_and_vendor_dirs_are_pruned(tmp_path: Path):
    for skip_dir in sorted(SKIP_SCAN_DIRS):
        _write_mona(tmp_path / skip_dir / "pkg", f"Hidden-{skip_dir}")

    assert find_nested_monorepos(tmp_path) == []


# 5 ── 超过 MAX_SCAN_DEPTH 不再下探


def test_beyond_max_scan_depth_not_descended(tmp_path: Path):
    deep = tmp_path
    for i in range(MAX_SCAN_DEPTH + 5):
        deep = deep / f"d{i}"
    _write_mona(deep, "TooDeep")

    assert find_nested_monorepos(tmp_path) == []

    # 对照：浅层普通子目录仍能发现
    _write_mona(tmp_path / "shallow", "Shallow")
    assert [p.name for p in find_nested_monorepos(tmp_path)] == ["shallow"]


# 6 ── 普通子目录仍能被正常发现（不误伤主功能）


def test_regular_nested_monorepo_still_discovered(tmp_path: Path):
    _write_mona(tmp_path / "platform" / "users", "UserDomain")

    found = find_nested_monorepos(tmp_path)
    assert [p.name for p in found] == ["users"]


# 7 ── 排除集是精确绝对路径（不误伤共享前缀的兄弟目录）


def test_exclude_paths_match_exact_abs_path_not_sibling_prefix(tmp_path: Path):
    _write_mona(tmp_path / "projects" / "app", "App")
    _write_mona(tmp_path / "projects" / "app-extra", "AppExtra")

    exclude = {str((tmp_path / "projects" / "app").resolve())}
    found = {p.name for p in find_nested_monorepos(tmp_path, exclude_paths=exclude)}

    assert found == {"app-extra"}


# 8 ── 不跟随符号链接（软链指向的目录不被当作嵌套大仓）


def test_symlinked_directory_not_treated_as_nested_monorepo(tmp_path: Path):
    outside = tmp_path / "outside" / "linked-pkg"
    _write_mona(outside, "LinkedPkg")

    root = tmp_path / "root"
    root.mkdir()
    (root / "linked-pkg").symlink_to(outside, target_is_directory=True)

    # 修复前：is_dir() 跟随软链 → 会把 root/linked-pkg 当成嵌套大仓
    assert find_nested_monorepos(root) == []
