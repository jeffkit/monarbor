"""monorepo.yaml 配置的加载与解析。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

CONFIG_FILENAME = "monorepo.yaml"


@dataclass
class RepoDef:
    """一个仓库的定义。"""

    path: str
    name: str
    repo_url: str
    description: str = ""
    tech_stack: list[str] = field(default_factory=list)
    branches: dict[str, str] = field(default_factory=dict)

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
        repos = [RepoDef(**r) for r in data.get("repos", [])]
        return cls(
            name=data.get("name", ""),
            owner=data.get("owner", ""),
            description=data.get("description", ""),
            root=root.resolve(),
            repos=repos,
        )


def find_nested_monorepos(root: Path, exclude_paths: set[str] | None = None) -> list[Path]:
    """扫描子目录，找到所有嵌套的逻辑大仓。"""
    nested = []
    exclude = exclude_paths or set()
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in exclude:
            continue
        config = entry / CONFIG_FILENAME
        if config.exists():
            nested.append(entry)
        else:
            nested.extend(find_nested_monorepos(entry, exclude))
    return nested


def walk_monorepos(root: Path, recursive: bool = False) -> Iterator[MonorepoConfig]:
    """遍历当前大仓，可选递归加载嵌套大仓。"""
    config = MonorepoConfig.load(root)
    yield config

    if recursive:
        repo_paths = {r.path.split("/")[0] for r in config.repos}
        for nested_root in find_nested_monorepos(root, exclude_paths=repo_paths):
            yield from walk_monorepos(nested_root, recursive=True)
