"""``python -m monarbor`` —— 与 ``monarbor`` 命令等价的模块入口。

供未安装（pipx 外）的调用方免 entry-point 使用，例如 nightly 调度器：

    PYTHONPATH=<大仓根>/monarbor python3 -m monarbor doctor --json
"""

from .cli import main

main()
