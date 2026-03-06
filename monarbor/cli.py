"""Monarbor 命令行入口。"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree as RichTree

from . import __version__
from .config import CONFIG_FILENAME, MonorepoConfig, RepoDef, find_nested_monorepos, walk_monorepos
from .git_ops import (
    ahead_behind,
    checkout,
    clone,
    current_branch,
    fetch,
    is_dirty,
    pull,
    run_in_repo,
)

console = Console()


def find_root(start: Path | None = None) -> Path:
    """向上查找最近的 monorepo.yaml 所在目录。"""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / CONFIG_FILENAME).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise click.ClickException(f"未找到 {CONFIG_FILENAME}，请在逻辑大仓目录下运行，或使用 monarbor init 初始化")


@click.group()
@click.version_option(__version__, prog_name="monarbor")
def main():
    """Monarbor - AI 友好的逻辑大仓命令行工具"""
    pass


# ── monarbor clone ───────────────────────────────────────────


@main.command(name="clone")
@click.option("-r", "--recursive", is_flag=True, help="递归 clone 嵌套的子逻辑大仓")
@click.option("-b", "--branch-type", type=click.Choice(["dev", "test", "prod"]), default="dev", help="clone 哪个分支类型 (默认 dev)")
@click.option("--filter", "path_filter", default=None, help="只 clone 路径前缀匹配的仓库 (如 business-a)")
def clone_repos(recursive: bool, branch_type: str, path_filter: str | None):
    """拉取大仓下所有项目代码。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))
    total, success, skipped = 0, 0, 0

    for config in configs:
        if config.root != root:
            console.rule(f"[bold]嵌套大仓: {config.name}[/bold] ({config.root.relative_to(root)})")

        for repo in config.repos:
            if path_filter and not repo.path.startswith(path_filter):
                continue
            total += 1
            target = config.root / repo.path
            if target.exists() and (target / ".git").exists():
                console.print(f"  [dim]跳过[/dim] {repo.path} (已存在)")
                skipped += 1
                continue

            branch = repo.branches.get(branch_type)
            console.print(f"  [cyan]克隆[/cyan] {repo.name} → {repo.path} [dim](branch: {branch})[/dim]")
            result = clone(repo.repo_url, target, branch=branch)
            if result.ok:
                success += 1
                console.print(f"       [green]✓[/green]")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")

    console.print(f"\n[bold]完成:[/bold] {success} 克隆, {skipped} 跳过, {total - success - skipped} 失败 (共 {total})")


# ── monarbor pull ────────────────────────────────────────────


@main.command(name="pull")
@click.option("-r", "--recursive", is_flag=True, help="递归 pull 嵌套大仓")
def pull_repos(recursive: bool):
    """拉取所有已 clone 仓库的最新代码。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))
    total, success = 0, 0

    for config in configs:
        for repo in config.repos:
            target = config.root / repo.path
            if not (target / ".git").exists():
                continue
            total += 1
            console.print(f"  [cyan]拉取[/cyan] {repo.name} ({repo.path})")
            result = pull(target)
            if result.ok:
                success += 1
                console.print(f"       [green]✓[/green] {result.output or 'Already up to date.'}")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")

    console.print(f"\n[bold]完成:[/bold] {success}/{total} 成功")


# ── monarbor status ──────────────────────────────────────────


@main.command()
@click.option("-r", "--recursive", is_flag=True, help="递归显示嵌套大仓")
@click.option("--fetch/--no-fetch", default=False, help="先 fetch 远端再显示状态")
def status(recursive: bool, fetch: bool):
    """显示所有仓库的当前状态。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))

    table = Table(title="仓库状态")
    table.add_column("项目", style="bold")
    table.add_column("路径", style="dim")
    table.add_column("分支", style="cyan")
    table.add_column("状态")
    table.add_column("同步")

    for config in configs:
        for repo in config.repos:
            target = config.root / repo.path
            rel_path = str(target.relative_to(root))
            if not (target / ".git").exists():
                table.add_row(repo.name, rel_path, "-", "[dim]未 clone[/dim]", "-")
                continue

            if fetch:
                from .git_ops import fetch as git_fetch
                git_fetch(target)

            branch = current_branch(target)
            dirty = is_dirty(target)
            dirty_label = "[red]有改动[/red]" if dirty else "[green]干净[/green]"
            a, b = ahead_behind(target)
            sync_parts = []
            if a:
                sync_parts.append(f"[yellow]↑{a}[/yellow]")
            if b:
                sync_parts.append(f"[yellow]↓{b}[/yellow]")
            sync_label = " ".join(sync_parts) if sync_parts else "[green]同步[/green]"

            table.add_row(repo.name, rel_path, branch, dirty_label, sync_label)

    console.print(table)


# ── monarbor list ────────────────────────────────────────────


@main.command(name="list")
@click.option("-r", "--recursive", is_flag=True, help="递归显示嵌套大仓")
def list_repos(recursive: bool):
    """以树形结构列出所有仓库。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))

    for config in configs:
        tree = RichTree(f"[bold]{config.name}[/bold] [dim]({config.root.relative_to(root) if config.root != root else '.'})[/dim]")
        groups: dict[str, list[RepoDef]] = {}
        for repo in config.repos:
            parts = repo.path.split("/")
            group = parts[0] if len(parts) > 1 else "."
            groups.setdefault(group, []).append(repo)

        for group_name, repos in sorted(groups.items()):
            if group_name == ".":
                for repo in repos:
                    tree.add(f"{repo.name} [dim]{repo.path}[/dim] [cyan]{'|'.join(repo.tech_stack)}[/cyan]")
            else:
                branch = tree.add(f"[bold]{group_name}/[/bold]")
                for repo in repos:
                    sub_path = "/".join(repo.path.split("/")[1:])
                    branch.add(f"{repo.name} [dim]{sub_path}[/dim] [cyan]{'|'.join(repo.tech_stack)}[/cyan]")

        nested = find_nested_monorepos(config.root)
        for n in nested:
            tree.add(f"[bold magenta]📦 {n.name}/[/bold magenta] [dim](嵌套大仓)[/dim]")

        console.print(tree)


# ── monarbor exec ────────────────────────────────────────────


@main.command()
@click.argument("command")
@click.option("-r", "--recursive", is_flag=True, help="递归执行到嵌套大仓")
@click.option("--filter", "path_filter", default=None, help="只在路径前缀匹配的仓库中执行")
def exec_cmd(command: str, recursive: bool, path_filter: str | None):
    """在所有已 clone 的仓库中执行命令。

    示例: monarbor exec "git log --oneline -5"
    """
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))

    for config in configs:
        for repo in config.repos:
            if path_filter and not repo.path.startswith(path_filter):
                continue
            target = config.root / repo.path
            if not (target / ".git").exists():
                continue
            console.rule(f"[bold]{repo.name}[/bold] ({repo.path})")
            result = run_in_repo(target, command)
            if result.output:
                console.print(result.output)
            if result.error:
                console.print(f"[red]{result.error}[/red]")


# ── monarbor checkout ────────────────────────────────────────


@main.command(name="checkout")
@click.argument("branch_type", type=click.Choice(["dev", "test", "prod"]))
@click.option("-r", "--recursive", is_flag=True, help="递归切换嵌套大仓")
@click.option("--filter", "path_filter", default=None, help="只切换路径前缀匹配的仓库")
def checkout_repos(branch_type: str, recursive: bool, path_filter: str | None):
    """将所有仓库切换到指定分支类型 (dev/test/prod)。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))

    for config in configs:
        for repo in config.repos:
            if path_filter and not repo.path.startswith(path_filter):
                continue
            target = config.root / repo.path
            if not (target / ".git").exists():
                continue
            branch = repo.branches.get(branch_type)
            if not branch:
                console.print(f"  [yellow]跳过[/yellow] {repo.name}: 未配置 {branch_type} 分支")
                continue
            console.print(f"  [cyan]切换[/cyan] {repo.name} → {branch}")
            result = checkout(target, branch)
            if result.ok:
                console.print(f"       [green]✓[/green]")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")


# ── monarbor init ────────────────────────────────────────────


@main.command()
@click.option("--name", prompt="大仓名称", help="逻辑大仓名称")
@click.option("--owner", prompt="负责人", help="负责人")
def init(name: str, owner: str):
    """在当前目录初始化一个新的逻辑大仓。"""
    config_path = Path.cwd() / CONFIG_FILENAME
    if config_path.exists():
        raise click.ClickException(f"{CONFIG_FILENAME} 已存在")

    content = f"""name: "{name}"
description: ""
owner: {owner}

repos: []
"""
    config_path.write_text(content, encoding="utf-8")
    console.print(f"[green]✓[/green] 已创建 {CONFIG_FILENAME}")


# ── monarbor add ─────────────────────────────────────────────


@main.command()
@click.option("--path", "repo_path", prompt="仓库路径 (如 business-a/frontend)", help="仓库在大仓中的相对路径")
@click.option("--name", "repo_name", prompt="项目名称", help="项目显示名称")
@click.option("--url", "repo_url", prompt="Git 仓库地址", help="Git 仓库 URL")
@click.option("--dev-branch", default="develop", help="开发分支 (默认 develop)")
@click.option("--test-branch", default="release/test", help="测试分支 (默认 release/test)")
@click.option("--prod-branch", default="main", help="生产分支 (默认 main)")
def add(repo_path: str, repo_name: str, repo_url: str, dev_branch: str, test_branch: str, prod_branch: str):
    """向当前大仓添加一个仓库。"""
    import yaml

    root = find_root()
    config_path = root / CONFIG_FILENAME
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    repos = data.get("repos", [])
    for r in repos:
        if r.get("path") == repo_path:
            raise click.ClickException(f"路径 {repo_path} 已存在于配置中")

    new_repo = {
        "path": repo_path,
        "name": repo_name,
        "repo_url": repo_url,
        "branches": {
            "dev": dev_branch,
            "test": test_branch,
            "prod": prod_branch,
        },
    }
    repos.append(new_repo)
    data["repos"] = repos

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓[/green] 已添加 {repo_name} ({repo_path})")


if __name__ == "__main__":
    main()
