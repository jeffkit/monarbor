# 更新日志

本文件记录 monarbor 每个发布版本的实际变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
PyPI 版本页描述随版本固化不可回改，**本文件是唯一持续可更正的发布史**。

## [0.5.2] - 2026-10-28

### 修复
- `doctor --init` 模板改为**空表起步**（`assertions: []`）：原模板自带 3 条依赖大仓结构的示例断言，
  在「还不是大仓」的空目录首跑即 0/3 红；示例断言整体注释保留，按需启用，空目录起步即绿。

### 文档
- README 安装段新增「📌 版本页说明」：PyPI 描述随版本固化，0.5.0 及更早版本页上的
  「发布新版本前暂缓安装」警告为历史文案（针对已修复的 0.4.0 缺陷），见到即说明打开的是旧版本页。

## [0.5.1] - 2026-10-28

### 修复
- `mona_paths_gitignored` 改为调用 `git check-ignore --no-index` 判定：白名单式 `.gitignore`
  （`/*` + `!` 放行）在原字面前缀解析下会被全量误报为「未被覆盖」；negation、`**/`、
  嵌套 .gitignore、`.git/info/exclude` 亦随之正确生效。非 git 环境回退字面解析并在 detail 标注。
- 缺断言表时 `doctor` 改为**跳过并退出 0**（原与「断言不成立」同为退出码 1，导致未配置断言表的
  仓库无法在 CI 挂载 doctor）；`--json` 输出加 `"skipped": true`；`--strict` 显式恢复强制报错；
  显式 `--file` 指向不存在文件仍视为配置错误。

### 新增
- 断言表解析序：mona.yaml `assertions:` 字段 → `.monarbor/assertions.yml` →
  `docs/DOC_ASSERTIONS.yml` → `DOC_ASSERTIONS.yml`（原只认最后一项）。
- `monarbor doctor --init`：生成带注释的断言表起步模板，已存在则拒绝。

### 文档
- README 安装段改回 `pipx install monarbor` 主路径（0.5.0 发布后「从仓库安装」绕行已过时）；
- `publish.yml` 新增发布守卫：README「请勿安装」类过期文案 grep 拦截 + `twine check`
  （PyPI long_description 随版本固化，0.5.0 曾把过期劝退文案打进项目页）。

## [0.5.0] - 2026-10-28

> ⚠️ 本版本 PyPI 页描述含过时的「请勿安装」警告（随版本固化不可回改）——该警告仅对 0.4.0
> 及更早版本成立，**0.5.0 本身即含全部修复**，可直接安装。

### 修复
- 嵌套扫描加固（`756a08a`）：不跟随符号链接、剪枝 `node_modules`、深度上限——修复
  `monarbor list` 在 deepseek-harness 软链环上崩溃（`OSError [Errno 63]`，缺陷 A）；
  修复 `list_repos` 漏传排除集（缺陷 B）。附带 8 个回归测试。
- 附带修复后，PyPI 0.4.0 及更早版本的上述缺陷不再存在。

### 新增
- `monarbor doctor` 文档事实断言命令（`756a08a`）：逐条执行 `docs/DOC_ASSERTIONS.yml`，
  失败退出码 1；含 `file_exists` / `glob_min` / `regex_*` / `dep_present`（npm/cargo/pyp）/
  `entry_points_count` / `mona_paths_gitignored` / `table_rows_matches_mona` /
  `backtick_paths_exist` 等 check 类型。
- `yaml_path_equals` check（`2ccc989`）：结构化账本断言（gov/* 治理账本配套）。
- `python -m monarbor` 模块入口（`2ccc989`）。
- `deploy/` nightly 部署单元（launchd plist + doctor-nightly.sh，`2ccc989`）。

## [0.4.0] - 2026-04-16

### 修复
- 嵌套逻辑大仓的递归发现与克隆（PR #1，`5fcf53e`）。
- `.worktrees/` 改写入 `.git/info/exclude`，避免污染宿主仓工作区状态（`6b4cee6`）。

### 新增
- `clone` 浅克隆与并行参数：`--shallow/--depth/--git-filter/--single-branch/--no-tags/--jobs/--timeout`（`2edaf8d`）。

## [0.3.0] - 2026-04-02

### 修复
- `clone -r` 递归 clone 嵌套大仓子仓库，`pull` 显示未 clone 仓库（`8710274`）。
- `clone` 到已有非空目录时改用 init+remote+fetch 方式（`c0e6493`）。

### 新增
- `clone` 时自动同步已存在仓库的 remote URL（`f1882c6`）。

## [0.2.1] - 2026-03-24

- 随 `clone` 到已有非空目录改用 init+remote+fetch（`c0e6493`）的补丁版。

## [0.2.0] - 2026-03-11

### 新增
- `mona.local.yaml` 本地分支覆盖（不入库）（`7670884`）。
- worktree 约定推广（`7670884`）。

## [0.1.0] - 2026-03-07

### 新增
- 初版：`init / add / clone / pull / status / list / exec / checkout` 命令集，
  `mona.yaml` 单一清单文件（`b998e79`、`f077df2`）。
- GitHub Actions PyPI 自动发布（tag 推送触发，Trusted Publishing）（`2e6663b`）。

[0.5.2]: https://github.com/jeffkit/monarbor/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/jeffkit/monarbor/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/jeffkit/monarbor/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jeffkit/monarbor/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/jeffkit/monarbor/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/jeffkit/monarbor/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jeffkit/monarbor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jeffkit/monarbor/releases/tag/v0.1.0
