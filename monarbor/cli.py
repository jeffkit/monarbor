"""Monarbor 命令行入口。"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree as RichTree

from . import __version__
from .config import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME, MonorepoConfig, RepoDef, find_nested_monorepos, walk_monorepos
from .git_ops import (
    ahead_behind,
    checkout,
    clone,
    clone_into_existing,
    current_branch,
    fetch,
    get_remote_url,
    is_dirty,
    list_worktrees,
    pull,
    run_in_repo,
    set_remote_url,
)

console = Console()


def find_root(start: Path | None = None) -> Path:
    """向上查找最近的 mona.yaml 所在目录。"""
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


def _sync_remote_if_needed(repo: RepoDef, target: Path, remote: str = "origin") -> None:
    """检查本地 remote URL 是否与 mona.yaml 一致，不一致则自动更新。"""
    current_url = get_remote_url(target, remote)
    if current_url is None or current_url == repo.repo_url:
        return
    result = set_remote_url(target, repo.repo_url, remote)
    if result.ok:
        console.print(f"  [yellow]同步[/yellow] {repo.path} remote: {current_url} → {repo.repo_url}")
    else:
        console.print(f"  [red]✗[/red] {repo.path} remote 同步失败: {result.error}")


# ── monarbor clone ───────────────────────────────────────────


@main.command(name="clone")
@click.option("-r", "--recursive", is_flag=True, help="递归 clone 嵌套的子逻辑大仓（含嵌套大仓内的所有子仓库）")
@click.option("-b", "--branch-type", type=click.Choice(["dev", "test", "prod"]), default="dev", help="clone 哪个分支类型 (默认 dev)")
@click.option("--filter", "path_filter", default=None, help="只 clone 路径前缀匹配的仓库 (如 business-a)")
def clone_repos(recursive: bool, branch_type: str, path_filter: str | None):
    """拉取大仓下所有项目代码。"""
    root = find_root()
    total, success, skipped = 0, 0, 0

    def _clone_config(config: "MonorepoConfig") -> None:
        nonlocal total, success, skipped
        if config.root != root:
            console.rule(f"[bold]嵌套大仓: {config.name}[/bold] ({config.root.relative_to(root)})")

        for repo in config.repos:
            if path_filter and not repo.path.startswith(path_filter):
                continue
            if not repo.repo_url:
                console.print(f"  [yellow]跳过[/yellow] {repo.name} ({repo.path}) [dim]— repo_url 未配置[/dim]")
                skipped += 1
                continue
            total += 1
            target = config.root / repo.path
            if target.exists() and (target / ".git").exists():
                _sync_remote_if_needed(repo, target)
                console.print(f"  [dim]跳过[/dim] {repo.path} (已存在)")
                skipped += 1
                total -= 1
                # 已存在的 repo 如果自身含嵌套大仓，仍需递归处理
                if recursive and (target / CONFIG_FILENAME).exists():
                    for nested_config in walk_monorepos(target, recursive=True):
                        _clone_config(nested_config)
                continue

            branch = repo.branches.get(branch_type)
            override_tag = " [yellow]⚡local[/yellow]" if repo.has_local_override else ""
            console.print(f"  [cyan]克隆[/cyan] {repo.name} → {repo.path} [dim](branch: {branch})[/dim]{override_tag}")
            if target.exists() and target.is_dir():
                result = clone_into_existing(repo.repo_url, target, branch=branch)
            else:
                result = clone(repo.repo_url, target, branch=branch)
            if result.ok:
                success += 1
                _ensure_in_git_exclude(target, ".worktrees/")
                console.print(f"       [green]✓[/green]")
                # 若该仓库本身也是嵌套大仓，递归 clone 其子仓库（任意深度）
                if recursive and (target / CONFIG_FILENAME).exists():
                    try:
                        for nested_config in walk_monorepos(target, recursive=True):
                            _clone_config(nested_config)
                    except Exception as e:
                        console.print(f"       [yellow]⚠ 无法加载嵌套大仓 {repo.path}: {e}[/yellow]")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")

    # 首先处理顶层大仓
    top_config = MonorepoConfig.load(root)
    _clone_config(top_config)

    # 递归时，还需处理已存在的嵌套大仓（clone 前就已在本地的）
    if recursive:
        repo_abs_paths = {str((root / r.path).resolve()) for r in top_config.repos}
        for nested_root in find_nested_monorepos(root, exclude_paths=repo_abs_paths):
            try:
                nested_config = MonorepoConfig.load(nested_root)
                _clone_config(nested_config)
            except Exception as e:
                console.print(f"  [yellow]⚠ 无法加载嵌套大仓 {nested_root}: {e}[/yellow]")

    console.print(f"\n[bold]完成:[/bold] {success} 克隆, {skipped} 跳过, {total - success} 失败 (共 {total})")


# ── monarbor pull ────────────────────────────────────────────


@main.command(name="pull")
@click.option("-r", "--recursive", is_flag=True, help="递归 pull 嵌套大仓（含嵌套大仓内的所有子仓库）")
@click.option("--clone-missing", is_flag=True, help="对未 clone 的仓库自动执行 clone")
@click.option("-b", "--branch-type", type=click.Choice(["dev", "test", "prod"]), default="dev", help="clone 缺失仓库时使用的分支类型 (默认 dev，与 --clone-missing 配合使用)")
def pull_repos(recursive: bool, clone_missing: bool, branch_type: str):
    """拉取所有已 clone 仓库的最新代码。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))
    total, success, missing = 0, 0, 0

    for config in configs:
        if config.root != root:
            console.rule(f"[bold]嵌套大仓: {config.name}[/bold] ({config.root.relative_to(root)})")
        for repo in config.repos:
            target = config.root / repo.path
            if not (target / ".git").exists():
                if clone_missing and repo.repo_url:
                    total += 1
                    branch = repo.branches.get(branch_type)
                    console.print(f"  [cyan]克隆[/cyan] {repo.name} ({repo.path}) [dim](branch: {branch})[/dim]")
                    if target.exists() and target.is_dir():
                        result = clone_into_existing(repo.repo_url, target, branch=branch)
                    else:
                        result = clone(repo.repo_url, target, branch=branch)
                    if result.ok:
                        success += 1
                        _ensure_in_git_exclude(target, ".worktrees/")
                        console.print(f"       [green]✓[/green]")
                    else:
                        console.print(f"       [red]✗ {result.error}[/red]")
                else:
                    missing += 1
                    url_hint = "" if repo.repo_url else " [dim](repo_url 未配置)[/dim]"
                    console.print(f"  [dim]未 clone[/dim] {repo.name} ({repo.path}){url_hint}")
                continue
            total += 1
            console.print(f"  [cyan]拉取[/cyan] {repo.name} ({repo.path})")
            result = pull(target)
            if result.ok:
                success += 1
                console.print(f"       [green]✓[/green] {result.output or '已经是最新的。'}")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")

    if missing:
        console.print(f"\n[bold]完成:[/bold] {success}/{total} 成功, [yellow]{missing} 个仓库未 clone[/yellow]（运行 monarbor clone 或 monarbor pull --clone-missing 来补全）")
    else:
        console.print(f"\n[bold]完成:[/bold] {success}/{total} 成功")


# ── monarbor status ──────────────────────────────────────────


@main.command()
@click.option("-r", "--recursive", is_flag=True, help="递归显示嵌套大仓")
@click.option("--fetch/--no-fetch", default=False, help="先 fetch 远端再显示状态")
@click.option("--check-worktrees", is_flag=True, help="同时显示各仓库的活跃 worktree")
def status(recursive: bool, fetch: bool, check_worktrees: bool):
    """显示所有仓库的当前状态。"""
    root = find_root()
    configs = list(walk_monorepos(root, recursive=recursive))

    table = Table(title="仓库状态")
    table.add_column("项目", style="bold")
    table.add_column("路径", style="dim")
    table.add_column("分支", style="cyan")
    table.add_column("状态")
    table.add_column("同步")
    if check_worktrees:
        table.add_column("Worktrees")

    for config in configs:
        for repo in config.repos:
            target = config.root / repo.path
            rel_path = str(target.relative_to(root))
            if not (target / ".git").exists():
                row = [repo.name, rel_path, "-", "[dim]未 clone[/dim]", "-"]
                if check_worktrees:
                    row.append("-")
                table.add_row(*row)
                continue

            if fetch:
                from .git_ops import fetch as git_fetch
                git_fetch(target)

            branch = current_branch(target)
            branch_display = f"{branch} [yellow]⚡local[/yellow]" if repo.has_local_override else branch
            dirty = is_dirty(target)
            dirty_label = "[red]有改动[/red]" if dirty else "[green]干净[/green]"
            a, b = ahead_behind(target)
            sync_parts = []
            if a:
                sync_parts.append(f"[yellow]↑{a}[/yellow]")
            if b:
                sync_parts.append(f"[yellow]↓{b}[/yellow]")
            sync_label = " ".join(sync_parts) if sync_parts else "[green]同步[/green]"

            row = [repo.name, rel_path, branch_display, dirty_label, sync_label]

            if check_worktrees:
                wts = list_worktrees(target)
                extra = [w for w in wts if w.get("path") != str(target.resolve())]
                if extra:
                    wt_labels = [f"{w.get('branch', '?')}" for w in extra]
                    row.append("[magenta]" + ", ".join(wt_labels) + "[/magenta]")
                else:
                    row.append("[dim]无[/dim]")

            table.add_row(*row)

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
            override_tag = " [yellow]⚡local[/yellow]" if repo.has_local_override else ""
            console.print(f"  [cyan]切换[/cyan] {repo.name} → {branch}{override_tag}")
            result = checkout(target, branch)
            if result.ok:
                console.print(f"       [green]✓[/green]")
            else:
                console.print(f"       [red]✗ {result.error}[/red]")


# ── monarbor local ───────────────────────────────────────────


def _load_local_yaml(root: Path) -> dict:
    local_path = root / LOCAL_CONFIG_FILENAME
    if not local_path.exists():
        return {"repos": []}
    import yaml
    with open(local_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "repos" not in data:
        data["repos"] = []
    return data


def _save_local_yaml(root: Path, data: dict) -> None:
    import yaml
    local_path = root / LOCAL_CONFIG_FILENAME
    with open(local_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    _ensure_gitignore(root)


def _ensure_in_gitignore(root: Path, entry: str) -> None:
    """确保指定条目在 .gitignore 中。"""
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip() == entry:
                return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore_path.write_text(content, encoding="utf-8")
    else:
        gitignore_path.write_text(f"{entry}\n", encoding="utf-8")


def _ensure_in_git_exclude(repo_path: Path, entry: str) -> None:
    """确保指定条目在 .git/info/exclude 中（本地排除，不影响工作区，不产生 unstaged changes）。"""
    exclude_path = repo_path / ".git" / "info" / "exclude"
    if not exclude_path.parent.exists():
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
    if exclude_path.exists():
        content = exclude_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip() == entry:
                return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        exclude_path.write_text(content, encoding="utf-8")
    else:
        exclude_path.write_text(f"{entry}\n", encoding="utf-8")


def _ensure_gitignore(root: Path) -> None:
    """确保 mona.local.yaml 在 .gitignore 中。"""
    _ensure_in_gitignore(root, LOCAL_CONFIG_FILENAME)


@main.group(name="local")
def local_group():
    """管理本地分支覆盖 (mona.local.yaml)。"""
    pass


@local_group.command(name="list")
def local_list():
    """查看当前所有本地覆盖。"""
    root = find_root()
    data = _load_local_yaml(root)
    repos = data.get("repos", [])
    if not repos:
        console.print("[dim]无本地覆盖 (mona.local.yaml 不存在或为空)[/dim]")
        return

    table = Table(title="本地覆盖")
    table.add_column("路径", style="bold")
    table.add_column("覆盖字段")

    for repo in repos:
        path = repo.get("path", "(unknown)")
        branches = repo.get("branches", {})
        parts = [f"{k}={v}" for k, v in branches.items()]
        table.add_row(path, ", ".join(parts) if parts else "[dim]无分支覆盖[/dim]")

    console.print(table)


@local_group.command(name="set")
@click.argument("repo_path")
@click.argument("branch")
@click.option("-t", "--branch-type", type=click.Choice(["dev", "test", "prod"]), default="dev", help="覆盖哪个分支类型 (默认 dev)")
def local_set(repo_path: str, branch: str, branch_type: str):
    """为指定 repo 设置本地分支覆盖。

    示例: monarbor local set infra/argusai feat/new-api
    """
    root = find_root()

    config = MonorepoConfig.load(root)
    known_paths = {r.path for r in config.repos}
    if repo_path not in known_paths:
        raise click.ClickException(f"路径 {repo_path} 不在 mona.yaml 中，已知路径: {', '.join(sorted(known_paths))}")

    data = _load_local_yaml(root)
    repos = data.get("repos", [])

    target = None
    for r in repos:
        if r.get("path") == repo_path:
            target = r
            break

    if target is None:
        target = {"path": repo_path, "branches": {}}
        repos.append(target)

    if "branches" not in target:
        target["branches"] = {}
    target["branches"][branch_type] = branch
    data["repos"] = repos

    _save_local_yaml(root, data)
    console.print(f"[green]✓[/green] {repo_path} 的 {branch_type} 分支已覆盖为 [cyan]{branch}[/cyan]")


@local_group.command(name="unset")
@click.argument("repo_path")
def local_unset(repo_path: str):
    """移除指定 repo 的所有本地覆盖。"""
    root = find_root()
    data = _load_local_yaml(root)
    repos = data.get("repos", [])
    original_len = len(repos)
    repos = [r for r in repos if r.get("path") != repo_path]

    if len(repos) == original_len:
        console.print(f"[yellow]未找到[/yellow] {repo_path} 的本地覆盖")
        return

    data["repos"] = repos
    _save_local_yaml(root, data)
    console.print(f"[green]✓[/green] 已移除 {repo_path} 的本地覆盖")


@local_group.command(name="clear")
@click.confirmation_option(prompt="确认清除所有本地覆盖？")
def local_clear():
    """清除所有本地覆盖。"""
    root = find_root()
    local_path = root / LOCAL_CONFIG_FILENAME
    if local_path.exists():
        local_path.unlink()
        console.print("[green]✓[/green] 已删除 mona.local.yaml")
    else:
        console.print("[dim]mona.local.yaml 不存在，无需清除[/dim]")


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
    _ensure_gitignore(Path.cwd())
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
