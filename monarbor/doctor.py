"""monarbor doctor —— 逐条执行文档事实断言表（``docs/DOC_ASSERTIONS.yml``）。

断言表把「文档声称的跨仓事实」写成机器可校验条目，每条 ``id = <repo>/<claim>``。
``monarbor doctor`` 在大仓根运行，逐条执行；失败即文档漂移，退出码 1。

本模块实现 ``DOC_ASSERTIONS.yml`` 中实际出现的全部 check 类型：

    file_exists / glob_min / regex_count / regex_contains / regex_contains_all /
    regex_not_contains / dep_present / entry_points_count /
    mona_paths_gitignored / table_rows_matches_mona / backtick_paths_exist

设计约定：
* 断言字段形状直接对齐大仓 ``docs/DOC_ASSERTIONS.yml``，不引入额外必填字段；
* 单条断言自身出错（格式错、文件缺失、未知 check）只记为该条失败，不中断整次执行；
* 断言表中的路径一律相对大仓根解析。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

DEFAULT_ASSERTIONS_FILE = "docs/DOC_ASSERTIONS.yml"


class CheckError(Exception):
    """断言条目自身格式错误（区别于「断言不成立」）。"""


@dataclass
class CheckResult:
    """一条断言的执行结果。"""

    id: str
    desc: str
    check: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "desc": self.desc,
            "check": self.check,
            "ok": self.ok,
            "detail": self.detail,
        }


# ── 通用工具 ─────────────────────────────────────────────────


def _require(assertion: dict, field_name: str) -> Any:
    value = assertion.get(field_name)
    if value is None:
        raise CheckError(f"缺少字段 {field_name!r}")
    return value


def _read_file(assertion: dict, root: Path) -> tuple[Path, str]:
    rel = assertion.get("file")
    if not rel:
        raise CheckError("缺少 file 字段")
    path = root / rel
    if not path.is_file():
        raise CheckError(f"文件不存在: {rel}")
    return path, path.read_text(encoding="utf-8")


def _regex_findall(pattern: str, text: str) -> list:
    return re.findall(pattern, text, re.MULTILINE)


# ── TOML 解析（tomllib → tomli → 内置极简解析器）──────────────
#
# 包声明 requires-python >= 3.9，而 tomllib 是 3.11+ 才进标准库；
# 又不希望为 doctor 新增依赖，故提供内置极简 TOML 子集解析器兜底。
# 只覆盖断言表涉及的结构：table / array-of-tables / key = string|array|inline-table。


def _strip_comment(line: str) -> str:
    """去掉行内 ``#`` 注释，忽略字符串内部的 ``#``。"""
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
                out.append(ch)
            elif ch == "#":
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def _split_outside_quotes(text: str, sep: str) -> list:
    """按 sep 切分，忽略字符串内部与 ``[]``/``{}`` 嵌套内部的 sep。"""
    parts = []
    buf = []
    quote = None
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _unquote_key(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _parse_key_path(raw: str) -> list:
    return [_unquote_key(p) for p in _split_outside_quotes(raw, ".") if p.strip()]


def _balanced(text: str) -> bool:
    quote = None
    depth = 0
    for ch in text:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth <= 0


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p) for p in _split_outside_quotes(inner, ",") if p.strip()]
    if raw.startswith("{") and raw.endswith("}"):
        table: dict = {}
        inner = raw[1:-1].strip()
        if not inner:
            return table
        for item in _split_outside_quotes(inner, ","):
            if "=" not in item:
                continue
            k, _, v = item.partition("=")
            _assign(table, _parse_key_path(k), _parse_scalar(v))
        return table
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _assign(table: dict, key_path: list, value: Any) -> None:
    for key in key_path[:-1]:
        nxt = table.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            table[key] = nxt
        table = nxt
    if key_path:
        table[key_path[-1]] = value


def _ensure_table(root: dict, key_path: list) -> dict:
    current = root
    for key in key_path:
        nxt = current.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            current[key] = nxt
        current = nxt
    return current


def _ensure_array_table(root: dict, key_path: list) -> dict:
    parent = _ensure_table(root, key_path[:-1])
    key = key_path[-1]
    seq = parent.get(key)
    if not isinstance(seq, list):
        seq = []
        parent[key] = seq
    table: dict = {}
    seq.append(table)
    return table


def parse_minimal_toml(text: str) -> dict:
    """极简 TOML 子集解析器（兜底用，非完整 TOML 实现）。"""
    root: dict = {}
    current: dict = root
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = _strip_comment(lines[i]).strip()
        i += 1
        if not stripped:
            continue
        if stripped.startswith("[[") and stripped.endswith("]]"):
            current = _ensure_array_table(root, _parse_key_path(stripped[2:-2]))
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = _ensure_table(root, _parse_key_path(stripped[1:-1]))
            continue
        if "=" not in stripped:
            continue
        key_part, _, value_part = stripped.partition("=")
        value_text = value_part.strip()
        while not _balanced(value_text) and i < len(lines):
            value_text += " " + _strip_comment(lines[i]).strip()
            i += 1
        _assign(current, _parse_key_path(key_part), _parse_scalar(value_text))
    return root


def _load_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # Python 3.11+  # type: ignore

        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli  # type: ignore

        return tomli.loads(text)
    except ImportError:
        pass
    return parse_minimal_toml(text)


def _load_structured(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".toml":
        return _load_toml(path)
    raise CheckError(f"不支持的依赖清单格式: {path.name}")


# ── check 实现 ───────────────────────────────────────────────


def check_file_exists(assertion: dict, root: Path) -> tuple[bool, str]:
    rel = assertion.get("path") or assertion.get("file")
    if not rel:
        raise CheckError("缺少 path 字段")
    path = root / rel
    return path.exists(), f"{rel} {'存在' if path.exists() else '不存在'}"


def check_glob_min(assertion: dict, root: Path) -> tuple[bool, str]:
    rel = _require(assertion, "path")
    pattern = _require(assertion, "pattern")
    minimum = int(_require(assertion, "min"))
    base = root / rel
    matches = sorted(base.glob(pattern)) if base.is_dir() else []
    return len(matches) >= minimum, f"{rel}/{pattern}: {len(matches)} 个（要求 >= {minimum}）"


def check_regex_count(assertion: dict, root: Path) -> tuple[bool, str]:
    _, text = _read_file(assertion, root)
    pattern = _require(assertion, "pattern")
    expected = int(_require(assertion, "equals"))
    found = _regex_findall(pattern, text)
    return (
        len(found) == expected,
        f"{assertion['file']}: 匹配 {len(found)} 处（要求 == {expected}），pattern={pattern!r}",
    )


def check_regex_contains(assertion: dict, root: Path) -> tuple[bool, str]:
    _, text = _read_file(assertion, root)
    pattern = _require(assertion, "pattern")
    ok = re.search(pattern, text, re.MULTILINE) is not None
    return ok, f"{assertion['file']}: {'命中' if ok else '未命中'} pattern={pattern!r}"


def check_regex_contains_all(assertion: dict, root: Path) -> tuple[bool, str]:
    _, text = _read_file(assertion, root)
    patterns = _require(assertion, "patterns")
    missing = [p for p in patterns if re.search(p, text, re.MULTILINE) is None]
    return (
        not missing,
        f"{assertion['file']}: {len(patterns) - len(missing)}/{len(patterns)} 命中"
        + (f"，缺失 {missing}" if missing else ""),
    )


def check_regex_not_contains(assertion: dict, root: Path) -> tuple[bool, str]:
    _, text = _read_file(assertion, root)
    pattern = _require(assertion, "pattern")
    hit = re.search(pattern, text, re.MULTILINE)
    return (
        hit is None,
        f"{assertion['file']}: {'未出现（符合）' if hit is None else '仍出现'} pattern={pattern!r}",
    )


def _norm_name(name: str) -> str:
    """PEP 503 风格名称归一化，兼容 ``-``/``_``/``.`` 差异。"""
    return re.sub(r"[-_.]+", "-", name).lower()


_GIT_PREFIXES = ("git+", "git:", "github:", "gitlab:", "bitbucket:")
_PATH_PREFIXES = ("file:", "link:", "workspace:", "path:", "../", "./", "/")


def _is_git_spec(spec: str) -> bool:
    low = spec.strip().lower()
    return low.startswith(_GIT_PREFIXES) or ("://" in low and "git" in low)


def _is_path_spec(spec: str) -> bool:
    low = spec.strip().lower()
    return low.startswith(_PATH_PREFIXES)


def _npm_dep_entries(data: Any, name: str) -> list:
    sections = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    entries = []
    for section in sections:
        deps = data.get(section) if isinstance(data, dict) else None
        if not isinstance(deps, dict):
            continue
        for key, spec in deps.items():
            if _norm_name(str(key)) == _norm_name(name):
                spec = str(spec)
                entries.append({
                    "spec": spec,
                    "git_pin": _is_git_spec(spec),
                    "path_pin": _is_path_spec(spec),
                    "where": section,
                })
    return entries


def _cargo_dep_entries(data: Any, name: str) -> list:
    sections = ("dependencies", "dev-dependencies", "build-dependencies")
    entries = []
    for section in sections:
        deps = data.get(section) if isinstance(data, dict) else None
        if not isinstance(deps, dict):
            continue
        for key, value in deps.items():
            if _norm_name(str(key)) != _norm_name(name):
                continue
            if isinstance(value, str):
                entries.append({"spec": value, "git_pin": False, "path_pin": False, "where": section})
            elif isinstance(value, dict):
                git = value.get("git")
                path = value.get("path")
                version = value.get("version")
                if version is not None:
                    spec = str(version)
                elif git:
                    spec = f"git:{git}"
                elif path:
                    spec = f"path:{path}"
                else:
                    spec = str(value)
                entries.append({
                    "spec": spec,
                    "git_pin": bool(git),
                    "path_pin": bool(path),
                    "where": section,
                })
    return entries


_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _pyp_dep_entries(data: Any, name: str) -> list:
    reqs: list = []
    project = data.get("project") if isinstance(data, dict) else None
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            reqs += [r for r in deps if isinstance(r, str)]
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for value in optional.values():
                if isinstance(value, list):
                    reqs += [r for r in value if isinstance(r, str)]
    entries = []
    for req in reqs:
        match = _PEP508_NAME.match(req)
        if not match or _norm_name(match.group(1)) != _norm_name(name):
            continue
        spec = req.strip()
        entries.append({
            "spec": spec,
            "git_pin": _is_git_spec(spec),
            "path_pin": _is_path_spec(spec),
            "where": "project.dependencies",
        })
    return entries


def check_dep_present(assertion: dict, root: Path) -> tuple[bool, str]:
    ecosystem = _require(assertion, "ecosystem")
    name = str(_require(assertion, "name"))
    version_re = assertion.get("version")
    no_git_pin = bool(assertion.get("no_git_pin"))
    path = root / _require(assertion, "file")
    if not path.is_file():
        raise CheckError(f"文件不存在: {assertion['file']}")
    data = _load_structured(path)

    if ecosystem == "npm":
        entries = _npm_dep_entries(data, name)
    elif ecosystem == "cargo":
        entries = _cargo_dep_entries(data, name)
    elif ecosystem == "pyp":
        entries = _pyp_dep_entries(data, name)
    else:
        raise CheckError(f"未知 ecosystem: {ecosystem!r}（支持 npm/cargo/pyp）")

    if not entries:
        return False, f"{assertion['file']}: 未找到依赖 {name}"

    reasons = []
    for entry in entries:
        if version_re and not re.search(version_re, entry["spec"]):
            reasons.append(f"版本不匹配（{entry['where']}: {entry['spec']!r}）")
            continue
        if no_git_pin and (entry["git_pin"] or entry["path_pin"]):
            reasons.append(f"git/path pin 不被允许（{entry['where']}: {entry['spec']!r}）")
            continue
        return True, f"{assertion['file']}: {name} = {entry['spec']!r}（{entry['where']}）"
    return False, f"{assertion['file']}: {name} 不满足 — " + "；".join(reasons)


def check_entry_points_count(assertion: dict, root: Path) -> tuple[bool, str]:
    rel = _require(assertion, "file")
    group = _require(assertion, "group")
    expected = int(_require(assertion, "equals"))
    path = root / rel
    if not path.is_file():
        raise CheckError(f"文件不存在: {rel}")
    data = _load_toml(path)
    project = data.get("project") if isinstance(data, dict) else None
    entry_points = project.get("entry-points") if isinstance(project, dict) else None
    table = entry_points.get(group) if isinstance(entry_points, dict) else None
    count = len(table) if isinstance(table, dict) else 0
    return (
        count == expected,
        f"{rel}: [{group}] {count} 个 entry point（要求 == {expected}）",
    )


def _gitignore_rules(text: str) -> list:
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        line = line.lstrip("/").rstrip("/")
        if line:
            rules.append(line)
    return rules


def _covered_by_gitignore(path: str, rules: list) -> bool:
    target = path.strip("/")
    return any(target == rule or target.startswith(rule + "/") for rule in rules)


def check_mona_paths_gitignored(assertion: dict, root: Path) -> tuple[bool, str]:
    mona = root / "mona.yaml"
    if not mona.is_file():
        raise CheckError("mona.yaml 不存在")
    data = yaml.safe_load(mona.read_text(encoding="utf-8")) or {}
    paths = [r.get("path") for r in (data.get("repos") or []) if r.get("path")]
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return False, ".gitignore 不存在"
    rules = _gitignore_rules(gitignore.read_text(encoding="utf-8"))
    missing = [p for p in paths if not _covered_by_gitignore(p, rules)]
    if missing:
        return False, f"{len(missing)}/{len(paths)} 个子仓 path 未被 .gitignore 覆盖: {', '.join(missing)}"
    return True, f"{len(paths)} 个子仓 path 全部被 .gitignore 覆盖"


def check_table_rows_matches_mona(assertion: dict, root: Path) -> tuple[bool, str]:
    mona = root / "mona.yaml"
    if not mona.is_file():
        raise CheckError("mona.yaml 不存在")
    data = yaml.safe_load(mona.read_text(encoding="utf-8")) or {}
    expected = len(data.get("repos") or [])
    _, text = _read_file(assertion, root)
    pattern = _require(assertion, "pattern")
    rows = len(_regex_findall(pattern, text))
    return rows == expected, f"{assertion['file']}: {rows} 行（mona.yaml {expected} 个子仓）"


def _looks_like_path(span: str) -> bool:
    """判断反引号片段是否是需要校验存在的「路径」而非普通词/命令。"""
    if not span or span.startswith("/"):  # /slash 形式的 skill / 命令名
        return False
    if "://" in span:  # URL
        return False
    if "/" not in span:  # 裸文件名不算「代码路径」
        return False
    if span.startswith("~") or "<" in span or ">" in span:
        return False
    return True


def _expand_braces(span: str) -> list:
    match = re.search(r"\{([^{}]*)\}", span)
    if not match:
        return [span]
    out = []
    for part in match.group(1).split(","):
        out.extend(_expand_braces(span[: match.start()] + part + span[match.end():]))
    return out


def check_backtick_paths_exist(assertion: dict, root: Path) -> tuple[bool, str]:
    _, text = _read_file(assertion, root)
    allow = [str(x) for x in (assertion.get("allow") or [])]
    spans = re.findall(r"`([^`]+)`", text)
    checked = 0
    missing = []
    for span in spans:
        candidate = span.strip()
        if not _looks_like_path(candidate):
            continue
        if any(candidate.startswith(prefix) for prefix in allow):
            continue
        for expanded in _expand_braces(candidate):
            checked += 1
            if any(ch in expanded for ch in "*?["):
                if not list(root.glob(expanded)):
                    missing.append(expanded)
            elif not (root / expanded).exists():
                missing.append(expanded)
    if missing:
        shown = ", ".join(sorted(set(missing))[:10])
        return False, f"{assertion['file']}: {len(set(missing))} 个引用路径不存在: {shown}"
    return True, f"{assertion['file']}: {checked} 个引用路径全部存在"


CHECKS: dict[str, Callable[[dict, Path], tuple[bool, str]]] = {
    "file_exists": check_file_exists,
    "glob_min": check_glob_min,
    "regex_count": check_regex_count,
    "regex_contains": check_regex_contains,
    "regex_contains_all": check_regex_contains_all,
    "regex_not_contains": check_regex_not_contains,
    "dep_present": check_dep_present,
    "entry_points_count": check_entry_points_count,
    "mona_paths_gitignored": check_mona_paths_gitignored,
    "table_rows_matches_mona": check_table_rows_matches_mona,
    "backtick_paths_exist": check_backtick_paths_exist,
}


def load_assertions(path: Path) -> list:
    """读取断言表，返回 assertions 列表。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("断言表根节点必须是 mapping")
    assertions = data.get("assertions")
    if not isinstance(assertions, list):
        raise ValueError("断言表缺少 assertions 列表")
    return assertions


def run_assertions(assertions: list, root: Path) -> list:
    """逐条执行断言，任何单条错误都只记为该条失败。"""
    root = Path(root)
    results = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            results.append(CheckResult("(invalid)", "", "", False, f"断言条目不是 mapping: {assertion!r}"))
            continue
        aid = str(assertion.get("id", "(no id)"))
        desc = str(assertion.get("desc", ""))
        kind = str(assertion.get("check", ""))
        fn = CHECKS.get(kind)
        if fn is None:
            results.append(CheckResult(aid, desc, kind, False, f"未实现的 check 类型: {kind!r}"))
            continue
        try:
            ok, detail = fn(assertion, root)
        except CheckError as e:
            ok, detail = False, f"断言格式错误: {e}"
        except FileNotFoundError as e:
            ok, detail = False, f"文件不存在: {e}"
        except Exception as e:  # noqa: BLE001 — 单条断言异常不应中断整表
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append(CheckResult(aid, desc, kind, ok, detail))
    return results
