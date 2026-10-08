"""断言包内 ``__version__`` 与 ``pyproject.toml`` 一致。

背景：上游 0.4.0 的 bump 提交只改了 ``pyproject.toml``、漏改
``monarbor/__init__.py``，而 ``click.version_option`` 读的是包内
``__version__``，导致 ``monarbor --version`` 在 0.4.0 上误报 0.3.0。
本测试防止后续 bump 再次漏改。
"""

from __future__ import annotations

import re
from pathlib import Path

import monarbor

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject():
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml 中找不到 version 字段"
    assert monarbor.__version__ == match.group(1), (
        f"__version__={monarbor.__version__!r} 与 pyproject version={match.group(1)!r} 漂移"
    )
