"""mona.yaml 配置的加载与解析。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

CONFIG_FILENAME = "mona.yaml"
LOCAL_CONFIG_FILENAME = "mona.local.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 优先。"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_local_overrides(
    repos: list[dict], local_repos: list[dict],
) -> tuple[list[dict], set[str]]:
    """按 path 匹配并合并 local 覆盖。返回 (合并后的列表, 被覆盖的 path 集合)。"""
    local_map = {r["path"]: r for r in local_repos if "path" in r}
    merged = []
    overridden_paths: set[str] = set()
    for repo in repos:
        override = local_map.get(repo.get("path", ""))
        if override:
            merged.append(_deep_merge(repo, override))
            overridden_paths.add(repo["path"])
        else:
            merged.append(repo)
    return merged, overridden_paths


@dataclass
class RepoDef:
    """一个仓库的定义。"""

    path: str
    name: str
    repo_url: str
    description: str = ""
    tech_stack: list[str] = field(default_factory=list)
    branches: dict[str, str] = field(default_factory=dict)
    has_local_override: bool = False

    @property
    def dev_branch(self) -> str:
        return self.branches.get("dev", "develop")

    @property
    def test_branch(self) -> str:
        return self.branches.get("test", "release/test")

    @property
    def prod_branch(self) -> str:
        return self.branches.get("prod", "main")


@dataclass
class MonorepoConfig:
    """一个逻辑大仓的配置。"""

    name: str
    owner: str
    root: Path
    description: str = ""
    repos: list[RepoDef] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> MonorepoConfig:
        config_path = root / CONFIG_FILENAME
        if not config_path.exists():
            raise FileNotFoundError(f"未找到配置文件: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_repos = data.get("repos", [])
        overridden_paths: set[str] = set()

        local_path = root / LOCAL_CONFIG_FILENAME
        if local_path.exists():
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = yaml.safe_load(f) or {}
            local_repos = local_data.get("repos", [])
            if local_repos:
                raw_repos, overridden_paths = _apply_local_overrides(raw_repos, local_repos)

        repos = []
        for r in raw_repos:
            rd = RepoDef(
                path=r.get("path", ""),
                name=r.get("name", ""),
                repo_url=r.get("repo_url", ""),
                description=r.get("description", ""),
                tech_stack=r.get("tech_stack", []),
                branches=r.get("branches", {}),
                has_local_override=r.get("path", "") in overridden_paths,
            )
            repos.append(rd)

        return cls(
            name=data.get("name", ""),
            owner=data.get("owner", ""),
            description=data.get("description", ""),
            root=root.resolve(),
            repos=repos,
        )


def find_nested_monorepos(root: Path, exclude_paths: set[str] | None = None) -> list[Path]:
    """扫描子目录，找到所有嵌套的逻辑大仓。

    exclude_paths 为绝对路径集合，匹配时使用精确路径比较（而非目录名）。
    """
    nested = []
    exclude = exclude_paths or set()
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if str(entry.resolve()) in exclude:
            continue
        config = entry / CONFIG_FILENAME
        if config.exists():
            nested.append(entry)
        else:
            nested.extend(find_nested_monorepos(entry, exclude))
    return nested


def walk_monorepos(root: Path, recursive: bool = False) -> Iterator[MonorepoConfig]:
    """遍历当前大仓，可选递归加载嵌套大仓。

    递归发现嵌套大仓来自两个来源：
    1. 已注册的 repo 目录自身含 mona.yaml → 作为嵌套大仓递归
    2. 文件系统扫描发现的、未被注册为 repo 的目录含 mona.yaml
    """
    config = MonorepoConfig.load(root)
    yield config

    if recursive:
        # 收集已注册 repo 的精确绝对路径（用于 find_nested_monorepos 排除）
        repo_abs_paths: set[str] = set()
        # 已经通过 repo 递归处理过的路径（防止 find_nested 重复发现）
        visited: set[str] = set()

        # 来源 1：已注册 repo 自身含 mona.yaml
        for repo in config.repos:
            repo_dir = config.root / repo.path
            repo_abs = str(repo_dir.resolve())
            repo_abs_paths.add(repo_abs)
            if repo_dir.is_dir() and (repo_dir / CONFIG_FILENAME).exists():
                visited.add(repo_abs)
                yield from walk_monorepos(repo_dir, recursive=True)

        # 来源 2：文件系统扫描（排除已注册 repo 的精确路径，避免重复）
        for nested_root in find_nested_monorepos(root, exclude_paths=repo_abs_paths | visited):
            if str(nested_root.resolve()) not in visited:
                yield from walk_monorepos(nested_root, recursive=True)
