"""monarbor doctor 的断言执行测试。

全部用临时目录 + 迷你 mona.yaml / 断言表构造，不依赖真实大仓，
保证 check 语义（含 4 种 ecosystem 依赖、entry point、gitignore、表格行数、
反引号路径）都被独立覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from monarbor.cli import main
from monarbor.doctor import load_assertions, parse_minimal_toml, run_assertions


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_mona(root: Path, repos: list) -> None:
    _write(root, "mona.yaml", yaml.dump(
        {"name": "t", "owner": "t", "repos": repos}, allow_unicode=True,
    ))


def _run(root: Path, assertions: list):
    return {r.id: r for r in run_assertions(assertions, root)}


# 1 ── file_exists

def test_file_exists_pass_and_fail(tmp_path: Path):
    _write(tmp_path, "src/ok.py", "x = 1\n")
    results = _run(tmp_path, [
        {"id": "exists", "check": "file_exists", "path": "src/ok.py"},
        {"id": "missing", "check": "file_exists", "path": "src/nope.py"},
    ])
    assert results["exists"].ok
    assert not results["missing"].ok


# 2 ── glob_min

def test_glob_min(tmp_path: Path):
    _write(tmp_path, "bundles/a/lavs.json", "{}")
    _write(tmp_path, "bundles/b/lavs.json", "{}")
    results = _run(tmp_path, [
        {"id": "enough", "check": "glob_min", "path": "bundles", "pattern": "*/lavs.json", "min": 2},
        {"id": "not-enough", "check": "glob_min", "path": "bundles", "pattern": "*/lavs.json", "min": 3},
    ])
    assert results["enough"].ok
    assert not results["not-enough"].ok


# 3 ── regex_count

def test_regex_count(tmp_path: Path):
    _write(tmp_path, "m.py", "def test_a():\n    pass\ndef test_b():\n    pass\n")
    results = _run(tmp_path, [
        {"id": "exact", "check": "regex_count", "file": "m.py", "pattern": "^def test_", "equals": 2},
        {"id": "wrong", "check": "regex_count", "file": "m.py", "pattern": "^def test_", "equals": 3},
    ])
    assert results["exact"].ok
    assert not results["wrong"].ok


# 4 ── regex_contains / regex_contains_all / regex_not_contains

def test_regex_contains_family(tmp_path: Path):
    _write(tmp_path, "r.txt", "alpha beta gamma\n")
    results = _run(tmp_path, [
        {"id": "contains", "check": "regex_contains", "file": "r.txt", "pattern": "beta"},
        {"id": "contains-miss", "check": "regex_contains", "file": "r.txt", "pattern": "delta"},
        {"id": "all-ok", "check": "regex_contains_all", "file": "r.txt", "patterns": ["alpha", "gamma"]},
        {"id": "all-miss", "check": "regex_contains_all", "file": "r.txt", "patterns": ["alpha", "delta"]},
        {"id": "not-ok", "check": "regex_not_contains", "file": "r.txt", "pattern": "zeta"},
        {"id": "not-miss", "check": "regex_not_contains", "file": "r.txt", "pattern": "alpha"},
    ])
    assert results["contains"].ok
    assert not results["contains-miss"].ok
    assert results["all-ok"].ok
    assert not results["all-miss"].ok
    assert results["not-ok"].ok
    assert not results["not-miss"].ok


# 5 ── dep_present: npm

def test_dep_present_npm(tmp_path: Path):
    _write(tmp_path, "package.json", json.dumps({"dependencies": {"agentproc": "^0.1.1"}}))
    results = _run(tmp_path, [
        {"id": "ok", "check": "dep_present", "file": "package.json", "ecosystem": "npm",
         "name": "agentproc", "version": r"\^0\.1\.1"},
        {"id": "bad-version", "check": "dep_present", "file": "package.json", "ecosystem": "npm",
         "name": "agentproc", "version": r"\^0\.9"},
        {"id": "missing", "check": "dep_present", "file": "package.json", "ecosystem": "npm",
         "name": "nope"},
    ])
    assert results["ok"].ok
    assert not results["bad-version"].ok
    assert not results["missing"].ok


# 6 ── dep_present: pyp

def test_dep_present_pyp(tmp_path: Path):
    _write(tmp_path, "pyproject.toml",
           '[project]\nname = "x"\n'
           'dependencies = ["plaita>=0.5.0", "agentproc>=0.15.0"]\n')
    results = _run(tmp_path, [
        {"id": "plaita", "check": "dep_present", "file": "pyproject.toml", "ecosystem": "pyp",
         "name": "plaita", "version": r">=0\.5\.0"},
        {"id": "agentproc", "check": "dep_present", "file": "pyproject.toml", "ecosystem": "pyp",
         "name": "agentproc", "version": r">=0\.15\.0"},
        {"id": "missing", "check": "dep_present", "file": "pyproject.toml", "ecosystem": "pyp",
         "name": "requests"},
    ])
    assert results["plaita"].ok
    assert results["agentproc"].ok
    assert not results["missing"].ok


# 7 ── dep_present: cargo

def test_dep_present_cargo(tmp_path: Path):
    _write(tmp_path, "Cargo.toml", '[dependencies]\nagentproc = "0.11.1"\n')
    results = _run(tmp_path, [
        {"id": "ok", "check": "dep_present", "file": "Cargo.toml", "ecosystem": "cargo",
         "name": "agentproc", "version": r"0\.11", "no_git_pin": True},
        {"id": "bad-version", "check": "dep_present", "file": "Cargo.toml", "ecosystem": "cargo",
         "name": "agentproc", "version": r"0\.9"},
    ])
    assert results["ok"].ok
    assert not results["bad-version"].ok


# 8 ── no_git_pin 拒绝 git / path pin

def test_dep_present_no_git_pin_rejects_git_or_path(tmp_path: Path):
    _write(tmp_path, "git-Cargo.toml",
           '[dependencies]\nagentproc = { git = "https://github.com/jeffkit/agentproc" }\n')
    _write(tmp_path, "path-Cargo.toml",
           '[dependencies]\nagentproc = { path = "../agentproc" }\n')
    _write(tmp_path, "pyproject.toml",
           '[project]\nname = "x"\ndependencies = ["agentproc @ git+https://github.com/jeffkit/agentproc"]\n')
    results = _run(tmp_path, [
        {"id": "cargo-git", "check": "dep_present", "file": "git-Cargo.toml", "ecosystem": "cargo",
         "name": "agentproc", "no_git_pin": True},
        {"id": "cargo-path", "check": "dep_present", "file": "path-Cargo.toml", "ecosystem": "cargo",
         "name": "agentproc", "no_git_pin": True},
        {"id": "pyp-git", "check": "dep_present", "file": "pyproject.toml", "ecosystem": "pyp",
         "name": "agentproc", "no_git_pin": True},
    ])
    assert not results["cargo-git"].ok
    assert not results["cargo-path"].ok
    assert not results["pyp-git"].ok


# 9 ── entry_points_count

def test_entry_points_count(tmp_path: Path):
    _write(tmp_path, "pyproject.toml",
           '[project.entry-points."my.nodes"]\n'
           'a = "pkg.a:A"\nb = "pkg.b:B"\n')
    results = _run(tmp_path, [
        {"id": "ok", "check": "entry_points_count", "file": "pyproject.toml",
         "group": "my.nodes", "equals": 2},
        {"id": "wrong", "check": "entry_points_count", "file": "pyproject.toml",
         "group": "my.nodes", "equals": 3},
    ])
    assert results["ok"].ok
    assert not results["wrong"].ok


# 10 ── mona_paths_gitignored

def test_mona_paths_gitignored(tmp_path: Path):
    _write_mona(tmp_path, [{"path": "alpha"}, {"path": "gamma"}])
    _write(tmp_path, ".gitignore", "/alpha/\n")
    bad = _run(tmp_path, [{"id": "g", "check": "mona_paths_gitignored"}])
    assert not bad["g"].ok
    assert "gamma" in bad["g"].detail

    _write(tmp_path, ".gitignore", "/alpha/\n/gamma/\n")
    good = _run(tmp_path, [{"id": "g", "check": "mona_paths_gitignored"}])
    assert good["g"].ok


# 11 ── table_rows_matches_mona

def test_table_rows_matches_mona(tmp_path: Path):
    _write_mona(tmp_path, [{"path": "a"}, {"path": "b"}])
    _write(tmp_path, "README.md", "| [A](a) |\n| [B](b) |\n")
    ok = _run(tmp_path, [{"id": "t", "check": "table_rows_matches_mona",
                          "file": "README.md", "pattern": r"^\| \["}])
    assert ok["t"].ok

    _write(tmp_path, "README.md", "| [A](a) |\n")
    bad = _run(tmp_path, [{"id": "t", "check": "table_rows_matches_mona",
                           "file": "README.md", "pattern": r"^\| \["}])
    assert not bad["t"].ok


# 12 ── backtick_paths_exist（含 allow 列表、brace/glob 展开）

def test_backtick_paths_exist_with_allow(tmp_path: Path):
    _write(tmp_path, "src/ok.py", "")
    _write(tmp_path, "src/a.py", "")
    _write(tmp_path, "src/b.py", "")
    _write(tmp_path, "lib/x.py", "")
    _write(tmp_path, "docs/MAP.md",
           "见 `src/ok.py`、`src/{a,b}.py`、`lib/*.py`、`src/allow/skip.py`、"
           "`main`、`/slash-cmd`、`https://example.com/x/y`\n")

    assertion = {"id": "p", "check": "backtick_paths_exist", "file": "docs/MAP.md",
                 "allow": ["src/allow/"]}
    assert _run(tmp_path, [assertion])["p"].ok

    without_allow = {"id": "p", "check": "backtick_paths_exist", "file": "docs/MAP.md"}
    bad = _run(tmp_path, [without_allow])["p"]
    assert not bad.ok
    assert "src/allow/skip.py" in bad.detail


# 13 ── CLI --json：失败退出码 1，输出机器可读

def test_cli_doctor_json_exit_code(tmp_path: Path, monkeypatch):
    _write(tmp_path, "a.txt", "")
    _write(tmp_path, "docs/DOC_ASSERTIONS.yml", yaml.dump({
        "version": 1,
        "assertions": [
            {"id": "pass", "desc": "ok", "check": "file_exists", "path": "a.txt"},
            {"id": "fail", "desc": "bad", "check": "file_exists", "path": "missing.txt"},
        ],
    }))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["doctor", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["total"] == 2 and payload["passed"] == 1 and payload["failed"] == 1
    assert payload["ok"] is False
    assert {r["id"] for r in payload["results"]} == {"pass", "fail"}


# 14 ── CLI 全绿退出码 0

def test_cli_doctor_all_pass_exit_zero(tmp_path: Path, monkeypatch):
    _write(tmp_path, "a.txt", "")
    _write(tmp_path, "docs/DOC_ASSERTIONS.yml", yaml.dump({
        "version": 1,
        "assertions": [{"id": "pass", "desc": "ok", "check": "file_exists", "path": "a.txt"}],
    }))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "全部通过" in result.output


# 15 ── 未知 check 只记为该条失败，不中断整表

def test_unknown_check_reported_as_failure(tmp_path: Path):
    results = run_assertions([
        {"id": "weird", "check": "not_a_real_check"},
        {"id": "fine", "check": "file_exists", "path": "."},
    ], tmp_path)
    by_id = {r.id: r for r in results}
    assert not by_id["weird"].ok
    assert "未实现的 check 类型" in by_id["weird"].detail
    assert by_id["fine"].ok


# 16 ── 内置极简 TOML 解析器（Python 3.9 无 tomllib 时的兜底）

def test_parse_minimal_toml_fallback():
    data = parse_minimal_toml(
        '[project]\n'
        'name = "x"\n'
        'dependencies = [\n'
        '  "plaita>=0.5.0",  # 行内注释\n'
        '  "agentproc>=0.15.0",\n'
        ']\n'
        '\n'
        '[project.entry-points."my.nodes"]\n'
        'a = "pkg.a:A"\n'
        'b = "pkg.b:B"\n'
        '\n'
        '[dependencies]\n'
        'agentproc = { version = "0.11", features = ["x", "y"] }\n'
    )
    assert data["project"]["name"] == "x"
    assert data["project"]["dependencies"] == ["plaita>=0.5.0", "agentproc>=0.15.0"]
    assert data["project"]["entry-points"]["my.nodes"] == {"a": "pkg.a:A", "b": "pkg.b:B"}
    assert data["dependencies"]["agentproc"]["version"] == "0.11"
    assert data["dependencies"]["agentproc"]["features"] == ["x", "y"]


# 17 ── load_assertions 对畸形断言表报错

def test_load_assertions_rejects_malformed(tmp_path: Path):
    _write(tmp_path, "bad.yml", "version: 1\n")
    try:
        load_assertions(tmp_path / "bad.yml")
    except ValueError as e:
        assert "assertions" in str(e)
    else:
        raise AssertionError("畸形断言表应抛 ValueError")
