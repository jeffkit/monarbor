# Monarbor

AI 友好的逻辑大仓命令行工具。一个 `monorepo.yaml` 配置文件描述所有仓库，一套命令统一管理。

## 安装

```bash
pip install monarbor
```

开发模式安装：

```bash
pip install -e .
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

当子目录下存在自己的 `monorepo.yaml` 时，带 `-r` 参数即可递归处理：

```bash
monarbor clone -r      # 递归 clone
monarbor status -r     # 递归查看状态
monarbor list -r       # 递归列出树形结构
```

## monorepo.yaml 格式

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
