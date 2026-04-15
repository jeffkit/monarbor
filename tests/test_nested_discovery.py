"""测试 walk_monorepos / find_nested_monorepos 在嵌套逻辑大仓场景下的正确性。

对应 PR 中的 3 个问题场景：
  场景 1 — clone -r（未 clone）：只处理直接注册子仓，不发现子目录分仓
  场景 2 — clone -r（已 clone）：跳过后不递归（纯 cli 层 bug，walk_monorepos 层面
           体现不出来，通过实际 monarbor clone -r 命令验证覆盖）
  场景 3 — pull/status/list -r：发现不了嵌套大仓的 mona.yaml

测试用例：
  test_walk_discovers_nested_monorepo_and_subdir_mona — 场景 3 核心：walk_monorepos 能进入已注册 repo 发现其内部子目录分仓
  test_walk_chain_nesting_arbitrary_depth            — 场景 1 核心：链式直接注册子仓递归到任意深度
  test_walk_no_duplicate_configs                     — 场景 3 补充：来源 1 和来源 2 不产出重复
  test_find_nested_excludes_exact_path_not_parent    — 场景 3 基础：精确路径排除，不误排除整个父目录
"""

from __future__ import annotations

from pathlib import Path

import yaml

from monarbor.config import find_nested_monorepos, walk_monorepos


def _write_mona(path: Path, name: str, repos: list[dict] | None = None) -> None:
    """在 path 下写入 mona.yaml。"""
    path.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "owner": "test", "repos": repos or []}
    (path / "mona.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _fake_git(path: Path) -> None:
    """在 path 下创建 .git 目录，模拟已 clone 的仓库。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir(exist_ok=True)


# ────────────────────────────────────────────────────────────────
# 场景 3：walk_monorepos 能进入已注册 repo，发现其内部子目录分仓
# ────────────────────────────────────────────────────────────────

def test_walk_discovers_nested_monorepo_and_subdir_mona(tmp_path: Path):
    """所有直接注册子仓路径共享同一前缀目录时，walk_monorepos -r 应能
    进入已注册 repo（platform），发现 platform 的 mona.yaml 以及
    platform 内部子目录分仓（users）的 mona.yaml。

    对应场景：pull/status/list -r 发现不了嵌套大仓的 mona.yaml。"""

    # root 的直接注册子仓都在 projects/ 下
    _write_mona(tmp_path, "Root", repos=[
        {"path": "projects/svc-a", "name": "SvcA", "repo_url": "git@example.com:svc-a.git"},
        {"path": "projects/platform", "name": "Platform", "repo_url": "git@example.com:platform.git"},
    ])

    # platform 是已 clone 的嵌套大仓
    platform = tmp_path / "projects" / "platform"
    _fake_git(platform)
    _write_mona(platform, "Platform Monorepo", repos=[
        {"path": "core", "name": "Core", "repo_url": "git@example.com:core.git"},
    ])

    # platform 内部的子目录分仓（无 repo_url，有自己的 mona.yaml）
    _write_mona(platform / "users", "User Domain", repos=[
        {"path": "user-svc", "name": "UserSvc", "repo_url": "git@example.com:user-svc.git"},
    ])

    configs = list(walk_monorepos(tmp_path, recursive=True))
    names = [c.name for c in configs]

    assert "Root" in names
    assert "Platform Monorepo" in names
    assert "User Domain" in names
    assert len(configs) == 3


# ────────────────────────────────────────────────────────────────
# 场景 1：链式直接注册子仓递归到任意深度
# ────────────────────────────────────────────────────────────────

def test_walk_chain_nesting_arbitrary_depth(tmp_path: Path):
    """每层大仓注册下一层作为直接注册子仓（有 repo_url），
    walk_monorepos -r 应能逐层递归发现全部配置。

    对应场景：clone -r（未 clone）只处理一层嵌套。"""

    _write_mona(tmp_path, "L0", repos=[
        {"path": "a", "name": "A", "repo_url": "git@example.com:a.git"},
    ])
    a = tmp_path / "a"
    _fake_git(a)
    _write_mona(a, "L1", repos=[
        {"path": "b", "name": "B", "repo_url": "git@example.com:b.git"},
    ])
    b = a / "b"
    _fake_git(b)
    _write_mona(b, "L2", repos=[
        {"path": "c", "name": "C", "repo_url": "git@example.com:c.git"},
    ])
    c = b / "c"
    _fake_git(c)
    _write_mona(c, "L3", repos=[
        {"path": "svc", "name": "Svc", "repo_url": ""},
    ])

    configs = list(walk_monorepos(tmp_path, recursive=True))
    names = [c.name for c in configs]

    assert names == ["L0", "L1", "L2", "L3"]


# ────────────────────────────────────────────────────────────────
# 场景 3 补充：来源 1 和来源 2 不产出重复
# ────────────────────────────────────────────────────────────────

def test_walk_no_duplicate_configs(tmp_path: Path):
    """直接注册子仓内含嵌套 mona.yaml + 子目录也有 mona.yaml 时，
    walk_monorepos 的来源 1（进入已注册 repo）和来源 2（文件扫描）
    不应产出重复的配置条目。"""

    _write_mona(tmp_path, "Root", repos=[
        {"path": "projects/nested-repo", "name": "NestedRepo", "repo_url": "git@example.com:nested.git"},
    ])

    nested = tmp_path / "projects" / "nested-repo"
    _fake_git(nested)
    _write_mona(nested, "Nested Monorepo", repos=[])

    # nested-repo 下的子目录分仓
    _write_mona(nested / "domain-a", "DomainA", repos=[])

    configs = list(walk_monorepos(tmp_path, recursive=True))
    names = [c.name for c in configs]

    assert names.count("Nested Monorepo") == 1
    assert names.count("DomainA") == 1
    assert len(configs) == 3  # Root, Nested Monorepo, DomainA


# ────────────────────────────────────────────────────────────────
# 场景 3 基础：精确路径排除
# ────────────────────────────────────────────────────────────────

def test_find_nested_excludes_exact_path_not_parent(tmp_path: Path):
    """排除 projects/repo-a 的精确路径时，不应排除同级的 projects/repo-b。
    这是场景 3 修复的基础——旧代码排除 \"projects\" 目录名导致整个目录不可达。"""

    _write_mona(tmp_path, "Root")

    repo_a = tmp_path / "projects" / "repo-a"
    repo_a.mkdir(parents=True)
    _write_mona(repo_a, "RepoA")

    repo_b = tmp_path / "projects" / "repo-b"
    repo_b.mkdir(parents=True)
    _write_mona(repo_b, "RepoB")

    # 只排除 repo-a 的精确路径
    exclude = {str(repo_a.resolve())}
    nested = find_nested_monorepos(tmp_path, exclude_paths=exclude)
    nested_resolved = {str(n.resolve()) for n in nested}

    assert str(repo_b.resolve()) in nested_resolved
    assert str(repo_a.resolve()) not in nested_resolved
