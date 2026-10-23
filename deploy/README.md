# monarbor doctor nightly 部署

每天自动在大仓根跑一遍 `monarbor doctor`（文档事实断言表），结果落盘内部
日志目录。对应 plaita#318 建议③；**实装与否由 owner 拍板**，本目录只交付
可安装单元与说明。

## 交付物

| 文件 | 说明 |
|------|------|
| `doctor-nightly.sh` | 执行脚本：探测带 PyYAML 的 python3 → `PYTHONPATH` 注入子仓源码跑 `python3 -m monarbor doctor --json` → 汇总行追加 `doctor.jsonl` + 完整结果写 `doctor-latest.json`；退出码 = doctor 退出码 |
| `cc.jeffkit.monarbor-doctor.plist` | launchd LaunchAgent（macOS 部署机），每天 08:47 触发 |

## 安装（macOS / launchd）

```bash
# 1. 安装 LaunchAgent（路径按实际部署机调整）
mkdir -p ~/Library/LaunchAgents ~/.local/state/monarbor
cp deploy/cc.jeffkit.monarbor-doctor.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/cc.jeffkit.monarbor-doctor.plist

# 2. 加载并即刻验证（手动触发一次）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/cc.jeffkit.monarbor-doctor.plist
launchctl kickstart gui/$(id -u)/cc.jeffkit.monarbor-doctor

# 3. 看结果
tail -3 ~/.local/state/monarbor/doctor.jsonl      # 每行：时间 exit=0/1 passed=50/50
python3 -m json.tool ~/.local/state/monarbor/doctor-latest.json | head
```

卸载：`launchctl bootout gui/$(id -u)/cc.jeffkit.monarbor-doctor && rm ~/Library/LaunchAgents/cc.jeffkit.monarbor-doctor.plist`。

## 安装（Linux / systemd timer，备选形制）

```bash
sudo tee /etc/systemd/system/monarbor-doctor.service <<'EOF'
[Unit]
Description=monarbor doctor nightly
[Service]
Type=oneshot
User=<部署用户>
ExecStart=/path/to/monarbor/deploy/doctor-nightly.sh
Environment=MONOREPO_ROOT=/path/to/infra4agent
EOF
sudo tee /etc/systemd/system/monarbor-doctor.timer <<'EOF'
[Unit]
Description=monarbor doctor nightly
[Timer]
OnCalendar=*-*-* 08:47:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
sudo systemctl enable --now monarbor-doctor.timer
```

cron 形制：`47 8 * * * /path/to/monarbor/deploy/doctor-nightly.sh`。

## 行为与开关

- **日志**：`~/.local/state/monarbor/`（`doctor.jsonl` 逐日汇总、
  `doctor-latest.json` 完整结果、`doctor.log` stderr）。可用
  `MONARBOR_DOCTOR_LOG_DIR` 改道。
- **红 → 开 issue**：默认**关**（只落日志）。置
  `MONARBOR_DOCTOR_OPEN_ISSUE=1` 后，红则复用环境既有 `gh` 登录态开单
  （不新增密钥），目标仓 `MONARBOR_DOCTOR_ISSUE_REPO`（默认
  `jeffkit/infra4agent`）。launchd 下经 plist 的 `EnvironmentVariables`
  传入。
- **退出码**：0 全绿 / 1 有红 / 2 环境失败（找不到解释器或大仓根），可被
  任何调度器消费。
- ** doctor 从子仓源码跑**（`PYTHONPATH=$MONOREPO_ROOT/monarbor`）：PyPI
  0.4.0 不含 doctor 命令；子仓 main（756a08a+）才含。

## 有意不做（待 owner 拍板）

- 未默认开启 issue webhook（见上，开关已备）；
- 未接入根仓 `.github/workflows/governance.yml`（issue 建议③备选，需只读
  token secret）；
- 本机未实装（交付即可，部署面由 owner 决定）。
