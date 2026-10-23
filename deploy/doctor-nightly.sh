#!/bin/bash
# monarbor doctor nightly —— 每天在大仓根跑一遍文档事实断言表，结果落内部日志目录。
#
# 调用方：launchd（同目录 cc.jeffkit.monarbor-doctor.plist）、cron 或手动。
# 退出码 = doctor 退出码（0 全绿 / 1 有红 / 2 环境失败），便于调度器告警。
# doctor 必须从子仓源码跑（PYTHONPATH 注入），PyPI 0.4.0 无 doctor 命令。
#
# 环境变量（均有默认值）：
#   MONOREPO_ROOT               大仓根路径
#   MONARBOR_DOCTOR_LOG_DIR     日志目录（默认 ~/.local/state/monarbor）
#   MONARBOR_DOCTOR_PYTHON      python 解释器（默认自动探测一个带 PyYAML 的）
#   MONARBOR_DOCTOR_OPEN_ISSUE  置 1 时红则经 gh 开 issue（复用环境既有 gh
#                               登录态，不新增密钥；默认 0=只落日志）
#   MONARBOR_DOCTOR_ISSUE_REPO  开 issue 的目标仓（默认 jeffkit/infra4agent）

set -u
MONOREPO_ROOT="${MONOREPO_ROOT:-/Users/kong/projects/infra4agent}"
LOG_DIR="${MONARBOR_DOCTOR_LOG_DIR:-$HOME/.local/state/monarbor}"
ISSUE_REPO="${MONARBOR_DOCTOR_ISSUE_REPO:-jeffkit/infra4agent}"
OPEN_ISSUE="${MONARBOR_DOCTOR_OPEN_ISSUE:-0}"

mkdir -p "$LOG_DIR" || exit 2

# launchd 的 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，而系统 python3 无 PyYAML，
# 故按候选序探测；命中第一个能 import yaml 的解释器即用。
PYTHON_BIN="${MONARBOR_DOCTOR_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
        if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import yaml' >/dev/null 2>&1; then
            PYTHON_BIN="$cand"
            break
        fi
    done
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "$(date '+%F %T') [env] 找不到带 PyYAML 的 python3（可用 MONARBOR_DOCTOR_PYTHON 指定）" >> "$LOG_DIR/doctor.log"
    exit 2
fi

cd "$MONOREPO_ROOT" || { echo "$(date '+%F %T') [env] 大仓根不存在: $MONOREPO_ROOT" >> "$LOG_DIR/doctor.log"; exit 2; }

ts="$(date '+%F %T')"
PYTHONPATH="$MONOREPO_ROOT/monarbor" "$PYTHON_BIN" -m monarbor doctor --json \
    > "$LOG_DIR/doctor-latest.json" 2>> "$LOG_DIR/doctor.log"
code=$?

summary="$("$PYTHON_BIN" -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    print("%d/%d" % (d.get("passed", 0), d.get("total", 0)))
except Exception:
    print("unreadable")' "$LOG_DIR/doctor-latest.json")"

echo "$ts exit=$code passed=$summary python=$PYTHON_BIN" >> "$LOG_DIR/doctor.jsonl"

# 红则可选开 issue（默认关；失败不影响退出码语义）
if [ "$code" -ne 0 ] && [ "$OPEN_ISSUE" = "1" ] && command -v gh >/dev/null 2>&1; then
    failed="$("$PYTHON_BIN" -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
    print("\n".join("- `%s` (%s): %s" % (r["id"], r["check"], r["detail"])
                    for r in d.get("results", []) if not r.get("ok")))
except Exception as e:
    print("（结果文件不可解析: %s）" % e)' "$LOG_DIR/doctor-latest.json" 2>/dev/null)"
    gh issue create -R "$ISSUE_REPO" \
        --title "chore(doctor): nightly 红 $ts（$summary）" \
        --body "monarbor doctor nightly 发现文档漂移（退出码 $code）。

$failed

完整结果：部署机 \`$LOG_DIR/doctor-latest.json\`（由 launchd cc.jeffkit.monarbor-doctor 生成）。" \
        > /dev/null 2>&1 || true
fi

exit "$code"
