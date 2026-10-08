# Monarbor

AI 友好的逻辑大仓命令行工具。一个 `mona.yaml` 配置文件描述所有仓库，一套命令统一管理。

## 安装

> ⚠️ **PyPI 上的 0.4.0 早于本轮修复**：软链环崩溃（缺陷 A）与 `list` 漏传排除集（缺陷 B）
> 在 PyPI 0.4.0 中仍存在，且尚无新版本发布。**在发布新版本之前，请勿 `pip install monarbor`**，
> 改用下面的「从仓库安装」。

从仓库安装（推荐，含本轮修复）：

```bash
# 从 GitHub 安装
pipx install git+https://github.com/jeffkit/monarbor.git

# 或从本地 checkout 安装
pipx install /path/to/monarbor
```

开发模式安装：

```bash
pip install -e .
```

未安装时也可直接用源码运行：

```bash
PYTHONPATH=/path/to/monarbor python -m monarbor list
```

## 快速开始

```bash
# 初始化一个逻辑大仓
monarbor init

# 添加仓库
monarbor add --path business-a/frontend --name "前端项目" --url "https://git.example.com/org/frontend.git"

# 拉取所有代码
monarbor clone

# 查看状态
monarbor status
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `monarbor clone` | 拉取大仓下所有项目代码 |
| `monarbor pull` | 更新所有已 clone 仓库的代码 |
| `monarbor status` | 显示所有仓库的分支、改动、同步状态 |
| `monarbor list` | 以树形结构列出所有仓库 |
| `monarbor doctor` | 逐条执行 `docs/DOC_ASSERTIONS.yml` 文档事实断言，失败退出码 1 |
| `monarbor exec <cmd>` | 在所有仓库中执行命令 |
| `monarbor checkout <dev\|test\|prod>` | 批量切换到指定分支类型 |
| `monarbor init` | 初始化新的逻辑大仓 |
| `monarbor add` | 向当前大仓添加仓库 |

## 常用场景

### 拉取所有代码

```bash
# 默认 clone dev 分支
monarbor clone

# clone 测试分支
monarbor clone -b test

# 递归 clone（包括嵌套的子逻辑大仓）
monarbor clone -r

# 只 clone 某个业务线
monarbor clone --filter business-a
```

### 批量切换分支

```bash
# 全部切到测试分支
monarbor checkout test

# 全部切到生产分支
monarbor checkout prod
```

### 批量执行命令

```bash
# 查看每个仓库最近 5 条提交
monarbor exec "git log --oneline -5"

# 全部安装依赖
monarbor exec "npm install"

# 只在某个业务线执行
monarbor exec "pnpm build" --filter business-a
```

### 嵌套逻辑大仓

当子目录下存在自己的 `mona.yaml` 时，带 `-r` 参数即可递归处理：

```bash
monarbor clone -r      # 递归 clone
monarbor status -r     # 递归查看状态
monarbor list -r       # 递归列出树形结构
```

### 文档事实体检

大仓可在 `docs/DOC_ASSERTIONS.yml` 里把「文档声称的跨仓事实」写成机器可校验断言，
`monarbor doctor` 逐条执行；任一失败即文档漂移，退出码 1：

```bash
cd <大仓根>
monarbor doctor                 # 人读输出
monarbor doctor --json          # CI 消费
monarbor doctor --file path/to/DOC_ASSERTIONS.yml
```

支持的 check 类型：`file_exists`、`glob_min`、`regex_count`、`regex_contains`、
`regex_contains_all`、`regex_not_contains`、`dep_present`（npm/cargo/pyp）、
`entry_points_count`、`mona_paths_gitignored`、`table_rows_matches_mona`、
`backtick_paths_exist`。

## mona.yaml 格式

```yaml
name: "我的大仓"
description: "大仓描述"
owner: your-name

repos:
  - path: business-a/frontend
    name: "前端项目"
    repo_url: "https://git.example.com/org/frontend.git"
    tech_stack: [typescript, react]
    branches:
      dev: develop
      test: release/test
      prod: main
```

## License

MIT
